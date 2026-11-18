"""POE V5 unit tests; all data writes to Neon are separately validated on test branch."""
import unittest
import ast
import inspect
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pandas as pd

from poe_board import (
    LIME, MONTHS, month_shift, parse_hours, unpack_year, month_frame, month_changes,
    update_local, annual_frame, style_annual, save_month, sync_directors, load_year,
    restore_pending_cells, queue_action, visibility_changes, render,
)


class POEV5Tests(unittest.TestCase):
    def data(self):
        return {
            "directors": {
                "110040": "PROGRAMA VCR8X8 DRAGON SERIE",
                "310008": "MODERNIZACIÓN PIZARRO",
            },
            "hours": {
                ("110040", date(2026, 11, 1)): (Decimal("0"), Decimal("200")),
                ("310008", date(2026, 11, 1)): (None, Decimal("100")),
            },
        }

    def test_read_year_widget_defaults_to_selected_year(self):
        # Prevent Streamlit from implicitly defaulting to min_value=2000.
        tree = ast.parse(inspect.getsource(render))
        selectors = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "number_input"
            and node.args and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "Año"
        ]
        self.assertEqual(len(selectors), 1)
        values = {item.arg: item.value for item in selectors[0].keywords}
        self.assertIsInstance(values.get("value"), ast.Name)
        self.assertEqual(values["value"].id, "year")
        self.assertNotEqual(values["value"].id, "min_value")

    def test_annual_view_contains_all_twelve_natural_months(self):
        frame, _ = annual_frame(self.data(), date.today().year)
        self.assertEqual(frame.columns.tolist(), ["Director", *MONTHS])
        self.assertEqual(len(MONTHS), 12)

    def test_calendar_across_year_and_six_years(self):
        self.assertEqual(month_shift(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(month_shift(date(2027, 1, 1), -1), date(2026, 12, 1))
        self.assertEqual(month_shift(date(2026, 11, 1), 72), date(2032, 11, 1))
        self.assertEqual(len(MONTHS), 12)

    def test_excel_paste_two_columns_all_directors(self):
        data = self.data()
        frame = month_frame(data, date(2026, 11, 1))
        frame[["Real (h)", "Previsto (h)"]] = [[125, 140], [205, 210]]
        changes = month_changes(data, date(2026, 11, 1), frame)
        self.assertEqual(len(changes), 2)
        self.assertEqual(changes[0][2], (Decimal("125"), Decimal("140")))
        self.assertEqual(changes[1][2], (Decimal("205"), Decimal("210")))
        update_local(data, date(2026, 11, 1), changes)
        self.assertEqual(data["hours"][("110040", date(2026, 11, 1))][0],
                         Decimal("125"))

    def test_real_zero_precedes_forecast_and_lime_only_for_real(self):
        frame, colors = annual_frame(self.data(), 2026)
        self.assertEqual(frame.loc[0, "NOV"], 0)
        self.assertEqual(frame.loc[1, "NOV"], 100)
        self.assertIn(LIME, colors.loc[0, "NOV"])
        self.assertEqual(colors.loc[1, "NOV"], "")
        self.assertTrue(pd.isna(frame.loc[0, "ENE"]))
        self.assertEqual(len(frame.columns), 13)
        self.assertEqual(len(style_annual(self.data(), 2026).to_html()) > 0, True)

    def test_no_data_not_converted_to_zero(self):
        data = self.data()
        frame = month_frame(data, date(2026, 12, 1))
        self.assertTrue(pd.isna(frame.loc[0, "Real (h)"]))
        self.assertTrue(pd.isna(frame.loc[0, "Previsto (h)"]))
        self.assertEqual(month_changes(data, date(2026, 12, 1), frame), [])

    def test_clear_one_field_without_changing_other(self):
        data = self.data()
        frame = month_frame(data, date(2026, 11, 1))
        frame.loc[0, "Real (h)"] = float("nan")
        changes = month_changes(data, date(2026, 11, 1), frame)
        self.assertEqual(changes, [
            ("110040", (Decimal("0"), Decimal("200")), (None, Decimal("200")))
        ])

    def test_decimal_rejection(self):
        self.assertEqual(parse_hours("120,25"), Decimal("120.25"))
        self.assertIsNone(parse_hours(""))
        self.assertEqual(parse_hours(0), Decimal(0))
        for bad in ("-1", "nan", "Infinity", "1,234", "bad"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                parse_hours(bad)

    def test_director_catalog_stable_after_source_absent(self):
        rows = [
            {"code": "110040", "name": "PROGRAMA VCR8X8 DRAGON SERIE",
             "period": None, "real_hours": None, "planned_hours": None},
            {"code": "310008", "name": "MODERNIZACIÓN PIZARRO",
             "period": None, "real_hours": None, "planned_hours": None},
        ]
        data = unpack_year(rows)
        self.assertEqual(len(data["directors"]), 2)
        self.assertIn("310008", data["directors"])

    def test_no_op_save_skips_database(self):
        with patch("poe_board.connect") as connection:
            self.assertEqual(save_month("unused", date(2026, 11, 1), []), 0)
            connection.assert_not_called()

    def test_write_queries_only_poe_and_constant_per_month(self):
        class DB:
            def __init__(self):
                self.queries = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def transaction(self):
                return self
            def execute(self, sql, args=()):
                self.queries.append((sql, args))
                return self
            def fetchall(self):
                return []
        db = DB()
        changes = [
            ("110040", (None, None), (Decimal("10"), Decimal("30"))),
            ("310008", (None, None), (Decimal("20"), Decimal("40"))),
        ]
        with patch("poe_board.connect", return_value=db):
            self.assertEqual(save_month("unused", date(2026, 11, 1), changes), 2)
        self.assertEqual(len(db.queries), 3)  # advisory lock + read + batch upsert
        self.assertIn("pg_advisory_xact_lock", db.queries[0][0])
        self.assertTrue(all("poe_monthly_hours" in q for q, _ in db.queries[1:]))
        self.assertFalse(any(
            "UPDATE projects" in q or "eac_" in q or "fact_hours" in q
            for q, _ in db.queries
        ))

    def test_concurrent_edit_refused_before_write(self):
        class DB:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def transaction(self):
                return self
            def execute(self, sql, args=()):
                self.last = sql
                return self
            def fetchall(self):
                return [{"code": "110040", "real_hours": Decimal("999"),
                         "planned_hours": None}]
        with patch("poe_board.connect", return_value=DB()):
            with self.assertRaisesRegex(ValueError, "Conflicto"):
                save_month("unused", date(2026, 11, 1), [
                    ("110040", (None, None), (Decimal("100"), None))
                ])

    def test_replayed_save_is_idempotent_without_rewriting_neon(self):
        class DB:
            def __init__(self):
                self.queries = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def transaction(self):
                return self
            def execute(self, sql, args=()):
                self.queries.append(sql)
                return self
            def fetchall(self):
                return [{"code": "110040", "real_hours": None,
                         "planned_hours": Decimal("5775")}]
        db = DB()
        with patch("poe_board.connect", return_value=db):
            self.assertEqual(save_month("unused", date(2029, 1, 1), [
                ("110040", (None, None), (None, Decimal("5775")))
            ]), 0)
        self.assertEqual(len(db.queries), 2)  # lock + read; no duplicate write

    def test_conflict_cannot_overwrite_newer_hours(self):
        class DB:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def transaction(self):
                return self
            def execute(self, sql, args=()):
                self.sql = sql
                return self
            def fetchall(self):
                return [{"code": "180011", "real_hours": None,
                         "planned_hours": Decimal("5775")}]
        with patch("poe_board.connect", return_value=DB()):
            with self.assertRaisesRegex(ValueError, "Conflicto"):
                save_month("unused", date(2029, 1, 1), [
                    ("180011", (None, None), (None, Decimal("6000")))
                ])

    def test_conflict_rebase_preserves_only_user_modified_cells(self):
        period = date(2029, 1, 1)
        fresh = {"directors": {"180011": "SUSTAINMENT LETONIA"},
                 "hours": {("180011", period): (Decimal("42"), Decimal("5775"))}}
        preserved = {("180011", "Previsto (h)"): Decimal("6000")}
        frame = restore_pending_cells(fresh, period, preserved)
        self.assertEqual(frame.loc[0, "Real (h)"], 42)
        self.assertEqual(frame.loc[0, "Previsto (h)"], 6000)
        self.assertEqual(month_changes(fresh, period, frame), [
            ("180011", (Decimal("42"), Decimal("5775")),
             (Decimal("42"), Decimal("6000")))
        ])

    def test_action_queue_rejects_second_navigation(self):
        state = {}
        with patch("poe_board.st.session_state", state):
            queue_action("next")
            queue_action("prev")
        self.assertEqual(state["poe_v5_action"], "next")

    def test_visibility_checkbox_affects_only_read_mode(self):
        data = self.data()
        data["visible"] = {"110040": True, "310008": False}
        editor = month_frame(data, date(2026, 11, 1))
        self.assertEqual(editor["Visible"].tolist(), [True, False])
        read, _ = annual_frame(data, 2026)
        self.assertEqual(read["Director"].tolist(), ["PROGRAMA VCR8X8 DRAGON SERIE"])
        self.assertEqual(len(data["hours"]), 2)  # Hidden row retains all hours.

    def test_visibility_multi_selection_and_no_hour_changes(self):
        data = self.data()
        editor = month_frame(data, date(2026, 11, 1))
        editor.loc[:, "Visible"] = [False, False]
        changed = visibility_changes(data, editor)
        self.assertEqual(changed, [("110040", True, False), ("310008", True, False)])
        self.assertEqual(month_changes(data, date(2026, 11, 1), editor), [])
        update_local(data, date(2026, 11, 1), [], changed)
        self.assertEqual(len(annual_frame(data, 2026)[0]), 0)
        self.assertEqual(len(month_frame(data, date(2026, 11, 1))), 2)

    def test_integer_display_does_not_mutate_decimal_storage(self):
        data = self.data()
        formatted = style_annual(data, 2026).to_html()
        self.assertIn(">0</td>", formatted)  # Real has precedence over planned
        self.assertNotIn("200.00", formatted)
        self.assertEqual(data["hours"][("110040", date(2026, 11, 1))][1], Decimal("200"))

    def test_visibility_only_atomic_write_and_query_scope(self):
        class DB:
            def __init__(self):
                self.queries = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def transaction(self):
                return self
            def execute(self, sql, args=()):
                self.queries.append(sql)
                return self
            def fetchall(self):
                if "SELECT code,visible" in self.queries[-1]:
                    return [{"code": "110040", "visible": True}]
                return []
        db = DB()
        with patch("poe_board.connect", return_value=db):
            changed = save_month("unused", date(2026, 11, 1), [],
                                 [("110040", True, False)])
        self.assertEqual(changed, 1)
        self.assertEqual(len(db.queries), 4)  # advisory, hours read, visibility read, visibility write
        self.assertTrue(all("poe_" in q for q in db.queries[1:]))
        self.assertTrue(any("UPDATE poe_directors" in q for q in db.queries))
        self.assertFalse(any("UPDATE projects" in q or "UPDATE eac_" in q
                             for q in db.queries))

    def test_order_guard_prevents_cross_director_paste(self):
        data = self.data()
        frame = month_frame(data, date(2026, 11, 1))
        frame.loc[0, "Director"] = "MODERNIZACIÓN PIZARRO"
        with self.assertRaises(ValueError):
            month_changes(data, date(2026, 11, 1), frame)


if __name__ == "__main__":
    unittest.main()
