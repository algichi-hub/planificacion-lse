# Guía operativa — preparación y carga de snapshots

Sistema **Planificación LSE**. Ejecutar en Windows PowerShell desde la raíz del repositorio, con Python y dependencias del proyecto instaladas.

**Prompt maestro para interpretar los expedientes:** [LLM_ERP_PROMPT.md](LLM_ERP_PROMPT.md). Emplear siempre su versión vigente con el ZIP generado por `pre_snapshot.ps1`.

## Resumen del proceso

1. Exportar los tres ficheros ERP a `data/`.
2. Preparar expedientes mediante `pre_snapshot.ps1 -Ct 422`. **No escribe en Neon**.
3. Interpretar el ZIP resultante con el agente LLM, generando los dos CSV de descripciones.
4. Guardar los CSV interpretados en `data/`.
5. Ejecutar `load_snapshot.ps1 -Ct 422 -ValidateOnly`. **Sin conexión ni escritura en Neon**.
6. Revisar el resultado y solo entonces ejecutar `load_snapshot.ps1 -Ct 422`. **Este paso escribe en Neon**.

`-Ct 422` es un ejemplo; utilizar el centro deseado. La fecha de snapshot es opcional y se toma del día actual del sistema, salvo que se indique `-SnapshotDate`.

## Archivos de entrada / salida

| Archivo | Uso |
|---|---|
| `data/OOFF_OP_Planif_Terminada.txt` | ERP horas; permite filtrar operaciones por `Ct.` y formar bonos |
| `data/Proyectos_Sevilla.csv` | Maestro de proyectos |
| `data/ooff_texto.csv` | Textos internos originales del ERP (solo preparación) |

El CSV de textos sin comprimir acepta **dos formatos de exportación ERP**: el CSV tabular con cabeceras `Orden|Articulo|...|Texto|...`, y el informe paginado `ÓRDENES DE FABRICACIÓN POR NÚMERO DE ORDEN` con textos multilínea en recuadros. El preparador lee directamente el CSV y detecta el formato y conserva las líneas de los expedientes seleccionados; no intenta aplicar `parse_line` de 14 columnas al informe paginado. Los formatos no reconocidos siguen siendo errores, y las OF sin correspondencia se marcan `### SIN DATOS ###`.
| `data/ooff_texto_consolidado.zip` | Salida de preparación; JSON por OF, manifiesto, `indice_of.csv` e `indice_bonos.csv` |
| `data/ooff_texto_interpretado.csv` | Salida LLM, obligatoria para carga |
| `data/bono_texto_interpretado.csv` | Salida LLM, obligatoria para carga |

Los archivos `data/*.zip`, `data/*.csv` y `data/*.txt` se excluyen del repositorio mediante `.gitignore`.

## 1. Preparación: pre_snapshot.ps1

El fichero de textos original se guarda **sin comprimir**, con nombre `data/ooff_texto.csv`. No es necesario crear un ZIP. La salida para el agente LLM **sí** sigue siendo `data/ooff_texto_consolidado.zip`. Para comprobar sintaxis antes de ejecutar: `python -m py_compile .\scripts\prepare_snapshot.py`.


```powershell
.\scripts\pre_snapshot.ps1 -Help
.\scripts\pre_snapshot.ps1 -Ct 422
```

Parámetros:

| Parámetro | Valor predeterminado | Uso |
|---|---|---|
| `-Ct` | Obligatorio | Centro de trabajo a seleccionar |
| `-SnapshotDate` | Fecha Windows (yyyy-MM-dd) | Fecha indicada en el manifiesto |
| `-HoursFile` | `data/OOFF_OP_Planif_Terminada.txt` | Export de horas |
| `-ProjectsFile` | `data/Proyectos_Sevilla.csv` | Maestro |
| `-OoffTextoFile` | `data/ooff_texto.csv` | Texto ERP original |
| `-OutputFile` | `data/ooff_texto_consolidado.zip` | ZIP destino |
| `-Help` | — | Muestra la ayuda sin procesar datos |

Ejemplo de fecha explícita:

