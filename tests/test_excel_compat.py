"""Regression tests: Excel-friendly copy without mutating analytical data."""
import unittest
from decimal import Decimal
import pandas as pd
from excel_compat import excel_copy_frame, excel_csv_bytes


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

    def test_spanish_csv_columns_decimals_and_utf8(self):
        frame = pd.DataFrame({
            "project_code": ["DRM001", "DRM002"],
            "description": ["PLANES LSA, DATOS SIGLE", "GARANTÍAS DRAGÓN"],
            "etc_hours": [Decimal("8077.00"), None],
            "hours_incurred": [Decimal("14127.76"), Decimal("228.78")],
        })
        raw = excel_csv_bytes(frame)
        self.assertTrue(raw.startswith(b"\\xef\\xbb\\xbf"))
        content = raw.decode("utf-8-sig")
        self.assertTrue(content.startswith("project_code;description;etc_hours;hours_incurred\\r\\n"))
        self.assertIn("DRM001;PLANES LSA, DATOS SIGLE;8077,00;14127,76", content)
        self.assertIn("DRM002;GARANTÍAS DRAGÓN;;228,78", content)
        import csv
        import io
        rows = list(csv.DictReader(io.StringIO(content), delimiter=";"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["description"], "PLANES LSA, DATOS SIGLE")
        self.assertEqual(rows[0]["etc_hours"], "8077,00")

    def test_sign_and_zero(self):
        frame = pd.DataFrame({"deviation_hours": [-0.25, 0.0, 1000000.25]})
        self.assertEqual(
            excel_copy_frame(frame)["deviation_hours"].tolist(),
            ["-0,25", "0,00", "1000000,25"],
        )


if __name__ == "__main__":
    unittest.main()
