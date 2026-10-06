"""Transport factice loopback uniquement : aucun modèle, GPU ni caméra."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from threading import Event, Thread, Timer, enumerate as running_threads
from time import monotonic
import unittest
from unittest.mock import Mock, patch

from packages.harness.control import (
    ControlledChatClient,
    InferenceCancelled,
    InferenceControl,
    InferenceDeadlineExceeded,
)
from packages.harness.local_llm import LocalLLMClient


class FakeClock:
    now = 0.0

    def __call__(self):
        return self.now


class ControlTests(unittest.TestCase):
    def test_budget_is_shared_across_calls_and_strict_at_deadline(self):
        clock = FakeClock()
        control = InferenceControl(1.0, clock=clock)

        class Client:
            calls = 0

            def complete(self, _messages, _tools):
                self.calls += 1
                clock.now += 0.6
                return {"content": "ok"}

        client = Client()
        wrapped = ControlledChatClient(client, control)
        self.assertEqual(wrapped.complete([], []), {"content": "ok"})
        self.assertAlmostEqual(control.remaining_seconds(), 0.4)
        with self.assertRaises(InferenceDeadlineExceeded) as error:
            wrapped.complete([], [])
        self.assertEqual(client.calls, 2)
        self.assertEqual(error.exception.code, "inference_deadline_exceeded")
        clock.now = 1.0
        with self.assertRaises(InferenceDeadlineExceeded):
            control.check()

    def test_cancellation_before_call_and_after_callback_is_permanent(self):
        control = InferenceControl()
        control.cancel()
        self.assertTrue(control.cancelled)

        class NeverCalled:
            def complete(self, *_args):
                raise AssertionError("Ne doit pas transmettre")

        with self.assertRaises(InferenceCancelled) as error:
            ControlledChatClient(NeverCalled(), control).complete([], [])
        self.assertEqual(error.exception.code, "inference_cancelled")
        permission = [True]
        revoked = InferenceControl(should_continue=lambda: permission[0])
        permission[0] = False
        with self.assertRaises(InferenceCancelled):
            revoked.check()
        permission[0] = True
        with self.assertRaises(InferenceCancelled):
            revoked.check()

    def test_late_result_and_malformed_message_are_refused(self):
        control = InferenceControl()

        class LateClient:
            def complete(self, *_args):
                control.cancel()
                return {"content": "late"}

        with self.assertRaises(InferenceCancelled):
            ControlledChatClient(LateClient(), control).complete([], [])

        class ListClient:
            def complete(self, *_args):
                return []

        with self.assertRaises(ValueError):
            ControlledChatClient(ListClient(), InferenceControl()).complete([], [])

    def test_controlled_method_receives_same_shared_control(self):
        control = InferenceControl()

        class Client:
            def complete(self, *_args):
                raise AssertionError("Le transport contrôlé doit être utilisé")

            def complete_controlled(inner_self, messages, tools, received):
                self.assertIs(received, control)
                self.assertEqual(messages, [{"role": "user", "content": "test"}])
                self.assertEqual(tools, [])
                return {"content": "ok"}

        result = ControlledChatClient(Client(), control).complete(
            [{"role": "user", "content": "test"}], []
        )
        self.assertEqual(result, {"content": "ok"})

    def test_failed_permission_check_fails_closed(self):
        def failed_permission():
            raise RuntimeError("Session indisponible")

        control = InferenceControl(should_continue=failed_permission)
        with self.assertRaises(InferenceCancelled):
            control.check()
        self.assertTrue(control.cancelled)

    def test_invalid_budgets_and_deadline_during_permission_check(self):
        for budget in (0, -1, math.inf, math.nan):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                InferenceControl(budget)
        clock = FakeClock()

        def slow_permission():
            clock.now = 1.0
            return True

        control = InferenceControl(1.0, clock=clock, should_continue=slow_permission)
        with self.assertRaises(InferenceDeadlineExceeded):
            control.check()

    def test_socket_is_closed_when_watcher_cannot_start(self):
        transport = Mock()
        with patch("packages.harness.local_llm.socket.socket", return_value=transport), \
             patch("packages.harness.local_llm.Thread.start", side_effect=RuntimeError("Thread indisponible")):
            with self.assertRaises(RuntimeError):
                LocalLLMClient("http://127.0.0.1:8081", "gpt-oss").complete_controlled(
                    [], [], InferenceControl(1.0)
                )
        transport.close.assert_called()
        transport.connect.assert_not_called()


@contextmanager
def fake_server(mode="normal", document=None):
    started = Event()
    disconnected = Event()
    stop = Event()
    requests = []
    body = json.dumps(document if document is not None else {
        "choices": [{"message": {"content": "ok"}}]
    }).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append((self.path, json.loads(self.rfile.read(int(
                self.headers.get("Content-Length", "0")
            )))))
            started.set()
            if mode == "headers_wait":
                self.connection.settimeout(2.0)
                try:
                    if self.connection.recv(1) == b"":
                        disconnected.set()
                except OSError:
                    pass
                return
            if mode == "redirect":
                self.send_response(302)
                self.send_header("Location", "http://example.invalid/never-follow")
                self.end_headers()
                return
            if mode == "malformed_http":
                self.connection.sendall(b"NOT-HTTP\r\n\r\n")
                return
            self.send_response(200)
            if mode != "oversize_unknown":
                self.send_header(
                    "Content-Length", str(
                        256_001 if mode == "oversize_declared" else
                        len(body) + 5 if mode == "truncated_body" else len(body)
                    )
                )
            self.end_headers()
            try:
                if mode == "slow_body":
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if stop.wait(0.01):
                            break
                elif mode == "oversize_unknown":
                    self.wfile.write(b"x" * 256_001)
                    self.wfile.flush()
                elif mode != "oversize_declared":
                    self.wfile.write(body)
                    self.wfile.flush()
            except OSError:
                disconnected.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", started, disconnected, requests
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=0.5)


class ControlledTransportTests(unittest.TestCase):
    def test_payload_and_alias_are_unchanged_and_proxy_is_ignored(self):
        messages = [{"role": "user", "content": "test"}]
        tools = [{"type": "function"}]
        with fake_server() as (url, _started, _disconnected, requests):
            with patch.dict("os.environ", {"http_proxy": "http://example.invalid:9", "no_proxy": ""}):
                result = LocalLLMClient(url, "qwen3.6-fp4").complete_controlled(
                    messages, tools, InferenceControl(1.0)
                )
            self.assertEqual(result, {"content": "ok"})
            path, payload = requests[0]
            self.assertEqual(path, "/v1/chat/completions")
            self.assertEqual(payload, {
                "model": "qwen3.6-fp4", "messages": messages, "tools": tools,
                "tool_choice": "auto", "max_tokens": 2048, "stream": False,
            })

    def test_deadline_closes_socket_while_waiting_for_headers(self):
        with fake_server("headers_wait") as (url, _started, disconnected, _requests):
            before = monotonic()
            with self.assertRaises(InferenceDeadlineExceeded):
                LocalLLMClient(url, "gpt-oss").complete_controlled([], [], InferenceControl(0.12))
            self.assertLess(monotonic() - before, 0.5)
            self.assertTrue(disconnected.wait(0.5), "Le serveur doit voir le socket fermé")

    def test_cancel_closes_socket_while_waiting_for_headers(self):
        with fake_server("headers_wait") as (url, started, disconnected, _requests):
            control = InferenceControl(2.0)
            timer = Timer(0.08, control.cancel)
            before = monotonic()
            timer.start()
            try:
                with self.assertRaises(InferenceCancelled):
                    LocalLLMClient(url, "gpt-oss").complete_controlled([], [], control)
            finally:
                timer.cancel()
                timer.join(timeout=0.2)
            self.assertTrue(started.is_set())
            self.assertLess(monotonic() - before, 0.5)
            self.assertTrue(disconnected.wait(0.5))

    def test_slow_trickle_cannot_reset_total_budget(self):
        with fake_server("slow_body") as (url, _started, _disconnected, _requests):
            before = monotonic()
            with self.assertRaises(InferenceDeadlineExceeded):
                LocalLLMClient(url, "gpt-oss", timeout_seconds=1.0).complete_controlled(
                    [], [], InferenceControl(0.12)
                )
            self.assertLess(monotonic() - before, 0.5)

    def test_cancellation_also_interrupts_a_partial_body(self):
        with fake_server("slow_body") as (url, _started, _disconnected, _requests):
            control = InferenceControl(2.0)
            timer = Timer(0.08, control.cancel)
            timer.start()
            try:
                with self.assertRaises(InferenceCancelled):
                    LocalLLMClient(url, "gpt-oss").complete_controlled([], [], control)
            finally:
                timer.cancel()
                timer.join(timeout=0.2)

    def test_revocation_during_network_wait_interrupts_it(self):
        permission = Event()
        permission.set()
        with fake_server("headers_wait") as (url, _started, disconnected, _requests):
            control = InferenceControl(2.0, should_continue=permission.is_set)
            timer = Timer(0.08, permission.clear)
            timer.start()
            try:
                with self.assertRaises(InferenceCancelled):
                    LocalLLMClient(url, "gpt-oss").complete_controlled([], [], control)
            finally:
                timer.cancel()
                timer.join(timeout=0.2)
            self.assertTrue(disconnected.wait(0.5))

    def test_redirect_and_oversized_bodies_are_refused(self):
        for mode in ("redirect", "oversize_declared", "oversize_unknown"):
            with self.subTest(mode=mode), fake_server(mode) as (url, _started, _disconnected, requests):
                with self.assertRaises(ValueError):
                    LocalLLMClient(url, "gpt-oss").complete_controlled([], [], InferenceControl(1.0))
                self.assertEqual(len(requests), 1)

    def test_malformed_envelopes_raise_value_error_not_attribute_error(self):
        for document in ([], {}, {"choices": []}, {"choices": [None]},
                         {"choices": [{"message": []}]}):
            with self.subTest(document=document), fake_server(document=document) as (url, *_rest):
                with self.assertRaises(ValueError):
                    LocalLLMClient(url, "gpt-oss").complete_controlled([], [], InferenceControl(1.0))

    def test_malformed_http_raises_fallback_compatible_os_error(self):
        with fake_server("malformed_http") as (url, *_rest):
            with self.assertRaises(OSError):
                LocalLLMClient(url, "gpt-oss").complete_controlled([], [], InferenceControl(1.0))

    def test_truncated_content_length_is_refused_even_if_json_is_valid(self):
        with fake_server("truncated_body") as (url, *_rest):
            with self.assertRaisesRegex(ValueError, "tronquée"):
                LocalLLMClient(url, "gpt-oss").complete_controlled([], [], InferenceControl(1.0))

    def test_watchers_do_not_accumulate_after_success_or_deadline(self):
        baseline = {thread.ident for thread in running_threads() if thread.name == "llm-budget-watch"}
        for mode in ("normal", "headers_wait", "normal", "headers_wait"):
            with fake_server(mode) as (url, *_rest):
                control = InferenceControl(0.08 if mode == "headers_wait" else 1.0)
                client = LocalLLMClient(url, "gpt-oss")
                if mode == "normal":
                    client.complete_controlled([], [], control)
                else:
                    with self.assertRaises(InferenceDeadlineExceeded):
                        client.complete_controlled([], [], control)
        self.assertEqual(
            {thread.ident for thread in running_threads() if thread.name == "llm-budget-watch"}, baseline
        )


if __name__ == "__main__":
    unittest.main()
