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
        self.assertIn("NULL::NUMERIC AS hours_granted", view)
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

    def test_manual_assignments_survive_reimport(self):
        loader = source("scripts/closed_of_pipeline.py")
        self.assertIn("JOIN bonus_ct_registry", loader)
        self.assertIn("LEFT JOIN closed_of_manual_assignments a", loader)
        self.assertIn("COALESCE(a.project_code", loader)
        self.assertIn("COALESCE(a.work_center", loader)


if __name__ == "__main__":
    unittest.main()
