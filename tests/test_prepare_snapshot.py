"""Pruebas de regresión de pre_snapshot (sin Neon ni datos ERP reales)."""
import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_snapshot import prepare
from consolidar_ooff_texto import HEADERS


class SnapshotRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.hours = self.root / "OOFF_OP_Planif_Terminada.txt"
        self.projects = self.root / "Proyectos_Sevilla.csv"
        self.source = self.root / "ooff_texto.csv"
        self.output = self.root / "ooff_texto_consolidado.zip"
        self.hours.write_text(
            "Orden|Ct.|Proyec|Opr.\n"
            "967673|422|MPILSE|10\n"
            "967673|422|MPILSE|20\n"
            "967674|422|MPILSE|10\n"
            "999999|010|OTRO|10\n", encoding="cp1252"
        )
        self.projects.write_text(
            "Proyecto|Descripción|Estatus\nMPILSE|Prueba|Activo\n",
            encoding="cp1252"
        )

    def run_prepare(self):
        report = prepare(self.hours, self.projects, self.source, self.output, "422", "2026-10-14")
        with zipfile.ZipFile(self.output) as z:
            self.assertIsNone(z.testzip())
            manifest = json.loads(z.read("manifiesto.json"))
            ids_of = list(csv.DictReader(io.StringIO(z.read("indice_of.csv").decode("utf-8-sig")), delimiter=";"))
            ids_bo = list(csv.DictReader(io.StringIO(z.read("indice_bonos.csv").decode("utf-8-sig")), delimiter=";"))
            dossiers = {p: json.loads(z.read(p)) for p in z.namelist() if p.startswith("of/")}
        self.assertEqual(len(ids_of), 2)
        self.assertEqual(len(ids_bo), 3)
        self.assertEqual({r["Bono numero"] for r in ids_bo}, {"9676730010","9676730020","9676740010"})
        self.assertEqual(set(dossiers), {"of/967673.json", "of/967674.json"})
        self.assertEqual(report, manifest)
        self.assertEqual(manifest["source_files_sha256"]["ooff_texto.csv"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        return manifest, dossiers

    def test_tabular(self):
        rows = [
            ["967673","ITEM","Descripcion","0","Activa","","1","Ingeniería detallada","Sí","","","","",""],
            ["967673","ITEM","Descripcion","0","Activa","","1","Texto con | delimitador interno","Sí","","","","",""],
            ["967674","ITEM","Descripcion","0","Activa","","1","Tarea distinta","Sí","","","","",""],
        ]
        with self.source.open("w", encoding="cp1252", newline="") as f:
            f.write("|".join(HEADERS) + "\r\n")
            for row in rows:
                f.write("|".join(row) + "\r\n")
        manifest, dossiers = self.run_prepare()
        self.assertEqual(manifest["missing_of"], [])
        self.assertEqual(manifest["source_lines_selected"], 3)
        self.assertEqual(dossiers["of/967673.json"]["records"][1]["fields"]["Texto"], "Texto con | delimitador interno")
        self.assertFalse(dossiers["of/967673.json"]["missing_in_ooff_texto"])

    def test_paged_report(self):
        def header(order):
            cols = [order, "ARTICULO", "DESCRIPCION", "", "", "", "", "", "0", "Activa", "Sí"]
            return "|".join(cols)
        self.source.write_bytes((
            "Fecha  : 14/10/26 [12:07]     ÓRDENES DE FABRICACIÓN POR NÚMERO DE ORDEN     Página : 1;\r\n"
            "Fábrica de Sevilla\r\n"
            + header("967673") + "\r\n"
            + "                         |Trabajo de ingeniería| \r\n"
            + header("967674") + "\r\n"
            + "                         |Trabajos de pruebas| \r\n"
        ).encode("cp1252"))
        manifest, dossiers = self.run_prepare()
        self.assertEqual(manifest["missing_of"], [])
        self.assertIn("Trabajo de ingeniería", [r["fields"]["Texto"] for r in dossiers["of/967673.json"]["records"]])

    def test_missing_of_marked_not_blocked(self):
        row = ["967673","ITEM","Descripcion","0","Activa","","1","Descripción","Sí","","","","",""]
        self.source.write_text("|".join(HEADERS) + "\n" + "|".join(row) + "\n",encoding="cp1252")
        manifest, dossiers = self.run_prepare()
        self.assertEqual(manifest["missing_of"], ["967674"])
        self.assertEqual(dossiers["of/967674.json"]["records"], [])
        self.assertTrue(dossiers["of/967674.json"]["missing_in_ooff_texto"])
        self.assertEqual(dossiers["of/967674.json"]["missing_description_value"], "### SIN DATOS ###")

    def test_invalid_csv_rejected_without_output(self):
        self.source.write_text("invalid\n",encoding="cp1252")
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.assertFalse(self.output.exists())

    def test_source_must_be_csv(self):
        renamed = self.root / "ooff_texto.zip"
        renamed.write_text("not a zip",encoding="utf-8")
        with self.assertRaises(ValueError):
            prepare(self.hours, self.projects, renamed, self.output, "422","2026-10-14")


if __name__ == "__main__":
    unittest.main()
