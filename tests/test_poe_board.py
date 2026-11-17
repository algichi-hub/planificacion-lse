"""POE unit and regression tests; no database credentials required."""
import unittest

import pandas as pd

from poe_board import month_shift, parse_hours, grid_frame, apply_grid, validate, to_work


class PoeTests(unittest.TestCase):
    def example(self):
        return {
            "revision": 0,
            "status": "draft",
            "directors": ["110040", "110050"],
            "months": {"2026-11-01": "real", "2026-12-01": "previsto",
                       "2027-01-01": "previsto"},
            "hours": {("110040", "2026-11-01"): "120.00",
                      ("110050", "2026-11-01"): "40.00"},
        }

    def test_month_extension_through_year_and_six_years(self):
        self.assertEqual(month_shift(pd.Timestamp("2026-12-01").date(), 1).isoformat(),
                         "2027-01-01")
        self.assertEqual(month_shift(pd.Timestamp("2026-01-01").date(), -1).isoformat(),
                         "2025-12-01")
        self.assertEqual(month_shift(pd.Timestamp("2026-11-01").date(), 72).isoformat(),
                         "2032-11-01")

    def test_excel_paste_rectangular_block(self):
        work = self.example()
        periods = sorted(work["months"])
        pasted = grid_frame(work, periods)
        pasted.loc[:, periods] = [[120, 250, 350], [40, 75, 110]]
        apply_grid(work, pasted, periods)
        self.assertEqual(work["hours"][("110040", "2027-01-01")], "350.0")
        self.assertEqual(work["hours"][("110050", "2026-12-01")], "75.0")
        self.assertEqual(len(validate(work)), 6)

    def test_missing_vs_zero_and_span_changes(self):
        work = self.example()
        frame = grid_frame(work, sorted(work["months"]))
        self.assertTrue(pd.isna(frame.loc[0, "2026-12-01"]))
        frame.loc[0, "2026-12-01"] = 0
        apply_grid(work, frame, sorted(work["months"]))
        self.assertEqual(work["hours"][("110040", "2026-12-01")], "0.0")
        work["months"]["2027-02-01"] = "previsto"
        self.assertTrue(pd.isna(grid_frame(work, ["2027-02-01"]).iloc[0, 1]))

    def test_kind_switch_does_not_change_hours(self):
        work = self.example()
        old = work["hours"].copy()
        work["months"]["2026-12-01"] = "real"
        self.assertEqual(work["hours"], old)

    def test_decimal_validation(self):
        self.assertEqual(str(parse_hours("120,25")), "120.25")
        self.assertIsNone(parse_hours(""))
        for bad in ["-1", "nan", "Infinity", "1,234", "bad"]:
            with self.subTest(value=bad), self.assertRaises(ValueError):
                parse_hours(bad)

    def test_restore_from_snapshot(self):
        record = {
            "revision": 3, "status": "draft",
            "months": [{"period": "2026-11-01", "kind": "real"}],
            "directors": ["110040"],
            "hours": [{"director": "110040", "period": "2026-11-01", "hours": 120}],
        }
        work = to_work(record)
        work["hours"][("110040", "2026-11-01")] = "300"
        self.assertEqual(to_work(record)["hours"][("110040", "2026-11-01")], "120")

    def test_elimination_removes_only_local_poe_data(self):
        work = self.example()
        work["directors"].remove("110050")
        work["hours"] = {k: v for k, v in work["hours"].items() if k[0] != "110050"}
        self.assertEqual(len(validate(work)), 1)


if __name__ == "__main__":
    unittest.main()
