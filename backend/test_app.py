"""Focused regression tests for the Sunrise Clinic agent/tool layer.

Run from the backend directory with: python -m unittest -v test_app.py
Requires app.py and clinic.json in the same directory.
"""
import copy
import json
import threading
import unittest
from pathlib import Path

import app

CLINIC = json.loads((Path(__file__).resolve().parent / "clinic.json").read_text(encoding="utf-8"))


class ToolLayerTests(unittest.TestCase):
    def test_malformed_tool_arguments_return_actionable_error(self):
        runtime = app.ToolRuntime(copy.deepcopy(CLINIC))
        result = runtime.call("search_slots", {"doctor_id": "dr_rao"})
        self.assertEqual(result["error"], "invalid_arguments")
        self.assertIn("date", result["detail"])

    def test_ambiguous_lookup_returns_candidates_without_resolution(self):
        runtime = app.ToolRuntime(copy.deepcopy(CLINIC))
        result = runtime.call("lookup_patient", {})
        self.assertGreater(len(result["candidates"]), 1)
        self.assertIsNone(result["resolved"])

    def test_urgent_non_happy_path_escalates(self):
        result = app.run_agent(app.RunRequest(
            conversation_id="test_urgent",
            today="2026-10-01",
            turns=["I have severe chest pain and difficulty breathing."],
        ))
        self.assertEqual(result["terminal_state"], "escalated")
        self.assertEqual(result["escalation_reason"], "clinical_urgent")
        self.assertIn("escalate_to_human", [c["name"] for c in result["tool_calls"]])

    def test_two_overlapping_bookings_cannot_reserve_same_slot(self):
        probe = app.ToolRuntime(copy.deepcopy(CLINIC))
        slots = probe.call("search_slots", {
            "doctor_id": "dr_rao", "date": "2026-10-03", "window": "morning"
        }).get("slots", [])
        self.assertTrue(slots, "Fixture should have a Dr. Rao morning slot on 2026-10-03")
        start = slots[0]["start"]
        patient_id = CLINIC["patients"][0]["id"]
        barrier = threading.Barrier(2)
        result_lock = threading.Lock()
        results = []
        runtimes = []

        def attempt():
            runtime = app.ToolRuntime(copy.deepcopy(CLINIC))
            runtimes.append(runtime)
            barrier.wait()
            result = runtime.call("book_appointment", {
                "patient_id": patient_id,
                "doctor_id": "dr_rao",
                "date": "2026-10-03",
                "start": start,
            })
            with result_lock:
                results.append(result)

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertTrue(all(not thread.is_alive() for thread in threads), "Booking test threads timed out")
            self.assertEqual(sum(bool(r.get("success")) for r in results), 1)
            self.assertEqual(sum(r.get("error") == "slot_reserved" for r in results), 1)
        finally:
            for runtime in runtimes:
                runtime.release_reservations()
            probe.release_reservations()


if __name__ == "__main__":
    unittest.main()
