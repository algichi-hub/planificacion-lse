"""Contracts for OF-grain reporting with closed manufacturing orders.

These offline checks prevent regressions which duplicate closed hours at bonus
grain or accidentally feed unallocated bonus hours into the risks dashboard.
SQL aggregates are also verified against Neon development separately.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class ReportingContractTests(unittest.TestCase):
    def test_of_view_has_one_closed_row_and_guards_overlap(self):
        sql = source("sql/schema.sql")
        view = sql.split("CREATE OR REPLACE VIEW v_reporting_of_hours AS", 1)[1].split("CREATE OR REPLACE VIEW v_latest_snapshot AS", 1)[0]
        self.assertIn("UNION ALL", view)
        self.assertIn("c.hours_incurred", view)
        self.assertIn("c.hours_incurred AS hours_granted", view)
        self.assertIn("0::NUMERIC AS hours_pending", view)
        self.assertNotIn("NULL::NUMERIC AS hours_granted", view)
        self.assertIn("NOT EXISTS", view)
        self.assertNotIn("JOIN bonus_ct_registry", view)

    def test_home_aggregates_of_but_risks_and_bonuses_remain_operational(self):
        app = source("app.py")
        before, after = app.split('if view == "risks":', 1)
        risk, rest = after.split("projects = query(", 1)
        home, bonus = rest.split("    bonuses = query(", 1)
        self.assertEqual(before.count("FROM v_reporting_of_hours f"), 2)
        self.assertIn("FROM fact_hours f", risk)
        self.assertEqual(home.count("FROM v_reporting_of_hours f"), 2)
        self.assertIn("FROM fact_hours f", bonus)
        self.assertIn("if bonuses.empty:", bonus)

    def test_closed_of_colors_are_local_to_home_order_chart(self):
        app = source("app.py")
        order_sql = app.split("orders = query(", 1)[1].split('if selected_project != "Todos":', 1)[0]
        order_chart = app.split('st.subheader("RESUMEN ORDEN DE FABRICACIÓN")', 1)[1].split("fig_orders.update_layout(", 1)[0]
        risk = app.split('if view == "risks":', 1)[1].split("projects = query(", 1)[0]
        self.assertIn("BOOL_OR(f.hours_source = 'CLOSED_OF') AS is_closed", order_sql)
        self.assertIn('order_chart.loc[order_chart["is_closed"], "Serie"] += " · cerrada"', order_chart)
        self.assertIn('"Concedidas": "#F2C94C"', order_chart)
        self.assertIn('"Incurridas": "#F2994A"', order_chart)
        self.assertIn('"Concedidas · cerrada": "#B8860B"', order_chart)
        self.assertIn('"Incurridas · cerrada": "#7B2943"', order_chart)
        self.assertNotIn("is_closed", risk)
        self.assertIn("FROM fact_hours f", risk)

    def test_eac_poe_incurred_use_of_grain(self):
        self.assertIn("FROM v_reporting_of_hours f", source("eac_board.py"))
        self.assertIn("FROM v_reporting_of_hours f", source("poe_board.py"))
        self.assertIn("SUM(f.hours_incurred)", source("eac_board.py"))

    def test_reporting_unknown_grants_are_not_zero(self):
        schema = source("sql/schema.sql")
        self.assertIn("COUNT(*) FILTER (WHERE f.hours_granted IS NULL)>0", schema)
        app = source("app.py")
        self.assertIn('granted is None', app)
        self.assertIn('of_granted is None', app)
        self.assertIn("sum(min_count=1)", app)

    def test_operative_to_closed_transition_reporting_contract(self):
        sql = source("sql/schema.sql")
        operational, closed = sql.split("CREATE OR REPLACE VIEW v_reporting_of_hours AS", 1)[1].split("UNION ALL", 1)
        closed = closed.split("CREATE OR REPLACE VIEW v_latest_snapshot AS", 1)[0]
        self.assertIn("SUM(f.hours_granted) AS hours_granted", operational)
        self.assertIn("SUM(f.hours_incurred) AS hours_incurred", operational)
        self.assertIn("c.hours_incurred AS hours_granted", closed)
        self.assertIn("c.hours_incurred", closed)
        self.assertIn("0::NUMERIC AS hours_pending", closed)
        self.assertIn("NOT EXISTS", closed)

    def test_import_rejects_same_snapshot_conflicts(self):
        loader = source("scripts/closed_of_pipeline.py")
        self.assertIn("JOIN incoming_closed c ON c.order_number = f.order_number", loader)
        self.assertIn("f.snapshot_date = %s", loader)
        self.assertIn("OF simultáneamente operativas y cerradas", loader)

    def test_import_rejects_unexpected_reopenings(self):
        loader = source("scripts/closed_of_pipeline.py")
        self.assertIn("old.snapshot_date < %s", loader)
        self.assertIn("OF cerrada previamente reaparece operativa", loader)

    def test_manual_assignments_survive_reimport(self):
        loader = source("scripts/closed_of_pipeline.py")
        self.assertIn("JOIN bonus_ct_registry", loader)
        self.assertIn("LEFT JOIN closed_of_manual_assignments a", loader)
        self.assertIn("COALESCE(a.project_code", loader)
        self.assertIn("COALESCE(a.work_center", loader)


if __name__ == "__main__":
    unittest.main()
