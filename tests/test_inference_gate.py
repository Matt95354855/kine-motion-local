import threading
import unittest

from packages.harness.control import InferenceControl
from services.api.inference import InferenceGate


class InferenceGateTests(unittest.TestCase):
    def test_live_and_draft_share_one_slot_without_waiting_or_queueing(self):
        gate = InferenceGate()
        first = gate.try_acquire(InferenceControl(), "s", "token", "live", 1)
        self.assertIsNotNone(first)
        self.assertIsNone(gate.try_acquire(InferenceControl(), "s", "token", "draft"))
        self.assertTrue(gate.is_busy())
        self.assertTrue(gate.release(first))
        self.assertFalse(gate.is_busy())
        self.assertIsNotNone(gate.try_acquire(InferenceControl(), "s", "token", "draft"))

    def test_cancellation_preserves_slot_until_actual_release(self):
        gate = InferenceGate()
        control = InferenceControl()
        lease = gate.try_acquire(control, "s", "token", "live", 1)
        self.assertFalse(gate.cancel_session("s", "wrong"))
        self.assertFalse(control.cancelled)
        self.assertTrue(gate.cancel_session("s", "token"))
        self.assertTrue(control.cancelled)
        self.assertIsNone(gate.try_acquire(InferenceControl(), "new", "token", "live", 1))
        gate.release(lease)
        self.assertFalse(gate.is_busy())

    def test_old_release_or_stop_cannot_affect_new_work(self):
        gate = InferenceGate()
        old = gate.try_acquire(InferenceControl(), "s", "token", "live", 1)
        gate.release(old)
        current = gate.try_acquire(InferenceControl(), "s", "token", "live", 3)
        self.assertFalse(gate.release(old))
        self.assertFalse(gate.cancel_session("s", "token", max_control_version=2))
        self.assertFalse(current.control.cancelled)
        self.assertTrue(gate.cancel_session("s", "token", max_control_version=3))
        self.assertTrue(current.control.cancelled)
        self.assertTrue(gate.is_busy())

    def test_live_only_cancellation_does_not_cancel_final_note(self):
        gate = InferenceGate()
        lease = gate.try_acquire(InferenceControl(), "s", "token", "draft")
        self.assertFalse(gate.cancel_session("s", "token", max_control_version=20))
        self.assertFalse(lease.control.cancelled)
        self.assertTrue(gate.cancel_all())
        self.assertTrue(lease.control.cancelled)

    def test_simultaneous_acquisition_reserves_exactly_one_slot(self):
        gate = InferenceGate()
        barrier = threading.Barrier(6)
        leases = []
        def acquire():
            barrier.wait(timeout=2)
            leases.append(gate.try_acquire(InferenceControl(), "s", "token", "live"))
        workers = [threading.Thread(target=acquire) for _ in range(5)]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=2)
        for worker in workers:
            worker.join(timeout=2)
        self.assertEqual(sum(lease is not None for lease in leases), 1)

    def test_invalid_kind_does_not_reserve_slot(self):
        gate = InferenceGate()
        with self.assertRaises(ValueError):
            gate.try_acquire(InferenceControl(), "s", "token", "unknown")
        self.assertFalse(gate.is_busy())

    def test_release_none_is_never_a_success_or_an_active_slot_release(self):
        gate = InferenceGate()
        self.assertFalse(gate.release(None))
        lease = gate.try_acquire(InferenceControl(), "s", "token", "draft")
        self.assertFalse(gate.release(None))
        self.assertTrue(gate.is_busy())
        self.assertTrue(gate.release(lease))
