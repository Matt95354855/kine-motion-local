"""Métadonnées de configuration uniquement : aucun runtime/model n'est contacté."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from packages.harness.local_llm import LocalLLMClient
from services.api.provenance import IMPLEMENTATION_FILES, analysis_provenance, llm_binding_provenance
from services.api.server import ModelBinding, configured_models


class RuntimeProvenanceTests(unittest.TestCase):
    def test_project_models_describe_configuration_without_calls_or_quantization_claim(self):
        gpt = LocalLLMClient("http://127.0.0.1:8001", "gpt-oss-20b", 17)
        qwen = LocalLLMClient("http://[::1]:8002", "Qwen/Qwen3.6-27B:FP4", 19)
        bindings = configured_models(gpt, qwen, True)
        original = (gpt.url, gpt.model, gpt.timeout_seconds, qwen.url, qwen.model, qwen.timeout_seconds)
        with patch.object(LocalLLMClient, "check_model") as check, \
                patch.object(LocalLLMClient, "complete") as complete, \
                patch.object(LocalLLMClient, "complete_controlled") as controlled:
            descriptors = llm_binding_provenance(bindings, "FP4")
        check.assert_not_called()
        complete.assert_not_called()
        controlled.assert_not_called()
        self.assertEqual(original, (gpt.url, gpt.model, gpt.timeout_seconds, qwen.url, qwen.model, qwen.timeout_seconds))
        self.assertEqual(descriptors[0]["endpoint"], "http://127.0.0.1:8001/v1")
        self.assertEqual(descriptors[1]["endpoint"], "http://[::1]:8002/v1")
        self.assertEqual(descriptors[0]["model_alias"], "gpt-oss-20b")
        self.assertEqual(descriptors[1]["model_alias"], "Qwen/Qwen3.6-27B:FP4")
        self.assertFalse(descriptors[0]["vision_enabled"])
        self.assertTrue(descriptors[1]["vision_enabled"])
        for descriptor in descriptors:
            self.assertEqual(descriptor["api_style"], "openai_compatible_chat_completions")
            self.assertEqual(descriptor["declared_quantization_choice"], "FP4")
            for field in ("model_revision", "runtime_version", "configured_quantization", "quantization_verified"):
                self.assertIsNone(descriptor[field])
            self.assertNotIn("used", descriptor)
            self.assertNotIn("invocations", descriptor)

    def test_custom_local_model_does_not_inherit_project_fp4_declaration(self):
        client = LocalLLMClient("http://127.0.0.1", "custom-model.gguf")
        descriptors = llm_binding_provenance({"custom": ModelBinding("Modèle local personnalisé", client, True, True)}, "FP4")
        self.assertEqual(len(descriptors), 1)
        descriptor = descriptors[0]
        self.assertEqual(descriptor["id"], "custom")
        self.assertEqual(descriptor["endpoint"], "http://127.0.0.1/v1")
        self.assertEqual(descriptor["model_alias"], "custom-model.gguf")
        self.assertIsNone(descriptor["declared_quantization_choice"])
        self.assertIsNone(descriptor["configured_quantization"])

    def test_unconfigured_models_remain_unconfigured_even_with_vision_flag(self):
        descriptors = llm_binding_provenance(configured_models(qwen_vision=True), "FP4")
        self.assertFalse(descriptors[0]["configured"])
        self.assertFalse(descriptors[1]["configured"])
        self.assertTrue(descriptors[1]["vision_supported"])
        for descriptor in descriptors:
            self.assertFalse(descriptor["vision_enabled"])
            self.assertIsNone(descriptor["model_alias"])
            self.assertIsNone(descriptor["endpoint"])
            self.assertIsNone(descriptor["api_style"])

    def test_unknown_client_has_unknown_alias_runtime_and_api_style(self):
        client = SimpleNamespace(base_url="http://127.0.0.1:8010", runtime_version="not-verified", model_revision="not-verified")
        descriptor = llm_binding_provenance({"custom": ModelBinding("Client local", client)})[0]
        self.assertTrue(descriptor["configured"])
        self.assertIsNone(descriptor["model_alias"])
        self.assertIsNone(descriptor["api_style"])
        self.assertIsNone(descriptor["runtime_version"])
        self.assertIsNone(descriptor["model_revision"])
        self.assertEqual(descriptor["endpoint"], "http://127.0.0.1:8010/v1")
        self.assertEqual(llm_binding_provenance(None), [])

    def test_unreadable_metadata_is_unknown_without_exposing_exception_details(self):
        class Unreadable:
            @property
            def model(self):
                raise ValueError("private-secret-model-path")

            @property
            def url(self):
                raise RuntimeError("private-secret-host")

        descriptor = llm_binding_provenance({"custom": ModelBinding("Client local", Unreadable())})[0]
        self.assertTrue(descriptor["configured"])
        self.assertIsNone(descriptor["model_alias"])
        self.assertIsNone(descriptor["endpoint"])
        self.assertNotIn("private-secret", json.dumps(descriptor))

    def test_credentials_queries_paths_and_nonloopback_endpoints_are_not_exported(self):
        unsafe = (
            "http://private.example:8000/v1/chat/completions",
            "http://192.168.1.10:8000/v1/chat/completions",
            "http://localhost:8000/v1/chat/completions",
            "http://user:private-secret@127.0.0.1:8000/v1/chat/completions",
            "http://127.0.0.1:8000/v1/chat/completions?api_key=private-secret",
            "http://127.0.0.1:8000/v1/chat/completions#private-secret",
            "http://127.0.0.1:8000/private-secret/file",
            "https://127.0.0.1:8000/v1/chat/completions",
            "http://127.0.0.1:invalid/v1/chat/completions",
            "http://127.0.0.1:0/v1/chat/completions",
            "http://127.0.0.1:8000\n/v1/chat/completions",
        )
        for endpoint in unsafe:
            with self.subTest(endpoint=endpoint):
                client = SimpleNamespace(url=endpoint, model="declared-model")
                descriptor = llm_binding_provenance({"custom": ModelBinding("Client local", client)})[0]
                self.assertIsNone(descriptor["endpoint"])
                serialized = json.dumps(descriptor)
                self.assertNotIn("private-secret", serialized)
                self.assertNotIn("private.example", serialized)
                self.assertNotIn("192.168", serialized)

    def test_alias_is_preserved_exactly_or_unknown_never_silently_renamed(self):
        safe = "Qwen/Qwen3.6-27B:FP4"
        for alias in (
            "/Users/private-secret/model.gguf", "~/private-secret/model.gguf",
            "C:\\Users\\private-secret\\model.gguf", "C:/private-secret/model.gguf",
            "../private-secret/model.gguf", "model\nprivate-secret", "model\u200bprivate-secret",
            "http://user:private-secret@127.0.0.1/model", "user:private-secret@127.0.0.1",
            "model?api_key=private-secret", "api_key=private-secret", "Bearer private-secret",
            "x" * 257, None, 123,
        ):
            with self.subTest(alias=alias):
                descriptor = llm_binding_provenance({"custom": ModelBinding("Client local", SimpleNamespace(model=alias))})[0]
                self.assertIsNone(descriptor["model_alias"])
                self.assertNotIn("private-secret", json.dumps(descriptor))
        descriptor = llm_binding_provenance({"custom": ModelBinding("Client local", SimpleNamespace(model=safe))})[0]
        self.assertEqual(descriptor["model_alias"], safe)

    def test_falsy_configured_client_is_not_confused_with_absence(self):
        class Falsy(SimpleNamespace):
            def __bool__(self):
                return False

        client = Falsy(model="declared-model", url="http://127.0.0.1:8000")
        descriptor = llm_binding_provenance({"qwen36": ModelBinding("Qwen 3.6", client, True, True)}, "FP4")[0]
        self.assertTrue(descriptor["configured"])
        self.assertTrue(descriptor["vision_enabled"])
        self.assertEqual(descriptor["model_alias"], "declared-model")

    def test_snapshot_separates_configured_metadata_from_actual_usage(self):
        client = LocalLLMClient("http://127.0.0.1:8000", "gpt-oss-20b")
        with patch("services.api.provenance._git", return_value=None), \
                patch("services.api.provenance._implementation_digest", return_value="a" * 64), \
                patch.object(client, "complete") as complete:
            snapshot = analysis_provenance(Path("/private/source"), "synthetic_demo",
                                           llm_bindings=configured_models(client), declared_quantization="FP4")
        complete.assert_not_called()
        runtime = snapshot["llm_runtime"]
        self.assertEqual(runtime["snapshot"], "server_startup_configuration")
        self.assertTrue(runtime["models"][0]["configured"])
        self.assertNotIn("llm_usage", snapshot)
        self.assertNotIn("/private/source", json.dumps(snapshot))
        self.assertIsNone(snapshot["pose_model"]["hash_verified"])

    def test_hash_scope_covers_harness_and_transport_changes(self):
        expected = {
            "packages/harness/control.py", "packages/harness/local_llm.py",
            "packages/harness/runner.py", "packages/harness/final_note.py",
            "packages/harness/live.py", "packages/harness/window.py",
            "services/api/inference.py", "services/api/live.py",
            "services/api/capture_integrity.py",
        }
        self.assertTrue(expected.issubset(set(IMPLEMENTATION_FILES)))
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in IMPLEMENTATION_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic source")
            with patch("services.api.provenance._git", return_value=None):
                original = analysis_provenance(root, "synthetic_demo")
                (root / "packages/harness/control.py").write_bytes(b"changed synthetic source")
                changed = analysis_provenance(root, "synthetic_demo")
        self.assertEqual(original["implementation_hash_scope"], "pose_geometry_capture_contracts_report_harness_transport_lifecycle")
        self.assertNotEqual(original["implementation_sha256"], changed["implementation_sha256"])


if __name__ == "__main__":
    unittest.main()
