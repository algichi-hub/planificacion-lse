"""Regression tests for the EAC read-only comparison and chart presentation."""
import unittest
from unittest.mock import patch

import pandas as pd

from eac_board import chart, project_comparison, director_comparison
from excel_compat import excel_copy_frame, excel_csv_bytes


class EACComparisonTests(unittest.TestCase):
    def sample(self):
        return pd.DataFrame({
            "project_code": ["A", "B", "C"],
            "management_group": ["110040", "110040", "110050"],
            "etc_hours": [100.0, 100.0, float("nan")],
            "hours_granted": [90.0, 130.0, 20.0],
            "hours_incurred": [110.0, 80.0, 15.0],
        })

    def test_difference_and_unregistered_eac(self):
        src = self.sample()
        result = project_comparison(src)
        self.assertEqual(result["etc_remaining"].iloc[0], -10.0)
        self.assertEqual(result["etc_remaining"].iloc[1], 20.0)
        self.assertTrue(pd.isna(result["etc_remaining"].iloc[2]))
        self.assertNotIn("etc_remaining", src.columns)

    def test_csv_and_clipboard_follow_requested_order(self):
        result = project_comparison(self.sample())
        columns = ["project_code", "hours_incurred", "etc_hours", "etc_remaining"]
        export = excel_csv_bytes(result[columns])
        self.assertTrue(export.startswith(b"\xef\xbb\xbf"))
        lines = export.decode("utf-8-sig").splitlines()
        self.assertEqual(lines[0], ";".join(columns))
        self.assertEqual(lines[1], "A;110,00;100,00;-10,00")
        self.assertEqual(lines[2], "B;80,00;100,00;20,00")
        self.assertEqual(lines[3], "C;15,00;;")
        self.assertEqual(excel_copy_frame(result[columns])["etc_remaining"].iloc[0], "-10,00")

    def test_director_aggregate_and_incomplete_eac(self):
        projects = self.sample()
        summary = projects.groupby("management_group", as_index=False).agg(
            etc_hours=("etc_hours", lambda values: values.sum(min_count=1)),
            hours_granted=("hours_granted", "sum"),
            hours_incurred=("hours_incurred", "sum"),
        )
        original = summary.copy(deep=True)
        result = director_comparison(projects, summary)
        first = result.set_index("management_group").loc["110040"]
        second = result.set_index("management_group").loc["110050"]
        self.assertEqual(first["hours_incurred"], 190.0)
        self.assertEqual(first["hours_granted"], 220.0)
        self.assertEqual(first["etc_hours"], 200.0)
        self.assertEqual(first["etc_remaining"], 10.0)
        self.assertEqual(second["hours_incurred"], 15.0)
        self.assertTrue(pd.isna(second["etc_hours"]))
        self.assertTrue(pd.isna(second["etc_remaining"]))
        pd.testing.assert_frame_equal(summary, original)

    def test_director_partial_eac_calculates_from_available_total(self):
        projects = self.sample()
        projects.loc[1, "etc_hours"] = float("nan")
        summary = projects.groupby("management_group", as_index=False).agg(
            etc_hours=("etc_hours", lambda values: values.sum(min_count=1)),
            hours_granted=("hours_granted", "sum"),
            hours_incurred=("hours_incurred", "sum"),
        )
        result = director_comparison(projects, summary).set_index("management_group")
        self.assertEqual(result.loc["110040", "etc_hours"], 100.0)
        self.assertEqual(result.loc["110040", "etc_remaining"], -90.0)

    def test_director_excel_csv_column_order(self):
        projects = self.sample()
        summary = projects.groupby("management_group", as_index=False).agg(
            etc_hours=("etc_hours", lambda values: values.sum(min_count=1)),
            hours_granted=("hours_granted", "sum"),
            hours_incurred=("hours_incurred", "sum"),
        )
        columns = ["management_group", "hours_incurred", "etc_hours", "etc_remaining"]
        result = director_comparison(projects, summary)
        rows = excel_csv_bytes(result[columns]).decode("utf-8-sig").splitlines()
        self.assertEqual(rows[0], ";".join(columns))
        self.assertEqual(rows[1], "110040;190,00;200,00;10,00")
        self.assertEqual(rows[2], "110050;15,00;;")

    def test_eac_csv_exports_use_visible_headers(self):
        from eac_board import comparison_table

        projects = project_comparison(self.sample())
        cases = [
            (projects, {
                "project_code": "Proyecto",
                "hours_incurred": "Total incurrido",
                "etc_hours": "EAC",
                "etc_remaining": "ETC",
            }, "Proyecto;Total incurrido;EAC;ETC"),
        ]
        totals = projects.groupby("management_group", as_index=False).agg(
            hours_incurred=("hours_incurred", "sum"),
            hours_granted=("hours_granted", "sum"),
            etc_hours=("etc_hours", lambda x: x.sum(min_count=1)),
        )
        director = director_comparison(projects, totals)
        cases.append((director, {
            "management_group": "Director",
            "hours_incurred": "Total incurrido",
            "etc_hours": "EAC",
            "etc_remaining": "ETC",
        }, "Director;Total incurrido;EAC;ETC"))
        for frame, labels, expected_header in cases:
            original = frame.copy(deep=True)
            with self.subTest(expected_header=expected_header), \
                    patch("eac_board.st.dataframe"), \
                    patch("eac_board.st.download_button") as download:
                comparison_table.__wrapped__(frame, labels, "eac.csv", "test")
                csv_data = download.call_args.kwargs["data"]
                self.assertTrue(csv_data.startswith(b"\xef\xbb\xbf"))
                rows = csv_data.decode("utf-8-sig").splitlines()
                self.assertEqual(rows[0], expected_header)
                self.assertIn(",00", rows[1])
                pd.testing.assert_frame_equal(frame, original)

    def test_charts_order_and_colors_for_both_axes(self):
        data = self.sample()
        expected = ["EAC", "Concedidas", "Incurridas"]
        colors = {"EAC": "#D5A547", "Concedidas": "#70B7EA", "Incurridas": "#1F4E8C"}
        for group in ["project_code", "management_group"]:
            if group == "management_group":
                data_to_plot = data.groupby(group, as_index=False).agg({
                    "etc_hours": lambda values: values.sum(min_count=1),
                    "hours_granted": "sum", "hours_incurred": "sum",
                })
            else:
                data_to_plot = data
            with self.subTest(group=group), patch("eac_board.st.plotly_chart") as render:
                chart(data_to_plot, group)
                figure = render.call_args.args[0]
                self.assertEqual([trace.name for trace in figure.data], expected)
                self.assertEqual(
                    {trace.name: trace.marker.color for trace in figure.data}, colors
                )
                self.assertEqual(figure.layout.barmode, "group")

    def test_eac_editor_and_publication_still_separate(self):
        # The comparison helpers must not modify input frames.
        source = self.sample()
        prior = source.copy(deep=True)
        project_comparison(source)
        pd.testing.assert_frame_equal(source, prior)


if __name__ == "__main__":
    unittest.main()
