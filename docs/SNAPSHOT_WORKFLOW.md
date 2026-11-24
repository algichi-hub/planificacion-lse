# Guía operativa — preparación y carga de snapshots

Sistema **Planificación LSE**. Ejecutar en Windows PowerShell desde la raíz del repositorio, con Python y dependencias del proyecto instaladas.

**Prompt maestro para interpretar los expedientes:** [LLM_ERP_PROMPT.md](LLM_ERP_PROMPT.md). Emplear siempre su versión vigente con el ZIP generado por `pre_snapshot.ps1`.

> **Desarrollo `feature/closed-of-importer` — importador desde ZIP AES-256.** Los cuatro ERP originales se extraen a `data/`; los dos CSV interpretados permanecen en la misma carpeta. La preparación `pre_snapshot.ps1 -Ct 422` genera `data/ooff_texto_consolidado.zip`. El ZIP incluye los índices originales y los auxiliares `indice_bono_ct.csv` e `indice_of_cerradas.csv`. `load_snapshot.ps1 -Ct 422 -ValidateOnly` valida los seis ficheros, la fecha, los cuatro hashes y las coberturas **sin acceder a Neon**. Sin `-ValidateOnly`, la conexión debe apuntar exactamente a la rama Neon `development` (`br-blue-firefly-b1adfx47`), y toda la carga se ejecuta en una transacción. `main` y Neon `production` no se modifican.
>
> Las horas finales de OF cerradas se almacenan una sola vez por OF en `closed_of_hours`, con cuatro decimales. Las OF sin CT histórico o con más de un CT quedan sin atribución hasta su revisión, y las vistas existentes del tablero siguen consultando `fact_hours`: **los cierres aún no se suman al dashboard**. El registro histórico `bonus_ct_registry` se actualiza incrementalmente y rechaza conflictos sin sobrescribir CT existentes.

**Ejecución en Windows (rama de desarrollo):**

```powershell
cd C:\\Users\\algic\\Projects\\planificacion-lse
git pull --ff-only origin feature/closed-of-importer
python -m unittest discover -s tests -p test_pre_snapshot_closed.py -v
python -m unittest discover -s tests -p test_load_snapshot_gate.py -v
.\\scripts\\pre_snapshot.ps1 -Ct 422
.\\scripts\\load_snapshot.ps1 -Ct 422 -ValidateOnly
# SOLO con LSE_DATABASE_URL apuntando a Neon development y tras validar:
.\\scripts\\load_snapshot.ps1 -Ct 422
```

**Aviso de seguridad:** La conexión configurada como `DATABASE_URL` en los secretos de Streamlit no modifica `LSE_DATABASE_URL` en PowerShell. El cargador comprueba `current_setting('neon.branch_id', true)` antes de cualquier escritura y rechaza ramas distintas de `development`.

## OF cerradas en los informes (development)

- La atribución manual aprobada de las OF `967341` y `967342` se conserva en `closed_of_manual_assignments` con proyecto `PZ7CUR` y centro `422`. El maestro del proyecto procede del ERP y su grupo/director es `500084 PIZARRO 7ª MODIFICACION`.
- `v_reporting_of_hours` agrega operaciones a nivel OF y añade cada OF cerrada **una sola vez**. `v_project_hours` y `v_order_hours` reutilizan la vista. El total conocido del 21/11/2026 es **3.000,6518 horas** de dos OF, sin atribución a bonos.
- Home, EAC y el indicador de incurridas ERP de POE leen esta fuente de nivel OF. **Riesgos y el detalle de bonos siguen leyendo exclusivamente `fact_hours`**. Para las OF cerradas, las concedidas de reporting se igualan al incurrido definitivo de la OF, el pendiente es 0 y el consumo 100 % si el total es positivo. Las horas por bono cerrado continúan desconocidas y no se reparten.
- La asignación manual se vuelve a aplicar en futuras cargas y la importación se bloquea si nuevos bonos ERP contradicen un centro asignado manualmente. Se bloquean también las OF simultáneamente operativas/cerradas en un snapshot y las reaperturas sin conciliación para evitar perder horas o presentar un estado ambiguo. No modifica snapshots anteriores.
- La visualización y exportación siguen el formato decimal de la aplicación; la precisión numérica del cierre en Neon es `NUMERIC(18,4)`.
- La aplicación de producción permanece en `main` y no debe apuntar a esta base `development` mientras se verifica el cambio.