```powershell
.\scripts\pre_snapshot.ps1 -Ct 422 -SnapshotDate "2026-10-12"
```

El script selecciona las OF que tengan registros de horas en el Ct elegido, pero conserva **todas las líneas textuales** de cada OF para que el modelo pueda interpretar su contexto, incluyendo operaciones de otros Ct. El ZIP integra el inventario autoritativo de bonos reales del Ct (`indice_bonos.csv`). No asigna ni interpreta descripciones y no utiliza credenciales de Neon.

**OF ausentes del ZIP de textos:** no se detiene el proceso. Se genera un JSON por cada OF seleccionada, aunque falte en `ooff_texto.csv`, con `records: []`, `missing_in_ooff_texto: true` y `missing_description_value: "### SIN DATOS ###"`. El manifiesto enumera esas OF en `missing_of`. Una ausencia individual no equivale a un ZIP corrupto; los errores de estructura que impiden interpretar las claves siguen siendo bloqueantes.

## 2. Interpretación LLM

Adjuntar `ooff_texto_consolidado.zip` al agente de interpretación. El resultado **debe incluir exactamente**:

`ooff_texto_interpretado.csv`: columnas `OF numero;of_detailed_description`.

`bono_texto_interpretado.csv`: columnas `Bono numero;bo_detailed_description`.

Especificación: UTF-8 con BOM, separador `;`, saltos CRLF, identificadores como texto, una fila por clave de los inventarios, ninguna descripción nula; usar exactamente `Vacío` si no hay texto y `Pendiente confirmar` si el contexto es insuficiente/ambiguo/contradictorio. No inventar bonos a partir de menciones `POS`.

**Regla prioritaria para el LLM:** cuando `missing_in_ooff_texto: true`, escribir exactamente `### SIN DATOS ###` como descripción de esa OF y de todos sus bonos presentes en `indice_bonos.csv`. Reservar `Vacío` para expedientes presentes sin contenido descriptivo, y `Pendiente confirmar` para contenido presente pero insuficiente, ambiguo, contradictorio o corrupto. No sustituir el marcador por una descripción genérica del ERP.

Los resultados del LLM se revisan antes de cargar; la validación automatizada garantiza estructura, cobertura y coherencia de IDs, **no** la verdad técnica de cada descripción.

## 3. Gate de validación: load_snapshot.ps1

```powershell
.\scripts\load_snapshot.ps1 -Help
.\scripts\load_snapshot.ps1 -Ct 422 -ValidateOnly
```

Parámetros:

| Parámetro | Valor predeterminado | Uso |
|---|---|---|
| `-Ct` | Obligatorio | Centro cuyas horas se importarán |
| `-SnapshotDate` | Fecha Windows (yyyy-MM-dd) | Fecha del snapshot |
| `-HoursFile` | `data/OOFF_OP_Planif_Terminada.txt` | Export ERP de horas |
| `-ProjectsFile` | `data/Proyectos_Sevilla.csv` | Maestro ERP |
| `-OfTextFile` | `data/ooff_texto_interpretado.csv` | Interpretación OF |
| `-BonusTextFile` | `data/bono_texto_interpretado.csv` | Interpretación bonos |
| `-PreparedZip` | `data/ooff_texto_consolidado.zip` | ZIP preparado; usado para verificar índices, centro, fecha y hashes si existe |
| `-ValidateOnly` | Desactivado | Validación local sin escritura ni conexión a Neon |
| `-Help` | — | Ayuda sin conexión ni escritura |

El proceso valida los cuatro ficheros obligatorios, cabeceras, formato CSV, descripciones no vacías, claves únicas y cobertura exacta de OF y bonos del centro. Si el ZIP preparado está disponible, se compara su manifiesto, índices, hashes de horas y proyectos y fecha de preparación. Ante un fallo, la carga no se inicia.

**Importante:** aunque la fecha tiene valor predeterminado, si se preparó el ZIP otro día y se ejecuta la carga más tarde, indicar a ambos scripts la **misma fecha** con `-SnapshotDate`, o regenerar el ZIP antes de validar.

## 4. Carga real: escribe en Neon

