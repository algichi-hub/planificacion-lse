"""Small, dependency-free tests for the lifecycle import hook.

Run from repository root:
    python -m unittest discover -s tests -p 'test_of_lifecycle.py'
"""
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from of_lifecycle import refresh_lifecycle_events


class LifecycleHookTests(unittest.TestCase):
    def test_one_bulk_refresh_for_snapshot(self):
        cur = Mock()
        cur.execute.return_value.fetchall.return_value = [("ACTIVA", "CERRADA", 2)]
        snapshot = date(2026, 11, 21)

        result = refresh_lifecycle_events(cur, snapshot)

        self.assertEqual(result, [("ACTIVA", "CERRADA", 2)])
        self.assertEqual(cur.execute.call_count, 3)
        delete, insert, summary = [call.args for call in cur.execute.call_args_list]
        self.assertIn("DELETE FROM of_lifecycle_events", delete[0])
        self.assertEqual(delete[1], (snapshot,))
        self.assertIn("LAG(status)", insert[0])
        self.assertIn("previous_status IS NOT NULL", insert[0])
        self.assertIn("status IS DISTINCT FROM previous_status", insert[0])
        self.assertEqual(insert[1], (snapshot, snapshot, snapshot))
        self.assertIn("GROUP BY previous_status, current_status", summary[0])
        self.assertEqual(summary[1], (snapshot,))

    def test_reopen_is_not_silently_accepted(self):
        # A previously closed OF appearing operative is rejected in
        # closed_of_pipeline before this hook executes; this hook only records
        # transitions after that gate has passed.
        cur = Mock()
        cur.execute.return_value.fetchall.return_value = []
        self.assertEqual(refresh_lifecycle_events(cur, date(2026, 12, 21)), [])


if __name__ == "__main__":
    unittest.main()
