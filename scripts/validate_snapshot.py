"""Validate the four ERP inputs before any connection to Neon.

CSV contract: UTF-8 BOM, semicolon, CRLF, exact columns; full Ct-specific
coverage and no extraneous IDs. An available pre_snapshot ZIP is checked as
an additional provenance gate.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from prepare_snapshot import select_of, check_projects

OF_HEADERS=["OF numero","of_detailed_description"]
BONUS_HEADERS=["Bono numero","bo_detailed_description"]

@dataclass
class ValidatedSnapshot:
    orders: set[str]
    bonuses: set[str]
    project_codes: set[str]
    of_text: dict[str,str]
    bonus_text: dict[str,str]
    hours_rows: int

def check_csv(path: Path, headers: list[str]) -> dict[str,str]:
    raw=path.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path.name}: debe ser UTF-8 con BOM")
    if not raw.endswith(b"\r\n"):
        raise ValueError(f"{path.name}: debe terminar en CRLF")
    # CSV supports quoted newlines; reject bare line breaks outside CRLF.
    if b"\n" in raw.replace(b"\r\n",b""):
        raise ValueError(f"{path.name}: saltos de línea no CRLF")
    text=raw.decode("utf-8-sig")
    rows=csv.reader(io.StringIO(text,newline=""),delimiter=";",quotechar='"',strict=True)
    if next(rows,None)!=headers:
        raise ValueError(f"{path.name}: cabeceras incorrectas, esperadas {headers}")
    result={}
    for number,row in enumerate(rows,2):
        if len(row)!=2: raise ValueError(f"{path.name}, registro {number}: se esperaban 2 columnas")
        key,desc=row
        if not key or key!=key.strip() or not key.isdigit():
            raise ValueError(f"{path.name}, registro {number}: identificador inválido {key!r}")
        if not desc or not desc.strip():
            raise ValueError(f"{path.name}, registro {number}: descripción vacía (usa Vacío)")
        if key in result: raise ValueError(f"{path.name}: duplicado {key}")
        result[key]=desc
    return result

def validate(hours: Path,projects: Path,of_csv: Path,bonus_csv: Path,ct: str,
             prepared_zip:Path|None=None,snapshot_date:str|None=None) -> ValidatedSnapshot:
    for p in (hours,projects,of_csv,bonus_csv):
        if not p.is_file(): raise FileNotFoundError(f"Entrada obligatoria ausente: {p}")
    orders,op_map,project_codes,hours_rows=select_of(hours,ct)
    missing_projects=project_codes-check_projects(projects)-{""}
    if missing_projects:raise ValueError(f"Proyectos ausentes del maestro: {sorted(missing_projects)}")
    if not op_map:raise ValueError("No hay bonos válidos para este centro")
    of_text=check_csv(of_csv,OF_HEADERS)
    bonus_text=check_csv(bonus_csv,BONUS_HEADERS)
    for label,actual,expected in (("OF",set(of_text),orders),
                                  ("bonos",set(bonus_text),set(op_map))):
        missing=sorted(expected-actual)
        extra=sorted(actual-expected)
        if missing or extra:
            raise ValueError(f"Cobertura {label} incorrecta: faltan {len(missing)} ({missing[:10]}), sobran {len(extra)} ({extra[:10]})")
    if prepared_zip and prepared_zip.is_file():
        with zipfile.ZipFile(prepared_zip) as z:
            manifest=json.loads(z.read("manifiesto.json"))
            if str(manifest["centro_trabajo"])!=str(ct):
                raise ValueError("Ct. del ZIP no coincide")
            if snapshot_date and manifest["snapshot_date"]!=snapshot_date:
                raise ValueError("Fecha del ZIP no coincide; vuelve a ejecutar pre_snapshot.ps1")
            hashes=manifest["source_files_sha256"]
            for p in (hours,projects):
                digest=hashlib.sha256(p.read_bytes()).hexdigest()
                if hashes.get(p.name)!=digest:
                    raise ValueError(f"{p.name}: ha cambiado desde pre_snapshot.ps1")
            if not {"indice_of.csv","indice_bonos.csv"}.issubset(z.namelist()):
                raise ValueError("El ZIP consolidado debe incluir ambos índices")
            idx_of=list(csv.DictReader(io.TextIOWrapper(z.open("indice_of.csv"),encoding="utf-8-sig"),delimiter=";"))
            idx_bonus=list(csv.DictReader(io.TextIOWrapper(z.open("indice_bonos.csv"),encoding="utf-8-sig"),delimiter=";"))
            if {r["order_number"] for r in idx_of}!=orders:
                raise ValueError("El índice OF consolidado difiere del ERP")
            if {r["Bono numero"] for r in idx_bonus}!=set(op_map):
                raise ValueError("El índice de bonos consolidado difiere del ERP")
    return ValidatedSnapshot(orders,set(op_map),project_codes,of_text,bonus_text,hours_rows)