## Entrada cifrada ZIP AES-256 (flujo vigente de esta rama)

Todos los archivos se gestionan bajo `data/`; no se utiliza `entrada/`.

La única fuente ERP que se entrega manualmente es `data/planificacion-lse.zip`, con **exactamente** estos cuatro ficheros en la raíz: `OOFF_OP_Planif_Terminada.txt`, `OOFFCerradasMO.txt`, `Proyectos_Sevilla.csv` y `ooff_texto.csv`.

**Requisitos:** 7-Zip instalado en Windows; variable de entorno `LSE_ZIP_PASSWORD` configurada en la sesión o permanentemente. Nunca escribir la contraseña en archivos, argumentos PowerShell ni en Git.

`pre_snapshot.ps1` llama a `scripts/prepare_input_zip.py` y comprueba la estructura AES del ZIP, ejecuta `7z t` para validar contenido cifrado y `7z x` en una carpeta temporal de `data/`. Solo si las cuatro extracciones son correctas, las mueve a `data/`; conserva las copias originales si falla. Cuando el ZIP no ha cambiado y los hashes extraídos coinciden, evita una nueva extracción. Se crea el manifiesto local ignorado por Git `data/.planificacion_lse_zip_state.json`.

`load_snapshot.ps1` valida **hashes de ZIP y de los cuatro archivos extraídos** mediante `--check-only`; no ejecuta 7-Zip ni sustituye ficheros. Un cambio del ZIP obliga a repetir `pre_snapshot.ps1`, regenerar el ZIP consolidado de textos y la interpretación correspondiente. Los dos CSV interpretados y `data/ooff_texto_consolidado.zip` se mantienen en la misma carpeta.

```powershell
.\\scripts\\pre_snapshot.ps1 -Ct 422 -SnapshotDate "2026-11-30"
.\\scripts\\load_snapshot.ps1 -Ct 422 -SnapshotDate "2026-11-30" -ValidateOnly
```

La extracción del ZIP no escribe en Neon. `-ValidateOnly` sigue sin establecer conexión con la base de datos. Para pruebas de extracción sin preparar ZIP de interpretación, utilizar `python scripts/prepare_input_zip.py --zip data/planificacion-lse.zip --data-dir data`.

**Seguridad:** 7-Zip recibe la contraseña por argumento del proceso hijo (`-p...`); no se registra ni se imprime, pero puede aparecer temporalmente en herramientas del sistema que inspeccionen las líneas de comandos de procesos. Restringir el acceso al equipo durante la extracción.

## Resumen del proceso

1. Exportar los cuatro ficheros ERP a `entrada/`.
2. Preparar expedientes mediante `pre_snapshot.ps1 -Ct 422`. **No escribe en Neon**.
3. Interpretar el ZIP resultante con el agente LLM, generando los dos CSV de descripciones.
4. Guardar los CSV interpretados en `entrada/`.
5. Ejecutar `load_snapshot.ps1 -Ct 422 -ValidateOnly`. **Sin conexión ni escritura en Neon**.
6. Revisar el resultado y solo entonces ejecutar `load_snapshot.ps1 -Ct 422`. **Este paso escribe en Neon**.

`-Ct 422` es un ejemplo; utilizar el centro deseado. La fecha de snapshot es opcional y se toma del día actual del sistema, salvo que se indique `-SnapshotDate`.

## Archivos de entrada / salida

| Archivo | Uso |
|---|---|
| `entrada/OOFF_OP_Planif_Terminada.txt` | ERP horas; permite filtrar operaciones por `Ct.` y formar bonos |
| `entrada/Proyectos_Sevilla.csv` | Maestro de proyectos |
| `entrada/ooff_texto.csv` | Textos internos originales del ERP (solo preparación) |
| `entrada/OOFFCerradasMO.txt` | OF cerradas y horas totales incurridas |

