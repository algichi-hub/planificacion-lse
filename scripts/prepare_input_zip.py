"""Safely prepare the four original ERP files from planificacion-lse.zip (AES ZIP).

Requires 7-Zip installed, and LSE_ZIP_PASSWORD in the environment.
No credentials are persisted. Existing extracted data are replaced only after
a successful test and extraction of all four inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

EXPECTED = (
    "OOFF_OP_Planif_Terminada.txt",
    "OOFFCerradasMO.txt",
    "Proyectos_Sevilla.csv",
    "ooff_texto.csv",
)
STATE = ".planificacion_lse_zip_state.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_7zip(explicit: str | None = None) -> str:
    candidates = [explicit, shutil.which("7z"), shutil.which("7zz"), shutil.which("7za")]
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(str(Path(root) / "7-Zip" / "7z.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise FileNotFoundError("7-Zip no encontrado. Instala 7-Zip o indica --seven-zip RUTA")


def verify_zip_layout(archive: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        records = [record for record in z.infolist() if not record.is_dir()]
        filenames = [record.filename for record in records]
        if len(filenames) != len(EXPECTED) or set(filenames) != set(EXPECTED):
            raise ValueError(f"ZIP incorrecto: esperados exactamente {list(EXPECTED)}, recibidos {filenames}")
        if any(not (record.flag_bits & 1) or record.compress_type != 99
               for record in records):
            raise ValueError("Se exige que los cuatro ficheros estén cifrados con ZIP AES")
        if any(not any(record.extra[pos:pos+2] == bytes((1, 153))
                       for pos in range(0, len(record.extra)-1))
               for record in records):
            # AES extra field 0x9901; scan permits other ZIP extras as well.
            raise ValueError("ZIP con entradas sin cabecera AES")


def run_7zip(seven_zip: str, operation: str, archive: Path, password: str, destination: Path | None = None) -> None:
    cmd = [seven_zip, operation, "-y", "-bd", "-bso0", "-bsp0", "-bse0", "-p" + password]
    if destination is not None:
        cmd.append("-o" + str(destination))
    cmd.append(str(archive))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Error de 7-Zip al validar/extraer el archivo cifrado. Comprueba contraseña e integridad del ZIP.")


def prepare(archive: Path, data_dir: Path, *, seven_zip: str | None = None, check_only: bool = False) -> str:
    if not archive.is_file():
        raise FileNotFoundError(f"ZIP de entrada no encontrado: {archive}")
    verify_zip_layout(archive)
    digest = sha256(archive)
    manifest_path = data_dir / STATE
    if check_only:
        if not manifest_path.is_file():
            raise ValueError("No existe extracción validada. Ejecuta pre_snapshot.ps1 primero.")
        state = json.loads(manifest_path.read_text(encoding="utf-8"))
        if state.get("zip_sha256") != digest or not all(
            (data_dir / name).is_file()
            and sha256(data_dir / name) == state.get("files_sha256", {}).get(name)
            for name in EXPECTED
        ):
            raise ValueError("Extracción incompleta u obsoleta. Ejecuta pre_snapshot.ps1 de nuevo.")
        return "EXTRACCION_VERIFICADA"

    if manifest_path.is_file():
        try:
            state = json.loads(manifest_path.read_text(encoding="utf-8"))
            if state.get("zip_sha256") == digest and all(
                (data_dir / name).is_file()
                and sha256(data_dir / name) == state.get("files_sha256", {}).get(name)
                for name in EXPECTED
            ):
                return "SIN_CAMBIOS"
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    password = os.environ.get("LSE_ZIP_PASSWORD")
    if not password:
        raise ValueError("Falta la variable de entorno LSE_ZIP_PASSWORD")
    executable = resolve_7zip(seven_zip)
    run_7zip(executable, "t", archive, password)
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".lse-extract-", dir=data_dir) as temp:
        stage = Path(temp)
        run_7zip(executable, "x", archive, password, stage)
        if any(not (stage / name).is_file() or (stage / name).stat().st_size == 0 for name in EXPECTED):
            raise ValueError("Extracción incompleta: falta algún fichero ERP")
        file_hashes = {name: sha256(stage / name) for name in EXPECTED}
        backups = stage / "backup"
        backups.mkdir()
        original = {}
        changed = []
        try:
            for name in EXPECTED:
                target = data_dir / name
                original[name] = target.is_file()
                if original[name]:
                    shutil.copy2(target, backups / name)
                os.replace(stage / name, target)
                changed.append(name)
            state_tmp = stage / "state.json"
            state_tmp.write_text(json.dumps(
                {"zip_sha256": digest, "files_sha256": file_hashes}, indent=2
            ), encoding="utf-8")
            os.replace(state_tmp, manifest_path)
        except Exception:
            for name in reversed(changed):
                target = data_dir / name
                if original[name]:
                    os.replace(backups / name, target)
                else:
                    target.unlink(missing_ok=True)
            raise
    return "EXTRAIDO"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--seven-zip", default=None)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    result = prepare(args.zip.resolve(), args.data_dir.resolve(),
                     seven_zip=args.seven_zip, check_only=args.check_only)
    print(f"ERP ZIP: {result}; fuentes: {len(EXPECTED)}; ubicación: {args.data_dir}")


if __name__ == "__main__":
    main()