**Solo cuando el Gate anterior haya pasado y el usuario haya autorizado la carga:**

```powershell
# DATABASE_URL debe estar configurada en la sesión PowerShell.
.\scripts\load_snapshot.ps1 -Ct 422
```

El script filtra las filas de horas por Ct, inserta sus proyectos y las descripciones de OF y bonos por fecha en PostgreSQL/Neon. Utiliza una transacción: si se produce un fallo SQL se revierte la operación. Repetir una fecha reemplaza sus filas de horas y descripciones para ese snapshot: **no usar para sobrescribir una fecha histórica sin revisar el alcance**.

No compartir nunca `DATABASE_URL` ni otras credenciales.

## 5. Solución de incidencias

- **Archivo ausente:** confirmar los nombres exactos en `data/` y ejecutar de nuevo `-ValidateOnly`.
- **Falta una OF o bono:** regenerar el ZIP con `pre_snapshot.ps1`, volver a interpretar y revisar los CSV.
- **Error de fecha:** alinear `-SnapshotDate` de preparación y carga.
- **Hash de origen distinto:** uno de los exportes cambió; repetir preparación e interpretación.
- **Error de codificación:** exportar CSV con UTF-8 BOM, `;` y CRLF.
- **Sin `DATABASE_URL`:** `-ValidateOnly` no necesita credenciales; la carga real sí.
- **Duda sobre la descripción:** usar `Pendiente confirmar` y revisar el expediente, nunca suplir información por intuición.

## 6. Ejecución típica completa

```powershell
cd C:\Users\algic\Projects\planificacion-lse
git pull --ff-only origin v0/sql-dashboard

.\scripts\pre_snapshot.ps1 -Ct 422
# Adjuntar data/ooff_texto_consolidado.zip al agente y guardar ambos CSV en data/
.\scripts\load_snapshot.ps1 -Ct 422 -ValidateOnly
# Después de revisar y autorizar:
.\scripts\load_snapshot.ps1 -Ct 422
```

Consultar `-Help` en cualquiera de los scripts para ver sus parámetros en la terminal.

## 7. Retirada segura de un Ct y fecha de Neon

La utilidad independiente `scripts/delete_snapshot.ps1` elimina las filas de `fact_hours` de un único Ct y fecha mediante transacción, y retira las descripciones de OF/bonos vinculadas exclusivamente a ese Ct. **Por defecto es una simulación sin escrituras.**

```powershell
# 1. Vista previa obligatoria en la práctica
.\scripts\delete_snapshot.ps1 -Ct 422 -SnapshotDate "2026-10-15"

# 2. Borrado REAL, solo si la vista previa es correcta y está autorizado
.\scripts\delete_snapshot.ps1 -Ct 422 -SnapshotDate "2026-10-15" -Execute -Confirm "ELIMINAR:422:2026-10-15"
```

**Precauciones:** requiere `DATABASE_URL`. La herramienta no modifica tablas SQL, vistas, índices ni otros snapshots. No borra proyectos maestros, porque son globales y pueden pertenecer a otras fechas o Ct. `imports` carece de columna Ct: sus filas de esa fecha se borran **solo cuando ya no existían horas de otros Ct en la fecha antes del borrado**; de lo contrario se conservan como metadatos compartidos. Del mismo modo, una OF o bono que figure en otro Ct de esa fecha mantiene su descripción.

**Limitaciones importantes:** el sistema actual guarda las descripciones con clave `(snapshot_date, OF)` o `(snapshot_date, bono)`, y las importaciones con `(snapshot_date, source_name)`. No se pueden eliminar selectivamente esas filas por Ct cuando son compartidas. Para una trazabilidad estricta multicentro deberá ampliarse el esquema e importador. La herramienta no garantiza exclusión frente a un proceso de importación concurrente; no ejecutar carga y borrado simultáneamente. Las ramas de respaldo/PITR de Neon no se purgan.

Tras el borrado, repetir una carga con `load_snapshot.ps1` requiere igualmente precaución: el importador actual sustituye horas y descripciones de la **fecha completa**, sin filtrar por Ct. No está corregido por esta utilidad.
