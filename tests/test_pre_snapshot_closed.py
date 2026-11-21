"""Regression tests for the four-file offline pre-snapshot."""
import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from consolidar_ooff_texto import HEADERS
from prepare_snapshot import inspect_erp_sources, prepare


def write_pipe(path, headers, rows):
    with path.open("w", encoding="cp1252", newline="") as f:
        writer = csv.writer(f, delimiter="|", lineterminator="\r\n")
        writer.writerow(headers)
        writer.writerows(rows)


class PreSnapshotClosedTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.hours = self.root / "OOFF_OP_Planif_Terminada.txt"
        self.closed = self.root / "OOFFCerradasMO.txt"
        self.projects = self.root / "Proyectos_Sevilla.csv"
        self.source = self.root / "ooff_texto.csv"
        self.out = self.root / "out.zip"
        write_pipe(self.hours, ["Orden", "Ct.", "Proyec", "Opr."],
                   [["111111", "422", "P1", "1"], ["111111", "010", "P1", "2"]])
        write_pipe(self.closed, ["O_FABR", "ESTATU", "H_INV_TOT_"],
                   [["222222", "Cerrad", "1234,5678"], ["333333", "Activa", "0"]])
        write_pipe(self.projects, ["Proyecto", "Descripción", "Estatus"], [["P1", "Proyecto", "Activo"]])
        write_pipe(self.source, HEADERS, [])

    def test_preserves_existing_indexes_and_adds_new_ones(self):
        manifest = prepare(self.hours, self.projects, self.source, self.out,
                           "422", "2026-11-21", self.closed)
        self.assertEqual(manifest["unique_of_selected"], 1)
        self.assertEqual(manifest["unique_bonuses_selected"], 1)
        self.assertEqual(manifest["closed_of_count"], 1)
        self.assertEqual(manifest["bonus_ct_registry_count"], 2)
        self.assertIn(self.closed.name, manifest["source_files_sha256"])
        with zipfile.ZipFile(self.out) as z:
            self.assertIsNone(z.testzip())
            self.assertIn("of/111111.json", z.namelist())
            self.assertEqual(set(["indice_of.csv", "indice_bonos.csv",
                                 "indice_bono_ct.csv", "indice_of_cerradas.csv"])
                             - set(z.namelist()), set())
            def index(name):
                return list(csv.DictReader(io.StringIO(z.read(name).decode("utf-8-sig")), delimiter=";"))
            self.assertEqual([r["Bono numero"] for r in index("indice_bonos.csv")], ["1111110001"])
            self.assertEqual({r["Bono numero"]: r["Ct."] for r in index("indice_bono_ct.csv")},
                             {"1111110001": "422", "1111110002": "010"})
            self.assertEqual(index("indice_of_cerradas.csv"),
                             [{"OF numero": "222222", "H_INV_TOT_": "1234.5678"}])

    def test_overlap_blocks_even_in_other_ct(self):
        write_pipe(self.hours, ["Orden", "Ct.", "Proyec", "Opr."],
                   [["222222", "010", "P1", "3"], ["111111", "422", "P1", "1"]])
        with self.assertRaisesRegex(ValueError, "OF presentes en horas y cerradas"):
            prepare(self.hours, self.projects, self.source, self.out,
                    "422", "2026-11-21", self.closed)
        self.assertFalse(self.out.exists())

    def test_only_cerrad_status_counts(self):
        write_pipe(self.closed, ["O_FABR", "ESTATU", "H_INV_TOT_"],
                   [["111111", "Activa", "20"], ["222222", "Cerrad", "12"]])
        _, closed = inspect_erp_sources(self.hours, self.closed)
        self.assertEqual(closed, {"222222": "12.0000"})

    def test_conflicting_bonus_ct_blocks(self):
        write_pipe(self.hours, ["Orden", "Ct.", "Proyec", "Opr."],
                   [["111111", "422", "P1", "1"], ["111111", "010", "P1", "1"]])
        with self.assertRaisesRegex(ValueError, "CT contradictorios"):
            inspect_erp_sources(self.hours, self.closed)

    def test_missing_closed_file_blocks(self):
        self.closed.unlink()
        with self.assertRaises(FileNotFoundError):
            prepare(self.hours, self.projects, self.source, self.out,
                    "422", "2026-11-21", self.closed)

    def test_blank_erp_separator_lines_are_skipped(self):
        with self.hours.open("a", encoding="cp1252") as stream:
            stream.write("\n")
        with self.closed.open("a", encoding="cp1252") as stream:
            stream.write("\n")
        bonus_ct, closed = inspect_erp_sources(self.hours, self.closed)
        self.assertEqual(len(bonus_ct), 2)
        self.assertEqual(closed, {"222222": "1234.5678"})

    def test_duplicate_closed_order_blocks(self):
        write_pipe(self.closed, ["O_FABR", "ESTATU", "H_INV_TOT_"],
                   [["222222", "Cerrad", "1"], ["222222", "Cerrad", "2"]])
        with self.assertRaisesRegex(ValueError, "duplicada"):
            inspect_erp_sources(self.hours, self.closed)


if __name__ == "__main__":
    unittest.main()