El CSV de textos sin comprimir acepta **dos formatos de exportación ERP**: el CSV tabular con cabeceras `Orden|Articulo|...|Texto|...`, y el informe paginado `ÓRDENES DE FABRICACIÓN POR NÚMERO DE ORDEN` con textos multilínea en recuadros. El preparador lee directamente el CSV y detecta el formato y conserva las líneas de los expedientes seleccionados; no intenta aplicar `parse_line` de 14 columnas al informe paginado. Los formatos no reconocidos siguen siendo errores, y las OF sin correspondencia se marcan `### SIN DATOS ###`.
| `data/ooff_texto_consolidado.zip` | Salida de preparación; JSON por OF, manifiesto, `indice_of.csv` e `indice_bonos.csv` |
| `entrada/ooff_texto_interpretado.csv` | Salida LLM, obligatoria para carga |
| `entrada/bono_texto_interpretado.csv` | Salida LLM, obligatoria para carga |

Los archivos `data/*.zip`, `data/*.csv` y `data/*.txt` se excluyen del repositorio mediante `.gitignore`.

## 1. Preparación: pre_snapshot.ps1

El fichero de textos original se guarda **sin comprimir**, con nombre `entrada/ooff_texto.csv`. No es necesario crear un ZIP. La salida para el agente LLM **sí** sigue siendo `data/ooff_texto_consolidado.zip`. Para comprobar sintaxis antes de ejecutar: `python -m py_compile .\scripts\prepare_snapshot.py`.


```powershell
.\scripts\pre_snapshot.ps1 -Help
.\scripts\pre_snapshot.ps1 -Ct 422
```

Parámetros:

| Parámetro | Valor predeterminado | Uso |
|---|---|---|
| `-Ct` | Obligatorio | Centro de trabajo a seleccionar |
| `-SnapshotDate` | Fecha Windows (yyyy-MM-dd) | Fecha indicada en el manifiesto |
| `-HoursFile` | `entrada/OOFF_OP_Planif_Terminada.txt` | Export de horas |
| `-ProjectsFile` | `entrada/Proyectos_Sevilla.csv` | Maestro |
| `-OoffTextoFile` | `entrada/ooff_texto.csv` | Texto ERP original |
| `-ClosedFile` | `entrada/OOFFCerradasMO.txt` | OF cerradas |
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
| `-HoursFile` | `entrada/OOFF_OP_Planif_Terminada.txt` | Export ERP de horas |
| `-ProjectsFile` | `entrada/Proyectos_Sevilla.csv` | Maestro ERP |
| `-OfTextFile` | `entrada/ooff_texto_interpretado.csv` | Interpretación OF |
| `-BonusTextFile` | `entrada/bono_texto_interpretado.csv` | Interpretación bonos |
| `-PreparedZip` | `data/ooff_texto_consolidado.zip` | ZIP preparado; usado para verificar índices, centro, fecha y hashes si existe |
| `-ValidateOnly` | Desactivado | Validación local sin escritura ni conexión a Neon |
| `-Help` | — | Ayuda sin conexión ni escritura |

El proceso valida los seis ficheros obligatorios, cabeceras, formato CSV, descripciones no vacías, claves únicas y cobertura exacta de OF y bonos del centro. Si el ZIP preparado está disponible, se compara su manifiesto, índices, hashes de horas y proyectos y fecha de preparación. Ante un fallo, la carga no se inicia.

**Importante:** aunque la fecha tiene valor predeterminado, si se preparó el ZIP otro día y se ejecuta la carga más tarde, indicar a ambos scripts la **misma fecha** con `-SnapshotDate`, o regenerar el ZIP antes de validar.

## 4. Carga real: escribe en Neon

**Solo cuando el Gate anterior haya pasado y el usuario haya autorizado la carga:**

```powershell
# LSE_DATABASE_URL debe estar configurada en la sesión PowerShell.
.\scripts\load_snapshot.ps1 -Ct 422
```

