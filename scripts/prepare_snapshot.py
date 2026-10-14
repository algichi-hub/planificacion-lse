#!/usr/bin/env python3
"""Prepara un ZIP de expedientes OOFF para un Ct sin interpretar ni modificar Neon.

Lee los tres exports ERP y genera data/ooff_texto_consolidado.zip.
Solo conserva en el ZIP los JSON de las OF que aparecen en el Ct solicitado
según el fichero de horas; cada JSON conserva TODAS las líneas originales de esa OF.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from consolidar_ooff_texto import HEADERS, parse_line


def normalized_order(value: str) -> str:
    val = value.strip().lstrip('"').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', val):
        raise ValueError(f'Número de OF no válido: {value!r}')
    return val


def read_pipe(path: Path):
    with path.open('r', encoding='cp1252', newline='') as fd:
        reader = csv.reader(fd, delimiter='|')
        header = [v.strip() for v in next(reader)]
        yield header, None
        for n, row in enumerate(reader, start=2):
            yield n, dict(zip(header, (v.strip() for v in row)))


def select_of(hours: Path, ct: str):
    lines = read_pipe(hours)
    headers, _ = next(lines)
    required = {'Orden', 'Ct.', 'Proyec', 'Opr.'}
    if not required.issubset(headers):
        raise ValueError('Faltan columnas obligatorias en horas: '+repr(sorted(required-set(headers))))
    selected, operations, projects = set(), {}, set()
    hours_rows = 0
    for _, r in lines:
        if r.get('Ct.', '').strip() != ct:
            continue
        hours_rows += 1
        order = normalized_order(r['Orden'])
        selected.add(order)
        projects.add(r.get('Proyec', '').strip())
        operation = r.get('Opr.', '').strip()
        if operation:
            try:
                op = int(operation)
            except ValueError as exc:
                raise ValueError(f'Operación no numérica, OF {order}: {operation!r}') from exc
            if not 0 <= op <= 9999:
                raise ValueError(f'Operación fuera del rango de 4 dígitos, OF {order}: {op}')
            operations[f'{order}{op:04d}'] = (order, f'{op:04d}')
    if not selected:
        raise ValueError(f'No hay registros para Ct. {ct}')
    return selected, operations, projects, hours_rows


def check_projects(projects: Path):
    lines = read_pipe(projects)
    header, _ = next(lines)
    if not {'Proyecto', 'Descripción', 'Estatus'}.issubset(header):
        raise ValueError('El maestro de proyectos no tiene las columnas esperadas')
    return {r.get('Proyecto', '').strip() for _, r in lines if r.get('Proyecto', '').strip()}


def prepare(hours: Path, projects: Path, source: Path, output: Path, ct: str, snapshot_date: str):
    for p in (hours, projects, source):
        if not p.is_file():
            raise FileNotFoundError(str(p))
    if output.resolve() in {p.resolve() for p in (hours,projects,source)}:
        raise ValueError('La salida no puede sobrescribir ninguna entrada')
    selected, operations, project_codes, hours_rows = select_of(hours, ct)
    master_projects = check_projects(projects)
    missing_projects = sorted(project_codes - master_projects - {''})
    if missing_projects:
        raise ValueError(f'Proyectos de Ct. {ct} ausentes del maestro: {missing_projects[:20]}')
    grouped = defaultdict(list)
    issues = Counter()
    with zipfile.ZipFile(source) as z:
        members = [x for x in z.infolist() if not x.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith('.csv'):
            raise ValueError('El ZIP debe contener exactamente un fichero CSV')
        with z.open(members[0]) as fp:
            first = fp.readline().decode('cp1252')
            fp.seek(0)
            # Soporta tanto CSV tabular original como informe ERP paginado.
            # Un informe no contiene la cabecera de 14 campos del CSV plano.
            report_mode = first.lstrip().startswith('Fecha  :') and (
                'ÓRDENES DE FABRICACIÓN POR NÚMERO DE ORDEN' in first
                or 'ÓRDENES DE FABRICACIÓN' in first
            )
            if report_mode:
                issues['source_format_report'] = 1
                current_order = None
                current_fields = None
                for n, raw_bytes in enumerate(fp, 1):
                    raw = raw_bytes.decode('cp1252').rstrip('\r\n')
                    line = raw.rstrip(';')
                    # El export CSV envuelve entre comillas las líneas que
                    # contienen comillas literales y duplica dichas comillas.
                    if line.startswith('"') and line.endswith('"'):
                        line = line[1:-1].replace('""', '"')
                    stripped = line.strip()
                    if stripped.startswith('Fecha  :'):
                        if 'ÓRDENES DE FABRICACIÓN' not in stripped:
                            raise ValueError(f'Página ERP no reconocida: línea {n}')
                        continue
                    if (not stripped or stripped.startswith('Fábrica de Sevilla')
                        or stripped.startswith(('Orden |', 'fabrc.'))
                        or stripped.startswith('-------+')
                        or (stripped and set(stripped) == {'-'})):
                        continue
                    header = re.match(r'^\s*(\d{5,9})\|', line)
                    if header:
                        parts = line.split('|')
                        if len(parts) != 11:
                            raise ValueError(f'Cabecera de OF inválida en línea {n}')
                        current_order = normalized_order(parts[0])
                        current_fields = {field: '' for field in HEADERS}
                        current_fields.update({
                            'Orden': current_order,
                            'Articulo': parts[1].strip(),
                            'Descripcion': parts[2].strip(),
                            'Subpro': parts[8].strip(),
                            'Estado': parts[9].strip(),
                            'Bono': parts[10].strip(),
                        })
                        issues['report_order_headers'] += 1
                        report_text = ''
                    else:
                        if current_order is None:
                            raise ValueError(f'Línea de informe sin OF asociada: {n}')
                        # El contenido se preserva literalmente y se extrae
                        # además el texto visible para interpretación.
                        text_match = re.match(r'^\s{20,}\|(.*?)\|?\s*    missing = sorted(selected - set(grouped))
    # Una OF sin expediente de textos sigue siendo una OF válida del ERP.
    # Se genera un JSON vacío y marcado explícitamente para interpretación LLM.
    hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (hours,projects,source)}
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name+'.tmp')
    idx = io.StringIO()
    writer = csv.writer(idx, delimiter=';')
    writer.writerow(['order_number','source_rows','nonempty_text_rows','empty_text_rows','json_entry'])
    bono_idx = io.StringIO(newline='')
    bono_writer = csv.writer(bono_idx, delimiter=';', lineterminator='\r\n')
    bono_writer.writerow(['Bono numero', 'OF numero', 'POS numero'])
    for bonus_id in sorted(operations):
        order, pos = operations[bonus_id]
        bono_writer.writerow([bonus_id, order, pos])
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for order in sorted(selected):
                records = grouped[order]
                nonempty = sum(bool(x['fields']['Texto'].strip()) for x in records)
                entry = f'of/{order}.json'
                dossier = {'order_number':order,'source_file':members[0].filename,
                           'source_zip_sha256':hashes[source.name],
                           'source_rows_count':len(records),
                           'missing_in_ooff_texto': order in missing,
                           'missing_description_value': '### SIN DATOS ###' if order in missing else None,
                           'records':records}
                z.writestr(entry, json.dumps(dossier, ensure_ascii=False, separators=(',',':')))
                writer.writerow([order,len(records),nonempty,len(records)-nonempty,entry])
            manifest = {'purpose':'consolidacion_literal_sin_interpretacion',
                        'centro_trabajo':ct,'snapshot_date':snapshot_date,
                        'source_files_sha256':hashes,
                        'hours_records_selected':hours_rows,
                        'unique_of_selected':len(selected),
                        'unique_bonuses_selected':len(operations),
                        'source_lines_selected':issues['selected_source_lines'],
                        'selected_embedded_pipe_rows':issues['selected_embedded_pipes'],
                        'source_lines_total':issues['source_lines_total'],
                        'json_included':len(selected),'missing_of':missing,
                        'missing_of_count':len(missing),
                        'note':'Todas las OF seleccionadas tienen JSON. Si missing_in_ooff_texto es true, el LLM debe escribir exactamente ### SIN DATOS ### para la OF y sus bonos. POS de otros Ct. se preservan para dar contexto.'}
            z.writestr('indice_of.csv',idx.getvalue().encode('utf-8-sig'))
            z.writestr('indice_bonos.csv', bono_idx.getvalue().encode('utf-8-sig'))
            z.writestr('manifiesto.json',json.dumps(manifest, ensure_ascii=False,indent=2))
        with zipfile.ZipFile(temp) as z:
            if z.testzip() is not None: raise ValueError('ZIP generado incorrectamente')
            items=[n for n in z.namelist() if n.startswith('of/') and n.endswith('.json')]
            if len(items)!=len(selected): raise ValueError('Número de JSON inesperado')
            with z.open('indice_bonos.csv') as bonus_file:
                bonus_rows = list(csv.DictReader(
                    io.TextIOWrapper(bonus_file, encoding='utf-8-sig', newline=''),
                    delimiter=';'
                ))
            if len(bonus_rows) != len(operations):
                raise ValueError('El índice no contiene todos los bonos')
            indexed_bonuses = {row['Bono numero'] for row in bonus_rows}
            if indexed_bonuses != set(operations):
                raise ValueError('El índice de bonos no coincide con los registros de horas')
            if any(
                row['OF numero'] not in selected
                or row['Bono numero'] != row['OF numero'] + row['POS numero']
                or len(row['POS numero']) != 4
                for row in bonus_rows
            ):
                raise ValueError('Índice de bonos con claves inválidas')
            if sum(json.loads(z.read(name))['source_rows_count'] for name in items)!=issues['selected_source_lines']:
                raise ValueError('No se preservaron todas las líneas seleccionadas')
            for order in missing:
                dossier = json.loads(z.read(f'of/{order}.json'))
                if not dossier['missing_in_ooff_texto'] or dossier['records']:
                    raise ValueError(f'OF ausente mal representada: {order}')
        temp.replace(output)
    finally:
        if temp.exists(): temp.unlink()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ct', required=True)
    parser.add_argument('--hours',required=True,type=Path)
    parser.add_argument('--projects',required=True,type=Path)
    parser.add_argument('--ooff-texto',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--snapshot-date',required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.hours,args.projects,args.ooff_texto,args.output,args.ct,args.snapshot_date),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
, line)
                        report_text = text_match.group(1).rstrip().rstrip('|').strip() if text_match else ''
                    issues['source_lines_total'] += 1
                    if current_order not in selected:
                        continue
                    issues['selected_source_lines'] += 1
                    fields = dict(current_fields)
                    fields['Texto'] = report_text
                    grouped[current_order].append({
                        'source_line_number': n,
                        'source_raw_line': raw,
                        'source_order_field': current_order,
                        'fields': fields,
                        'embedded_pipe_in_text': False,
                        'source_format': 'erp_paged_report',
                    })
            else:
                for n, raw_bytes in enumerate(fp, 1):
                    raw = raw_bytes.decode('cp1252')
                    values, extra = parse_line(raw)
                    if n == 1:
                        if tuple(v.strip().rstrip(';') for v in values) != HEADERS:
                            raise ValueError('Cabecera inesperada en ooff_texto.zip')
                        continue
                    issues['source_lines_total'] += 1
                    order = normalized_order(values[0])
                    if order not in selected:
                        continue
                    issues['selected_source_lines'] += 1
                    if extra: issues['selected_embedded_pipes'] += 1
                    grouped[order].append({
                        'source_line_number': n,
                        'source_raw_line': raw.rstrip('\r\n'),
                        'source_order_field': values[0],
                        'fields': dict(zip(HEADERS, values)),
                        'embedded_pipe_in_text': extra
                    })
    missing = sorted(selected - set(grouped))
    # Una OF sin expediente de textos sigue siendo una OF válida del ERP.
    # Se genera un JSON vacío y marcado explícitamente para interpretación LLM.
    hashes = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (hours,projects,source)}
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name+'.tmp')
    idx = io.StringIO()
    writer = csv.writer(idx, delimiter=';')
    writer.writerow(['order_number','source_rows','nonempty_text_rows','empty_text_rows','json_entry'])
    bono_idx = io.StringIO(newline='')
    bono_writer = csv.writer(bono_idx, delimiter=';', lineterminator='\r\n')
    bono_writer.writerow(['Bono numero', 'OF numero', 'POS numero'])
    for bonus_id in sorted(operations):
        order, pos = operations[bonus_id]
        bono_writer.writerow([bonus_id, order, pos])
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for order in sorted(selected):
                records = grouped[order]
                nonempty = sum(bool(x['fields']['Texto'].strip()) for x in records)
                entry = f'of/{order}.json'
                dossier = {'order_number':order,'source_file':members[0].filename,
                           'source_zip_sha256':hashes[source.name],
                           'source_rows_count':len(records),
                           'missing_in_ooff_texto': order in missing,
                           'missing_description_value': '### SIN DATOS ###' if order in missing else None,
                           'records':records}
                z.writestr(entry, json.dumps(dossier, ensure_ascii=False, separators=(',',':')))
                writer.writerow([order,len(records),nonempty,len(records)-nonempty,entry])
            manifest = {'purpose':'consolidacion_literal_sin_interpretacion',
                        'centro_trabajo':ct,'snapshot_date':snapshot_date,
                        'source_files_sha256':hashes,
                        'hours_records_selected':hours_rows,
                        'unique_of_selected':len(selected),
                        'unique_bonuses_selected':len(operations),
                        'source_lines_selected':issues['selected_source_lines'],
                        'selected_embedded_pipe_rows':issues['selected_embedded_pipes'],
                        'source_lines_total':issues['source_lines_total'],
                        'json_included':len(selected),'missing_of':missing,
                        'missing_of_count':len(missing),
                        'note':'Todas las OF seleccionadas tienen JSON. Si missing_in_ooff_texto es true, el LLM debe escribir exactamente ### SIN DATOS ### para la OF y sus bonos. POS de otros Ct. se preservan para dar contexto.'}
            z.writestr('indice_of.csv',idx.getvalue().encode('utf-8-sig'))
            z.writestr('indice_bonos.csv', bono_idx.getvalue().encode('utf-8-sig'))
            z.writestr('manifiesto.json',json.dumps(manifest, ensure_ascii=False,indent=2))
        with zipfile.ZipFile(temp) as z:
            if z.testzip() is not None: raise ValueError('ZIP generado incorrectamente')
            items=[n for n in z.namelist() if n.startswith('of/') and n.endswith('.json')]
            if len(items)!=len(selected): raise ValueError('Número de JSON inesperado')
            with z.open('indice_bonos.csv') as bonus_file:
                bonus_rows = list(csv.DictReader(
                    io.TextIOWrapper(bonus_file, encoding='utf-8-sig', newline=''),
                    delimiter=';'
                ))
            if len(bonus_rows) != len(operations):
                raise ValueError('El índice no contiene todos los bonos')
            indexed_bonuses = {row['Bono numero'] for row in bonus_rows}
            if indexed_bonuses != set(operations):
                raise ValueError('El índice de bonos no coincide con los registros de horas')
            if any(
                row['OF numero'] not in selected
                or row['Bono numero'] != row['OF numero'] + row['POS numero']
                or len(row['POS numero']) != 4
                for row in bonus_rows
            ):
                raise ValueError('Índice de bonos con claves inválidas')
            if sum(json.loads(z.read(name))['source_rows_count'] for name in items)!=issues['selected_source_lines']:
                raise ValueError('No se preservaron todas las líneas seleccionadas')
            for order in missing:
                dossier = json.loads(z.read(f'of/{order}.json'))
                if not dossier['missing_in_ooff_texto'] or dossier['records']:
                    raise ValueError(f'OF ausente mal representada: {order}')
        temp.replace(output)
    finally:
        if temp.exists(): temp.unlink()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ct', required=True)
    parser.add_argument('--hours',required=True,type=Path)
    parser.add_argument('--projects',required=True,type=Path)
    parser.add_argument('--ooff-texto',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--snapshot-date',required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.hours,args.projects,args.ooff_texto,args.output,args.ct,args.snapshot_date),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
