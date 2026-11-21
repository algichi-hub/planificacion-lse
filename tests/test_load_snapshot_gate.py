"""Offline gate regression: all inputs must agree before any Neon connection."""
from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from consolidar_ooff_texto import HEADERS
from prepare_snapshot import prepare
from validate_snapshot import validate


def pipe(path, headers, rows):
    with path.open("w", encoding="cp1252", newline="") as f:
        w = csv.writer(f, delimiter="|", lineterminator="\r\n")
        w.writerow(headers)
        w.writerows(rows)


def llm(path, header, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\r\n")
        w.writerow(header)
        w.writerows(rows)


class LoadGateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.hours = base / "OOFF_OP_Planif_Terminada.txt"
        self.closed = base / "OOFFCerradasMO.txt"
        self.projects = base / "Proyectos_Sevilla.csv"
        self.source = base / "ooff_texto.csv"
        self.of = base / "ooff_texto_interpretado.csv"
        self.bonus = base / "bono_texto_interpretado.csv"
        self.zip = base / "prepared.zip"
        pipe(self.hours, ["Orden", "Ct.", "Proyec", "Opr."],
             [["111111", "422", "P1", "10"], ["111111", "010", "P1", "20"]])
        pipe(self.closed, ["O_FABR", "ESTATU", "H_INV_TOT_"],
             [["222222", "Cerrad", "17,1234"]])
        pipe(self.projects, ["Proyecto", "Descripción", "Estatus"],
             [["P1", "test", "Activo"]])
        pipe(self.source, HEADERS, [])
        prepare(self.hours, self.projects, self.source, self.zip, "422", "2026-11-21", self.closed)
        llm(self.of, ["OF numero", "of_detailed_description"],
            [["111111", "### SIN DATOS ###"]])
        llm(self.bonus, ["Bono numero", "bo_detailed_description"],
            [["1111110010", "### SIN DATOS ###"]])

    def gate(self, date="2026-11-21"):
        return validate(self.hours, self.projects, self.of, self.bonus, "422",
                        self.zip, snapshot_date=date,
                        closed_file=self.closed, source_file=self.source)

    def test_cli_validate_only_without_database_dependencies(self):
        """Real CLI must validate offline without psycopg or python-dotenv installed."""
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        args = [
            sys.executable, "-S", str(scripts / "import_erp.py"),
            "--hours", str(self.hours),
            "--closed", str(self.closed),
            "--source-text", str(self.source),
            "--projects", str(self.projects),
            "--of-text", str(self.of),
            "--bonus-text", str(self.bonus),
            "--prepared-zip", str(self.zip),
            "--ct", "422",
            "--snapshot-date", "2026-11-21",
            "--validate-only",
        ]
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("VALIDATE ONLY: sin conexión", result.stdout)

    def test_all_six_inputs_and_indexes_pass(self):
        result = self.gate()
        self.assertEqual(result.orders, {"111111"})
        self.assertEqual(result.bonuses, {"1111110010"})

    def test_closed_file_changed_since_prepare_blocks(self):
        with self.closed.open("a", encoding="cp1252") as f:
            f.write("333333|Cerrad|1,0000\n")
        with self.assertRaisesRegex(ValueError, "ha cambiado"):
            self.gate()

    def test_source_text_changed_since_prepare_blocks(self):
        with self.source.open("a", encoding="cp1252") as f:
            f.write("NUEVA LINEA\n")
        with self.assertRaisesRegex(ValueError, "ha cambiado"):
            self.gate()

    def test_wrong_snapshot_date_blocks(self):
        with self.assertRaisesRegex(ValueError, "Fecha del ZIP"):
            self.gate("2026-11-22")

    def test_extra_llm_bonus_blocks(self):
        llm(self.bonus, ["Bono numero", "bo_detailed_description"],
            [["1111110010", "texto"], ["1111110020", "bono de otro Ct."]])
        with self.assertRaisesRegex(ValueError, "Cobertura bonos incorrecta"):
            self.gate()

    def test_missing_zip_blocks(self):
        self.zip.unlink()
        with self.assertRaises(FileNotFoundError):
            self.gate()


if __name__ == "__main__":
    unittest.main()
