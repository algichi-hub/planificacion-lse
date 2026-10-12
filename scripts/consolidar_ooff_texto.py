#!/usr/bin/env python3
"""Consolida exportación ERP OOFF en un JSON por OF, sin interpretación."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import defaultdict, Counter
from pathlib import Path

HEADERS = ("Orden", "Articulo", "Descripcion", "Subpro", "Estado", "Revis.",
           "Cant.Pedida", "Texto", "Bono", "Materiales", "Fech. Lanzamiento",
           "Fec. 1º Outbound", "Fec. Termin.", "Fec. Cierre")

def parse_line(raw: str) -> tuple[list[str], bool]:
    left = raw.rstrip("\r\n").split("|", 7)
    if len(left) != 8:
        raise ValueError("columnas anteriores a Texto insuficientes")
    right = left[7].rsplit("|", 6)
    if len(right) != 7:
        raise ValueError("columnas posteriores a Texto insuficientes")
    values = left[:7] + right
    return values, raw.count("|") > 13

def consolidate(input_path: Path, output_path: Path) -> dict:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Entrada y salida no pueden ser iguales")
    by_order = defaultdict(list)
    counts = Counter()
    input_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    with zipfile.ZipFile(input_path) as source:
        members = [m for m in source.infolist() if not m.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith('.csv'):
            raise ValueError("Se espera un ZIP con un único CSV")
        csv_member = members[0].filename
        with source.open(members[0]) as stream:
            for physical_line, data in enumerate(stream, 1):
                raw = data.decode("cp1252")
                values, extra = parse_line(raw)
                if physical_line == 1:
                    if tuple(v.strip().rstrip(';') for v in values) != HEADERS:
                        raise ValueError("Cabecera inesperada: se detiene sin generar salida")
                    continue
                counts['source_rows'] += 1
                order_original = values[0]
                order = order_original.strip().lstrip('"').strip()
                if order != order_original.strip(): counts['normalized_order_rows'] += 1
                if not order:
                    raise ValueError(f"Fila {physical_line}: Orden vacía")
                if '/' in order or '\\' in order or '..' in order or not re.fullmatch(r'[A-Za-z0-9_-]+', order):
                    raise ValueError(f"Fila {physical_line}: Orden no válida para nombre de archivo: {order!r}")
                if extra: counts['embedded_pipes_in_text_rows'] += 1
                by_order[order].append({
                    "source_line_number": physical_line,
                    "source_raw_line": raw.rstrip("\r\n"),
                    "source_order_field": order_original,
                    "fields": dict(zip(HEADERS, values)),
                    "embedded_pipe_in_text": extra,
                })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    index_buffer = io.StringIO()
    writer = csv.writer(index_buffer, delimiter=';')
    writer.writerow(["order_number", "source_rows", "nonempty_text_rows", "empty_text_rows", "json_entry"])
    total_rewritten = 0
    with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as dest:
        for order in sorted(by_order):
            records = by_order[order]
            entry = f"of/{order}.json"
            obj = {
                "order_number": order, "source_file": csv_member,
                "source_zip_sha256": input_hash,
                "source_rows_count": len(records), "records": records,
            }
            dest.writestr(entry, json.dumps(obj, ensure_ascii=False, separators=(',', ':')))
            nonempty = sum(bool(row['fields']['Texto'].strip()) for row in records)
            writer.writerow([order,len(records),nonempty,len(records)-nonempty,entry])
            total_rewritten += len(records)
        dest.writestr('indice_of.csv', index_buffer.getvalue().encode('utf-8-sig'))
        report = {
            "purpose": "consolidacion_literal_sin_inferencia_ni_descripciones",
            "source_zip": input_path.name, "source_csv_member": csv_member,
            "source_zip_sha256": input_hash, "distinct_orders": len(by_order),
            "source_rows": counts['source_rows'], "rows_preserved": total_rewritten,
            "rows_with_embedded_pipes": counts['embedded_pipes_in_text_rows'],
            "rows_with_normalized_order": counts['normalized_order_rows'],
            "one_json_per_order": True, "encoding_of_json": "utf-8",
            "raw_source_line_preserved": True,
            "note": "Los campos se mantienen literales. El dictamen corresponde al LLM.",
        }
        dest.writestr('manifiesto.json', json.dumps(report, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(output_path) as z:
        names=z.namelist()
        actual=[n for n in names if n.startswith('of/') and n.endswith('.json')]
        if len(actual)!=len(by_order): raise AssertionError('OF JSON faltantes')
        for name in actual:
            obj=json.loads(z.read(name))
            if obj['source_rows_count']!=len(obj['records']): raise AssertionError(name)
        if total_rewritten!=counts['source_rows']: raise AssertionError('Se han perdido líneas')
        if z.testzip() is not None: raise AssertionError('ZIP corrupto')
    return report

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', required=True, type=Path)
    ap.add_argument('--output', default=Path('ooff_texto_consolidado.zip'), type=Path)
    args=ap.parse_args()
    print(json.dumps(consolidate(args.input,args.output),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