El script filtra las filas de horas por Ct, inserta sus proyectos y las descripciones de OF y bonos por fecha en PostgreSQL/Neon. Utiliza una transacción: si se produce un fallo SQL se revierte la operación. Repetir una fecha reemplaza sus filas de horas y descripciones para ese snapshot: **no usar para sobrescribir una fecha histórica sin revisar el alcance**.

No compartir nunca `LSE_DATABASE_URL` ni otras credenciales.

## 5. Solución de incidencias

- **Archivo ausente:** confirmar los nombres exactos en `data/` y ejecutar de nuevo `-ValidateOnly`.
- **Falta una OF o bono:** regenerar el ZIP con `pre_snapshot.ps1`, volver a interpretar y revisar los CSV.
- **Error de fecha:** alinear `-SnapshotDate` de preparación y carga.
- **Hash de origen distinto:** uno de los exportes cambió; repetir preparación e interpretación.
- **Error de codificación:** exportar CSV con UTF-8 BOM, `;` y CRLF.
- **Sin `LSE_DATABASE_URL`:** `-ValidateOnly` no necesita credenciales; la carga real sí.
- **Duda sobre la descripción:** usar `Pendiente confirmar` y revisar el expediente, nunca suplir información por intuición.

## 6. Ejecución típica completa

```powershell
cd C:\Users\algic\Projects\planificacion-lse
git pull --ff-only origin feature/closed-of-importer

.\scripts\pre_snapshot.ps1 -Ct 422
# Adjuntar data/ooff_texto_consolidado.zip al agente y guardar ambos CSV en data/
.\scripts\load_snapshot.ps1 -Ct 422 -ValidateOnly
# Después de revisar y autorizar:
.\scripts\load_snapshot.ps1 -Ct 422
```

Consultar `-Help` en cualquiera de los scripts para ver sus parámetros en la terminal.

## 7. Retirada segura de un Ct y fecha de Neon

La utilidad independiente `scripts/delete_snapshot.ps1` elimina las filas de `fact_hours` de un único Ct y fecha mediante transacción, y retira las descripciones de OF/bonos vinculadas exclusivamente a ese Ct. **La simulación requiere `-ValidateOnly`; el borrado real requiere los switches `-Execute -Confirm`. Sin un modo explícito, se rechaza la ejecución.**

```powershell
# 1. Vista previa obligatoria en la práctica
.\scripts\delete_snapshot.ps1 -Ct 422 -SnapshotDate "2026-10-15" -ValidateOnly

# 2. Borrado REAL, solo si la vista previa es correcta y está autorizado
.\scripts\delete_snapshot.ps1 -Ct 422 -SnapshotDate "2026-10-15" -Execute -Confirm
```

**Precauciones:** requiere `LSE_DATABASE_URL`. La herramienta no modifica tablas SQL, vistas, índices ni otros snapshots. No borra proyectos maestros, porque son globales y pueden pertenecer a otras fechas o Ct. `imports` carece de columna Ct: sus filas de esa fecha se borran **solo cuando ya no existían horas de otros Ct en la fecha antes del borrado**; de lo contrario se conservan como metadatos compartidos. Del mismo modo, una OF o bono que figure en otro Ct de esa fecha mantiene su descripción.

**Limitaciones importantes:** el sistema actual guarda las descripciones con clave `(snapshot_date, OF)` o `(snapshot_date, bono)`, y las importaciones con `(snapshot_date, source_name)`. No se pueden eliminar selectivamente esas filas por Ct cuando son compartidas. Para una trazabilidad estricta multicentro deberá ampliarse el esquema e importador. La herramienta no garantiza exclusión frente a un proceso de importación concurrente; no ejecutar carga y borrado simultáneamente. Las ramas de respaldo/PITR de Neon no se purgan.

Tras el borrado, repetir una carga con `load_snapshot.ps1` requiere igualmente precaución: el importador actual sustituye horas y descripciones de la **fecha completa**, sin filtrar por Ct. No está corregido por esta utilidad.
