"""Tests for the encrypted ERP ZIP input gate without a real password/7-Zip.

Run: python -m unittest discover -s tests -p 'test_prepare_input_zip.py' -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from prepare_input_zip import EXPECTED, prepare


class EncryptedZipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / "data"
        self.data_dir.mkdir()
        self.archive = self.data_dir / "planificacion-lse.zip"
        self.archive.write_bytes(b"dummy encrypted ZIP for mocked tests")

    def fake_7zip(self, executable, operation, archive, password, destination=None):
        self.assertEqual(password, "dummy-password")
        if operation == "x":
            for name in EXPECTED:
                (destination / name).write_bytes(("ERP:" + name).encode())

    @patch.dict(os.environ, {"LSE_ZIP_PASSWORD": "dummy-password"})
    @patch("prepare_input_zip.resolve_7zip", return_value="7z")
    @patch("prepare_input_zip.verify_zip_layout")
    def test_extract_once_and_reuse_without_seven_zip(self, *_):
        with patch("prepare_input_zip.run_7zip", side_effect=self.fake_7zip) as run:
            self.assertEqual(prepare(self.archive, self.data_dir), "EXTRAIDO")
            self.assertEqual(run.call_count, 2)
        self.assertEqual(prepare(self.archive, self.data_dir, check_only=True), "EXTRACCION_VERIFICADA")
        with patch("prepare_input_zip.run_7zip") as run:
            self.assertEqual(prepare(self.archive, self.data_dir), "SIN_CAMBIOS")
            run.assert_not_called()
        self.assertEqual(len([p for p in EXPECTED if (self.data_dir / p).is_file()]), 4)

    @patch.dict(os.environ, {"LSE_ZIP_PASSWORD": "dummy-password"})
    @patch("prepare_input_zip.resolve_7zip", return_value="7z")
    @patch("prepare_input_zip.verify_zip_layout")
    def test_failed_password_does_not_overwrite_existing_files(self, *_):
        for name in EXPECTED:
            (self.data_dir / name).write_text("previous")
        with patch("prepare_input_zip.run_7zip", side_effect=ValueError("bad password")):
            with self.assertRaises(ValueError):
                prepare(self.archive, self.data_dir)
        self.assertTrue(all((self.data_dir / name).read_text() == "previous" for name in EXPECTED))

    @patch.dict(os.environ, {"LSE_ZIP_PASSWORD": "dummy-password"})
    @patch("prepare_input_zip.resolve_7zip", return_value="7z")
    @patch("prepare_input_zip.verify_zip_layout")
    def test_partial_extract_never_replaces_inputs(self, *_):
        for name in EXPECTED:
            (self.data_dir / name).write_text("previous")
        def incomplete(executable, operation, archive, password, destination=None):
            if operation == "x":
                (destination / EXPECTED[0]).write_text("only one")
        with patch("prepare_input_zip.run_7zip", side_effect=incomplete):
            with self.assertRaisesRegex(ValueError, "incompleta"):
                prepare(self.archive, self.data_dir)
        self.assertTrue(all((self.data_dir / name).read_text() == "previous" for name in EXPECTED))

    @patch.dict(os.environ, {"LSE_ZIP_PASSWORD": "dummy-password"})
    @patch("prepare_input_zip.resolve_7zip", return_value="7z")
    @patch("prepare_input_zip.verify_zip_layout")
    def test_tampering_with_extracted_file_blocks_load(self, *_):
        with patch("prepare_input_zip.run_7zip", side_effect=self.fake_7zip):
            prepare(self.archive, self.data_dir)
        (self.data_dir / EXPECTED[0]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "obsoleta"):
            prepare(self.archive, self.data_dir, check_only=True)


if __name__ == "__main__":
    unittest.main()
