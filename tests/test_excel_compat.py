"""Regression tests: Excel-friendly copy without mutating analytical data."""
import unittest
from decimal import Decimal
import pandas as pd
from excel_compat import excel_copy_frame


class ExcelCopyTests(unittest.TestCase):
    def test_hours_copy_and_original_unchanged(self):
        frame = pd.DataFrame({
            "project_code": ["00123", "ABC"],
            "hours_granted": [Decimal("1234.56"), Decimal("-25.5")],
            "hours_incurred": [0.0, None],
            "consumption_pct": [99.95, None],
            "project_count": [2, 3],
        })
        converted = excel_copy_frame(frame)
        self.assertEqual(converted["hours_granted"].tolist(), ["1234,56", "-25,50"])
        self.assertEqual(converted["hours_incurred"].tolist(), ["0,00", ""])
        self.assertEqual(converted["consumption_pct"].tolist(), ["100,0", ""])
        self.assertEqual(converted["project_code"].tolist(), ["00123", "ABC"])
        self.assertEqual(converted["project_count"].tolist(), [2, 3])
        self.assertEqual(frame.loc[0, "hours_granted"], Decimal("1234.56"))
        self.assertEqual(frame.loc[0, "consumption_pct"], 99.95)

    def test_future_decimal_column(self):
        frame = pd.DataFrame({"budget_estimate": [12.125, None], "record_id": ["0001", "0002"]})
        converted = excel_copy_frame(frame, precision={"budget_estimate": 3})
        self.assertEqual(converted["budget_estimate"].tolist(), ["12,125", ""])
        self.assertEqual(converted["record_id"].tolist(), ["0001", "0002"])

    def test_sign_and_zero(self):
        frame = pd.DataFrame({"deviation_hours": [-0.25, 0.0, 1000000.25]})
        self.assertEqual(
            excel_copy_frame(frame)["deviation_hours"].tolist(),
            ["-0,25", "0,00", "1000000,25"],
        )


if __name__ == "__main__":
    unittest.main()
