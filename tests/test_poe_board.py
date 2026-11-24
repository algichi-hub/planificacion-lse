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
    annual_evolution, director_eac, render_annual_chart, available_eac_snapshots,
    director_bar_sources, director_bar_frame, render_director_bars,
    consecutive_months, eac_exhaustion, exhaustion_rows, render_exhaustion_table,
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

    def test_exhaustion_month_year_and_horizon(self):
        last = date(2026, 10, 1)
        self.assertEqual(eac_exhaustion(15000, 10000, 1000, last), "Marzo 2027")
        self.assertEqual(eac_exhaustion(15000, 10000, 5000, last), "Noviembre 2026")
        self.assertEqual(eac_exhaustion(120, 0, 1, last), "Octubre 2036")
        self.assertEqual(eac_exhaustion(121, 0, 1, last), "El periodo excede de lo previsto")
        self.assertEqual(eac_exhaustion(200, 100, 0, last), "El periodo excede de lo previsto")
        self.assertEqual(eac_exhaustion(200, 100, -1, last), "El periodo excede de lo previsto")
        self.assertEqual(eac_exhaustion(200, 200, 15, last), "EAC alcanzado o superado")

    def test_projection_requires_matching_three_calendar_months(self):
        self.assertTrue(consecutive_months([
            date(2026, 10, 1), date(2026, 11, 1), date(2026, 12, 1)]))
        self.assertFalse(consecutive_months([
            date(2026, 9, 1), date(2026, 11, 1), date(2026, 12, 1)]))
        self.assertFalse(consecutive_months([date(2026, 11, 1), date(2026, 12, 1)]))

    def test_exhaustion_two_source_rates_and_zero_is_real(self):
        data = {"directors": {"A": "DIRECTOR"},
                "hours": {("A", date(2026, 10, 1)): (Decimal(0), None),
                          ("A", date(2026, 11, 1)): (Decimal(100), None),
                          ("A", date(2026, 12, 1)): (Decimal(200), None)},
                "opening": {"A": Decimal(200)}, "opening_count": {"A": 1}}
        erp = [{"period": date(2026, 10, 1), "accumulated": Decimal(200)},
               {"period": date(2026, 11, 1), "accumulated": Decimal(260)},
               {"period": date(2026, 12, 1), "accumulated": Decimal(400)}]
        rows = exhaustion_rows(data, 2026, "A",
                               {"eac_hours": Decimal(1000)}, erp)
        self.assertEqual([r["Fuente"] for r in rows], ["Incurrido OF", "POE real"])
        self.assertEqual(rows[0]["Ritmo (h/mes)"], 100)
        self.assertEqual(rows[1]["Ritmo (h/mes)"], 100)
        self.assertEqual(rows[1]["Acumulado (h)"], 500)
        self.assertEqual(rows[0]["Agotamiento EAC"], "Junio 2027")
        self.assertEqual(rows[1]["Agotamiento EAC"], "Mayo 2027")
        self.assertIsNone(exhaustion_rows(data, 2026, "A", {"eac_hours": 1000}, erp[:2]))

    def test_exhaustion_insufficient_poe_avoids_neon(self):
        data = {"hours": {("A", date(2026, 10, 1)): (Decimal(10), None),
                          ("A", date(2026, 11, 1)): (Decimal(20), None)}}
        with patch("poe_board.erp_monthly_director") as query, \
             patch("poe_board.st.info") as info, patch("poe_board.st.markdown"):
            render_exhaustion_table("url", data, 2026, "A",
                                    {"year": 2026, "quarter": 3, "eac_hours": 100})
        query.assert_not_called()
        info.assert_called_once_with("No se dispone de suficientes datos")

    def test_exhaustion_renders_table_only_and_no_new_plot(self):
        data = {"hours": {("A", date(2026, 10, 1)): (Decimal(10), None),
                          ("A", date(2026, 11, 1)): (Decimal(20), None),
                          ("A", date(2026, 12, 1)): (Decimal(30), None)},
                "opening": {"A": None}, "opening_count": {"A": 0}}
        erp = [{"period": date(2026, m, 1), "accumulated": 100*m}
               for m in (10, 11, 12)]
        with patch("poe_board.erp_monthly_director", return_value=erp) as query, \
             patch("poe_board.st.dataframe") as table, \
             patch("poe_board.st.plotly_chart") as plot, \
             patch("poe_board.st.markdown"), patch("poe_board.st.caption"):
            render_exhaustion_table("url", data, 2026, "A",
                                    {"year": 2026, "quarter": 3, "eac_hours": 900})
        query.assert_called_once_with("url", "A", date(2026, 12, 1))
        table.assert_called_once()
        plot.assert_not_called()
        frame = table.call_args.args[0]
        self.assertEqual(list(frame.columns),
                         ["Fuente", "Ritmo (h/mes)", "Acumulado (h)", "Agotamiento EAC"])
        self.assertTrue(all(isinstance(x, str) for x in frame["Agotamiento EAC"]))

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

    def test_edit_grid_shows_immutable_director_code(self):
        frame = month_frame(self.data(), date(2026, 11, 1))
        self.assertEqual(frame["Código"].tolist(), ["110040", "310008"])
        self.assertEqual(frame.columns.tolist(),
                         ["Visible", "Código", "Director", "Real (h)", "Previsto (h)"])
        edited = frame.copy()
        edited.loc[0, "Real (h)"] = 12.0
        self.assertEqual(month_changes(self.data(), date(2026, 11, 1), edited)[0][0],
                         "110040")
        edited.loc[0, "Código"] = "IMPOSTOR"
        with self.assertRaisesRegex(ValueError, "orden de directores"):
            month_changes(self.data(), date(2026, 11, 1), edited)
        code = inspect.getsource(render)
        self.assertIn('disabled=["Código", "Director"]', code)
        self.assertIn('st.column_config.TextColumn("Código", width="small")', code)

    def test_annual_view_contains_all_twelve_natural_months(self):
        frame, _ = annual_frame(self.data(), date.today().year)
        self.assertEqual(frame.columns.tolist(), ["Código", "Director", *MONTHS])
        self.assertEqual(frame["Código"].tolist(), ["110040", "310008"])
        self.assertEqual(len(MONTHS), 12)

    def test_screen_sections_in_expected_order(self):
        source = inspect.getsource(render)
        eac = source.index('st.subheader("EAC representado")')
        selector = source.index('st.selectbox(\n                "Snapshot EAC"')
        bars = source.index('render_director_bars(data, sources)')
        poe = source.index('st.subheader("POE mensual")')
        table = source.index("st.dataframe(style_annual(data, year)")
        refresh = source.index('refresh.button("Actualizar POE"')
        sync = source.index('sync.button("Sincronizar directores"')
        evolution = source.index('st.subheader("Evolución anual por director")')
        self.assertEqual(sorted([eac, selector, bars, poe, table, refresh, sync, evolution]),
                         [eac, selector, bars, poe, table, refresh, sync, evolution])
        self.assertNotIn("Horas reales y previstas manuales; lectura de directores", source)
        self.assertIn('label_visibility="collapsed"', source)
        self.assertEqual(source.count('refresh.button("Actualizar POE"'), 1)
        self.assertEqual(source.count('sync.button("Sincronizar directores"'), 1)

    def test_single_year_selector_and_edit_button_grouped(self):
        source = inspect.getsource(render)
        self.assertEqual(source.count('number_input("Año"'), 1)
        table = source.index("st.dataframe(style_annual(data, year)")
        actions = source.index("refresh, sync, edit = st.columns(3)")
        edit = source.index('edit.button("Abrir modo edición"')
        trend = source.index('st.subheader("Evolución anual por director")')
        self.assertLess(table, actions)
        self.assertLess(actions, edit)
        self.assertLess(edit, trend)
        self.assertIn('key="poe_v5_open_edit"', source)
        self.assertIn('background:#003087', source)

    def test_poe_bar_temporal_caption_with_mixed_directors(self):
        data = {"directors": {"A": "ONE", "B": "TWO"},
                "visible": {"A": True, "B": True}, "hours": {}}
        sources = [
            {"code": "A", "last_real": date(2025, 12, 1),
             "first_forecast": None, "erp_date": date(2026, 10, 15)},
            {"code": "B", "last_real": date(2026, 10, 1),
             "first_forecast": date(2026, 11, 1),
             "erp_date": date(2026, 10, 15)},
        ]
        with patch("poe_board.eac_chart"), patch("poe_board.comparison_table"), \
             patch("poe_board.st.subheader"), patch("poe_board.st.caption") as caption:
            render_director_bars(data, sources)
        label = caption.call_args_list[0].args[0]
        self.assertIn("hasta DIC/2025–OCT/2026", label)
        self.assertIn("desde NOV/2026", label)
        self.assertIn("Incurrido OFs (15/10/2026)", label)

    def test_poe_director_table_reuses_chart_rows_and_eac_component(self):
        data = {"directors": {"A": "FIRST", "B": "HIDDEN", "C": "THIRD"},
                "visible": {"A": True, "B": False, "C": True},
                "hours": {}}
        rows = [
            {"code": "A", "eac_hours": Decimal(1000),
             "incurred_hours": Decimal(350), "poe_real": Decimal(270),
             "poe_future": Decimal(140), "erp_date": date(2026, 11, 24)},
            {"code": "C", "eac_hours": None, "incurred_hours": None,
             "poe_real": None, "poe_future": None,
             "erp_date": date(2026, 11, 24)},
        ]
        with patch("poe_board.eac_chart") as bars, \
             patch("poe_board.comparison_table") as summary, \
             patch("poe_board.st.subheader"), patch("poe_board.st.caption"):
            render_director_bars(data, rows)
        frame = summary.call_args.args[0]
        self.assertEqual(frame["management_group"].tolist(),
                         bars.call_args.args[0]["management_group"].tolist())
        self.assertEqual(frame["etc_remaining"].iloc[0], Decimal(650))
        self.assertEqual(frame["poe_total"].iloc[0], Decimal(410))
        self.assertTrue(pd.isna(frame["poe_total"].iloc[1]))
        self.assertEqual(summary.call_args.args[2], "poe_directores.csv")
        self.assertEqual(list(summary.call_args.args[1]),
                         ["management_group", "hours_incurred", "etc_hours",
                          "etc_remaining", "poe_real", "poe_future", "poe_total"])

    def test_lazy_evolution_selector_and_year_specific_data(self):
        source = inspect.getsource(render)
        self.assertIn('codes, index=None', source)
        self.assertIn('key="poe_v5_evolution_director"', source)
        self.assertIn('if selected_director is not None:', source)
        self.assertIn('date(int(selected_year), 1, 1)', source)
        self.assertIn('render_annual_chart(url, data, year, selected_eac,', source)
        tree = ast.parse(inspect.getsource(render))
        chart_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name)
                       and n.func.id == "render_annual_chart"]
        self.assertEqual(len(chart_calls), 1)
        kwargs = {k.arg: k.value for k in chart_calls[0].keywords}
        self.assertEqual(kwargs["code"].id, "selected_director")

    def test_snapshots_catalog_reuses_eac_board_listing(self):
        frame = pd.DataFrame([
            {"id": 3, "year": 2027, "quarter": 1, "status": "draft"},
            {"id": 1, "year": 2026, "quarter": 3, "status": "published"},
        ])
        available_eac_snapshots.clear()
        with patch("poe_board.list_snapshots", return_value=frame) as listing:
            self.assertEqual(available_eac_snapshots("unused").iloc[0]["id"], 3)
            self.assertEqual(available_eac_snapshots("unused").iloc[0]["id"], 3)
        listing.assert_called_once_with("unused")

    def test_real_percentage_labels_use_selected_eac(self):
        data = {"directors": {"A": "DIRECTOR"}, "visible": {"A": True},
                "opening": {"A": Decimal(200)}, "opening_count": {"A": 1},
                "hours": {("A", date(2026, 1, 1)): (Decimal(50), None),
                          ("A", date(2026, 2, 1)): (Decimal(50), Decimal(60))}}
        ref = {"year": 2026, "quarter": 4, "eac_hours": Decimal(1000),
               "projects": 1}
        with patch("poe_board.director_eac", return_value=ref) as get_eac, \
             patch("poe_board.st.plotly_chart") as chart, \
             patch("poe_board.st.subheader"), \
             patch("poe_board.st.caption"):
            render_annual_chart("unused", data, 2026, 9, code="A")
        get_eac.assert_called_once_with("unused", "A", 9)
        figure = chart.call_args.args[0]
        real = next(trace for trace in figure.data if trace.name == "POE incurrido")
        limit = next(trace for trace in figure.data if trace.name == "Límite EAC")
        eac_label = figure.data[-1]
        self.assertEqual(eac_label.name, "Etiqueta EAC")
        self.assertEqual(eac_label.text, ("<b>EAC (2026 Q4) = 1.000 horas</b>",))
        self.assertEqual(eac_label.mode, "text")
        self.assertEqual(eac_label.textfont.color, "#F28C28")
        self.assertEqual(eac_label.textfont.size, 15)
        self.assertEqual(eac_label.showlegend, False)
        self.assertEqual(eac_label.hoverinfo, "skip")
        labels = figure.layout.annotations
        self.assertEqual([a.text for a in labels], ["<b>25%</b>", "<b>30%</b>"])
        self.assertTrue(all(a.textangle == -90 for a in labels))
        self.assertTrue(all(a.showarrow is False for a in labels))
        self.assertEqual(real.mode, "lines+markers")
        self.assertEqual(limit.y[0], 1000)

    def test_no_percentage_when_selected_eac_zero(self):
        data = {"directors": {"A": "DIRECTOR"}, "visible": {"A": True},
                "opening": {}, "opening_count": {},
                "hours": {("A", date(2026, 1, 1)): (Decimal(50), None)}}
        ref = {"year": 2026, "quarter": 3, "eac_hours": Decimal(0),
               "projects": 1}
        with patch("poe_board.director_eac", return_value=ref), \
             patch("poe_board.st.plotly_chart") as chart, \
             patch("poe_board.st.subheader"), \
             patch("poe_board.st.caption"):
            render_annual_chart("unused", data, 2026, 1, code="A")
        trace = next(trace for trace in chart.call_args.args[0].data
                     if trace.name == "POE incurrido")
        self.assertEqual(trace.mode, "lines+markers")
        self.assertFalse(any(t.name == "Porcentaje incurrido"
                             for t in chart.call_args.args[0].data))
        self.assertEqual(sum(t.name == "Etiqueta EAC" for t in chart.call_args.args[0].data), 1)

    def test_bar_poe_lifetime_totals_independent_of_selected_year(self):
        data = {"directors": {"A": "FIRST", "B": "HIDDEN", "C": "THIRD"},
                "visible": {"A": True, "B": False, "C": True},
                "hours": {}}
        sources = [{"code": "A", "eac_hours": Decimal(1000),
                    "incurred_hours": Decimal(350), "projects": 2,
                    "poe_real": Decimal(270), "poe_future": Decimal(140)},
                   {"code": "C", "eac_hours": None, "incurred_hours": None,
                    "poe_real": None, "poe_future": None}]
        frame = director_bar_frame(data, sources)
        self.assertEqual(frame.management_group.tolist(), ["A FIRST", "C THIRD"])
        self.assertEqual(frame.loc[0, "poe_real"], Decimal(270))
        self.assertEqual(frame.loc[0, "poe_future"], Decimal(140))
        self.assertEqual(frame.loc[0, "etc_hours"], Decimal(1000))
        self.assertEqual(frame.loc[0, "hours_incurred"], Decimal(350))
        self.assertIsNone(frame.loc[1, "poe_real"])
        self.assertIsNone(frame.loc[1, "poe_future"])
        self.assertNotIn("year", inspect.signature(director_bar_frame).parameters)

    def test_bar_uses_shared_eac_chart_lime_and_light_gray_stack(self):
        data = {"directors": {"A": "FIRST"}, "visible": {"A": True},
                "hours": {}}
        with patch("poe_board.eac_chart") as chart, \
             patch("poe_board.st.subheader"), patch("poe_board.st.caption"):
            render_director_bars(data, [
                {"code": "A", "eac_hours": Decimal(500),
                 "incurred_hours": Decimal(200), "poe_real": Decimal(100),
                 "poe_future": Decimal(150), "erp_date": date(2026, 10, 15)}
            ])
        chart.assert_called_once()
        args, kwargs = chart.call_args
        self.assertEqual(args[1], "management_group")
        self.assertEqual(list(kwargs["metrics"].values()),
                         ["EAC", "POE real", "POE previsto", "Incurrido OF"])
        self.assertEqual(kwargs["palette"]["POE real"], LIME)
        self.assertEqual(kwargs["palette"]["POE previsto"], "#E7E9EB")
        self.assertEqual(kwargs["stack_groups"]["POE real"], "POE")
        self.assertEqual(kwargs["stack_groups"]["POE previsto"], "POE")
        self.assertNotEqual(kwargs["stack_groups"]["EAC"], "POE")
        self.assertNotEqual(kwargs["stack_groups"]["Incurrido OF"], "POE")

    def test_existing_eac_chart_remains_grouped_and_poe_segments_stack(self):
        from eac_board import chart as shared_chart
        frame = pd.DataFrame([{
            "management_group": "110040 DRAGON", "etc_hours": 500,
            "poe_real": 100, "poe_future": 150, "hours_incurred": 200
        }])
        with patch("eac_board.st.plotly_chart") as plot:
            shared_chart(frame, "management_group", metrics={
                "etc_hours": "EAC", "poe_real": "POE real",
                "poe_future": "POE previsto", "hours_incurred": "Incurrido OF",
            }, stack_groups={"EAC": "EAC", "POE real": "POE",
                             "POE previsto": "POE", "Incurrido OF": "OF"})
        fig = plot.call_args.args[0]
        traces = {trace.name: trace for trace in fig.data}
        self.assertEqual(fig.layout.barmode, "relative")
        self.assertEqual(traces["POE real"].offsetgroup, traces["POE previsto"].offsetgroup)
        self.assertNotEqual(traces["POE real"].offsetgroup, traces["EAC"].offsetgroup)
        self.assertEqual(sum([traces["POE real"].y[0], traces["POE previsto"].y[0]]), 250)
        original = pd.DataFrame([{
            "management_group": "110040 DRAGON", "etc_hours": 500,
            "hours_granted": 300, "hours_incurred": 200
        }])
        with patch("eac_board.st.plotly_chart") as plot:
            shared_chart(original, "management_group")
        self.assertEqual(plot.call_args.args[0].layout.barmode, "group")

    def test_bar_snapshot_query_one_read_latest_ct422_and_cached(self):
        class DB:
            def __init__(self):
                self.calls = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql, params=()):
                self.calls.append((sql, params))
                return self
            def fetchall(self):
                return [{"code": "A", "eac_hours": Decimal(1000),
                         "incurred_hours": Decimal(200), "projects": 2,
                         "erp_date": date(2026, 10, 15)}]
        db = DB()
        director_bar_sources.clear()
        with patch("poe_board.connect", return_value=db):
            sources = director_bar_sources("unused", 9, ("A",))
            self.assertEqual(director_bar_sources("unused", 9, ("A",)), sources)
        self.assertEqual(len(db.calls), 1)
        sql, params = db.calls[0]
        self.assertEqual(params, (9, ["A"]))
        self.assertIn("MAX(snapshot_date)", sql)
        self.assertIn("work_center='422'", sql)
        self.assertIn("eac_project_hours", sql)
        self.assertIn("poe_monthly_hours", sql)
        self.assertIn("MAX(period) AS last_real", sql)
        self.assertIn("h.period > l.last_real", sql)
        self.assertNotIn("UPDATE ", sql)
        self.assertNotIn("INSERT ", sql)
        self.assertNotIn("DELETE ", sql)

    def test_annual_chart_reuses_bar_reference_without_extra_db(self):
        data = {"directors": {"A": "FIRST"}, "visible": {"A": True},
                "opening": {"A": None}, "opening_count": {"A": 0},
                "hours": {("A", date(2026, 1, 1)): (Decimal(100), None)}}
        reference = {"year": 2026, "quarter": 3,
                     "eac_hours": Decimal(500), "projects": 2}
        with patch("poe_board.director_eac") as redundant, \
             patch("poe_board.st.plotly_chart") as plot, \
             patch("poe_board.st.subheader"), patch("poe_board.st.caption"):
            render_annual_chart("unused", data, 2026, 9, reference, code="A")
        redundant.assert_not_called()
        self.assertEqual(plot.call_args.args[0].data[0].y[0], 500)

    def test_no_data_for_selected_year_skips_chart_and_database(self):
        data = {"directors": {"A": "DIRECTOR"}, "visible": {"A": True},
                "opening": {"A": Decimal(200)}, "opening_count": {"A": 1},
                "hours": {("A", date(2025, 1, 1)): (Decimal(100), None)}}
        with patch("poe_board.director_eac") as lookup, \
             patch("poe_board.st.plotly_chart") as plot, \
             patch("poe_board.st.info") as notice:
            render_annual_chart("unused", data, 2026, 1, code="A")
        lookup.assert_not_called()
        plot.assert_not_called()
        notice.assert_called_once_with("Sin datos")
        annual, _ = annual_frame(data, 2026)
        self.assertTrue(all(pd.isna(annual.iloc[0][m]) for m in MONTHS))

    def test_evolution_colors_and_forecast_dotted(self):
        data = {"directors": {"A": "DIRECTOR"}, "visible": {"A": True},
                "opening": {"A": Decimal(200)}, "opening_count": {"A": 1},
                "hours": {("A", date(2026, 1, 1)): (Decimal(100), Decimal(120))}}
        ref = {"year": 2026, "quarter": 3, "eac_hours": Decimal(1000),
               "projects": 1}
        with patch("poe_board.st.plotly_chart") as plot, \
             patch("poe_board.st.subheader"), patch("poe_board.st.caption"):
            render_annual_chart("unused", data, 2026, 1, reference=ref, code="A")
        traces = {t.name: t for t in plot.call_args.args[0].data}
        self.assertEqual(traces["Límite EAC"].line.color, "#F28C28")
        self.assertEqual(traces["POE previsto"].line.color, "#E7E9EB")
        self.assertEqual(traces["POE previsto"].line.dash, "dot")
        self.assertEqual(traces["POE incurrido"].line.color, "#2563EB")
        self.assertEqual([t.name for t in plot.call_args.args[0].data if t.showlegend is not False],
                         ["Límite EAC", "POE previsto", "POE incurrido"])
        self.assertEqual(plot.call_args.args[0].layout.annotations[0].font.color, "#2563EB")
        self.assertEqual(plot.call_args.args[0].layout.yaxis.range[0], 0)

    def test_2025_dragon_real_series_from_neon_and_no_forecast(self):
        data = {"directors": {"110040": "DRAGON"}, "visible": {"110040": True},
                "opening": {"110040": None}, "opening_count": {"110040": 0},
                "hours": {}}
        monthly = [0, 977, 1319, 1009, 1120, 1458, 1337, 906, 1529, 1513, 1511, 1461]
        for month, hours in enumerate(monthly, 1):
            data["hours"][("110040", date(2025, month, 1))] = (Decimal(hours), None)
        actual, forecast, last_real, gaps = annual_evolution(data, "110040", 2025)
        self.assertEqual(actual, [0, 977, 2296, 3305, 4425, 5883,
                                  7220, 8126, 9655, 11168, 12679, 14140])
        self.assertEqual(forecast, [None] * 12)
        self.assertEqual(last_real, 12)
        self.assertEqual(gaps, [])

    def test_chart_reuses_selected_read_year_and_existing_data(self):
        tree = ast.parse(inspect.getsource(render))
        chart_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name)
                       and n.func.id == "render_annual_chart"]
        self.assertEqual(len(chart_calls), 1)
        self.assertEqual([a.id for a in chart_calls[0].args],
                         ["url", "data", "year", "selected_eac"])
        # No additional year is loaded just to draw the plot.
        self.assertNotIn("chart_year", inspect.getsource(render))

    def test_chart_fixed_zero_minimum_and_navigation_locked(self):
        data = {"directors": {"110040": "DRAGON"}, "visible": {"110040": True},
                "opening": {"110040": None}, "opening_count": {"110040": 0},
                "hours": {("110040", date(2025, 1, 1)): (Decimal(0), None),
                          ("110040", date(2025, 2, 1)): (Decimal(977), None)}}
        eac = {"year": 2026, "quarter": 3, "eac_hours": Decimal(48526),
               "projects": 4}
        with patch("poe_board.director_eac", return_value=eac), \
             patch("poe_board.st.plotly_chart") as chart, \
             patch("poe_board.st.subheader"), \
             patch("poe_board.st.caption"):
            render_annual_chart("unused", data, 2025, 1, code="110040")
        figure = chart.call_args.args[0]
        self.assertEqual(figure.layout.yaxis.range[0], 0)
        self.assertGreater(figure.layout.yaxis.range[1], 48526)
        self.assertTrue(figure.layout.yaxis.fixedrange)
        self.assertTrue(figure.layout.xaxis.fixedrange)
        self.assertFalse(figure.layout.dragmode)
        self.assertEqual(figure.layout.hovermode, "x unified")
        self.assertEqual(chart.call_args.kwargs["config"],
                         {"displayModeBar": False, "scrollZoom": False,
                          "doubleClick": False})

    def test_empty_chart_shows_no_data_without_query_or_plot(self):
        data = {"directors": {"A": "DIRECTOR"}, "visible": {"A": True},
                "opening": {"A": None}, "opening_count": {"A": 0},
                "hours": {}}
        with patch("poe_board.director_eac") as eac, \
             patch("poe_board.st.plotly_chart") as chart, \
             patch("poe_board.st.info") as info:
            render_annual_chart("unused", data, 2025, 1, code="A")
        eac.assert_not_called()
        chart.assert_not_called()
        info.assert_called_once_with("Sin datos")

    def test_chart_omits_vertical_axis_title(self):
        tree = ast.parse(inspect.getsource(render_annual_chart))
        layouts = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "update_layout"]
        self.assertEqual(len(layouts), 1)
        titles = [k.value for k in layouts[0].keywords if k.arg == "yaxis_title"]
        self.assertEqual(len(titles), 1)
        self.assertIsInstance(titles[0], ast.Constant)
        self.assertIsNone(titles[0].value)

    def test_2026_dragon_actual_and_forecast_from_neon_sample(self):
        from decimal import Decimal
        data = {"directors": {"110040": "DRAGON"}, "visible": {"110040": True},
                "opening": {"110040": None}, "opening_count": {"110040": 0},
                "hours": {}}
        real = [1563, 1752, 1559, 862, 976, 1083, 869, 362, 1054, 918]
        for month, h in enumerate(real, 1):
            data["hours"][("110040", date(2026, month, 1))] = (Decimal(h), None)
        data["hours"][("110040", date(2026, 11, 1))] = (None, Decimal(896))
        data["hours"][("110040", date(2026, 12, 1))] = (None, Decimal(552))
        incurred, forecast, last_real, gaps = annual_evolution(data, "110040", 2026)
        self.assertEqual(last_real, 10)
        self.assertEqual(incurred[9], 10998)
        self.assertEqual(forecast[10:], [11894, 12446])
        self.assertEqual(gaps, [])

    def test_forecast_is_visible_alongside_real_for_every_recorded_month(self):
        period = lambda month: date(2026, month, 1)
        data = {"hours": {
            ("A", period(1)): (Decimal(100), None),
            ("A", period(2)): (Decimal(120), Decimal(150)),
            ("A", period(3)): (Decimal(90), Decimal(80)),
            ("A", period(4)): (Decimal(0), Decimal(0)),
            ("A", period(6)): (None, Decimal(40)),
            ("A", period(8)): (Decimal(70), Decimal(60)),
            ("A", period(10)): (None, Decimal(25)),
        }, "opening": {"A": Decimal(500)}, "opening_count": {"A": 1}}
        actual, planned, last_real, gaps = annual_evolution(data, "A", 2026)
        self.assertEqual(actual[0:4], [600, 720, 810, 810])
        self.assertEqual(planned[0:4], [None, 750, 830, 830])
        self.assertEqual(planned[5], 870)
        self.assertEqual(planned[7], 930)
        self.assertEqual(planned[9], 955)
        self.assertEqual(actual[7], 880)
        self.assertEqual(last_real, 8)
        self.assertIn(5, gaps)
        self.assertIsNone(planned[4])
        self.assertEqual(len(planned), 12)

    def test_plot_does_not_overwrite_forecast_on_last_real_month(self):
        period = date(2026, 10, 1)
        data = {"directors": {"A": "DIRECTOR"}, "visible": {"A": True},
                "opening": {"A": None}, "opening_count": {"A": 0},
                "hours": {("A", period): (Decimal(90), Decimal(75)),
                          ("A", date(2026, 11, 1)): (None, Decimal(40))}}
        with patch("poe_board.director_eac", return_value=None), \
             patch("poe_board.st.plotly_chart") as chart, \
             patch("poe_board.st.subheader"), \
             patch("poe_board.st.warning"), \
             patch("poe_board.st.caption"):
            render_annual_chart("unused", data, 2026, 1, code="A")
        figure = chart.call_args.args[0]
        planned_trace = next(t for t in figure.data if t.name == "POE previsto")
        real_trace = next(t for t in figure.data if t.name == "POE incurrido")
        self.assertEqual(planned_trace.y[9], 75)
        self.assertEqual(planned_trace.y[10], 115)
        self.assertEqual(real_trace.y[9], 90)

    def test_manual_opening_real_includes_previous_year(self):
        data = {"hours": {("A", date(2026, 1, 1)): (Decimal(100), None),
                          ("A", date(2026, 2, 1)): (None, Decimal(50))},
                "opening": {"A": Decimal(700)}, "opening_count": {"A": 1}}
        actual, planned, last_actual, gaps = annual_evolution(data, "A", 2026)
        self.assertEqual(actual[0], 800)
        self.assertEqual(planned[1], 850)
        self.assertEqual(last_actual, 1)
        self.assertIn(3, gaps)

    def test_zero_is_valid_real_and_gaps_not_replaced_by_zero(self):
        data = {"hours": {("A", date(2026, 1, 1)): (Decimal(0), None),
                          ("A", date(2026, 3, 1)): (Decimal(50), None)},
                "opening": {}, "opening_count": {}}
        actual, planned, _, gaps = annual_evolution(data, "A", 2026)
        self.assertEqual(actual[0], 0)
        self.assertIsNone(actual[1])
        self.assertEqual(actual[2], 50)
        self.assertIn(2, gaps)

    def test_eac_is_read_only_and_single_aggregate_query(self):
        class DB:
            def __init__(self):
                self.calls = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def execute(self, sql, params=()):
                self.calls.append((sql, params))
                return self
            def fetchone(self):
                return {"year": 2026, "quarter": 3, "eac_hours": Decimal(48526), "projects": 4}
        db = DB()
        with patch("poe_board.connect", return_value=db):
            director_eac.clear()
            value = director_eac("unused", "110040", 1)
            self.assertEqual(value["eac_hours"], Decimal(48526))
        self.assertEqual(len(db.calls), 1)
        self.assertIn("eac_snapshots", db.calls[0][0])
        self.assertIn("eac_project_hours", db.calls[0][0])
        self.assertEqual(db.calls[0][1], (1, "110040"))
        self.assertFalse(any("UPDATE " in sql or "INSERT " in sql or "DELETE " in sql
                             for sql, _ in db.calls))

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
        self.assertEqual(len(frame.columns), 14)
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
