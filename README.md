# Planificación LSE

**Prompt reutilizable para cualquier agente LLM:** [Interpretación de OF y bonos ERP](docs/LLM_ERP_PROMPT.md). Incluye el caso `### SIN DATOS ###` y el formato obligatorio de ambos CSV.

> **Entrada de textos ERP:** `data/ooff_texto.csv` (CSV sin comprimir). `pre_snapshot.ps1` genera `data/ooff_texto_consolidado.zip` para el LLM. El ZIP original `ooff_texto.zip` ya no es la entrada predeterminada.

> **Flujo operativo actual:** para preparar OF y bonos, validar los cuatro archivos e importar snapshots por centro de trabajo, consulta [Guía de preparación y carga de snapshots](docs/SNAPSHOT_WORKFLOW.md). Los comandos históricos de importación de esta V0 se conservan solo como referencia y no describen el proceso vigente.

V0 de un sistema de control de horas basado en SQL para sustituir el resumen ejecutivo manual.

## Objetivo de la V0

Validar el flujo completo:

1. Exportar desde ERP:
   - `OOFF_OP_Planif_Terminada.txt`
   - `Proyectos_Sevilla.csv`
2. Importar y normalizar ambos ficheros.
3. Persistir la información en PostgreSQL / Neon.
4. Consultar horas concedidas, incurridas, desviación y consumo.
5. Navegar por la jerarquía:
   - Proyecto
   - Orden de Fabricación
   - Bono / operación

El Bono se calcula como:

```text
Bono = Orden + Operación con 4 dígitos
351201 + 10 -> 3512010010
```

## Métricas

- Horas concedidas = `T.Conce.`
- Horas incurridas = `T.Inver.`
- Desviación = Incurridas - Concedidas
- Horas restantes = Concedidas - Incurridas
- Consumo = Incurridas / Concedidas

Una desviación positiva representa sobreconsumo.

## Estructura

```text
app.py                  Dashboard Streamlit/Plotly
scripts/import_erp.py   ETL ERP -> PostgreSQL
sql/schema.sql          Tablas, índices y vistas SQL
.env.example            Variables de entorno
requirements.txt        Dependencias Python
```

## Base de datos

La V0 crea:

- `projects`: maestro de proyectos.
- `fact_hours`: dato granular del export de OF/operaciones.
- `imports`: trazabilidad de cargas.
- `v_project_hours`: agregado por proyecto.
- `v_order_hours`: agregado por OF.
- `v_bonus_hours`: agregado por bono.
- `v_latest_snapshot`: último snapshot disponible.

Los datos se almacenan por `snapshot_date`, por lo que el modelo ya permite conservar histórico semanal.

## Preparación

Python 3.11+ recomendado.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

En Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Configurar en `.env`:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DB?sslmode=require
```

## Importar un snapshot

```bash
python scripts/import_erp.py \
  --hours data/OOFF_OP_Planif_Terminada.txt \
  --projects data/Proyectos_Sevilla.csv \
  --snapshot-date 2026-10-07
```

Si se vuelve a cargar la misma fecha, la V0 reemplaza el detalle de esa fecha en vez de duplicarlo.

El importador valida las cabeceras, interpreta los decimales con coma y calcula el Bono. Si `T.Pendi.` llega como `########` por desbordamiento de formato del export, recalcula ese valor como `T.Conce. - T.Inver.`.

## Ejecutar dashboard

```bash
streamlit run app.py
```

El dashboard muestra:

- KPIs globales o filtrados por proyecto.
- Horas concedidas vs. incurridas por proyecto.
- Tabla ejecutiva de proyectos.
- Tabla de Órdenes de Fabricación.
- Tabla de Bonos cuando se selecciona un proyecto.

## Validación inicial con los exports reales

La estructura se ha contrastado con los dos ficheros de partida usados para definir esta V0:

- 6.275 filas de horas procesables.
- 2.694 filas del maestro de proyectos.
- 0 proyectos de las filas de horas sin correspondencia en el maestro.
- 0 duplicados detectados para la clave Proyecto + OF + Operación.
- Se detectó al menos un `T.Pendi.` representado como `########`; queda cubierto por el ETL.

## Siguiente Gate

Para considerar cerrada la V0:

1. Crear/conectar una base Neon.
2. Ejecutar una carga real.
3. Verificar reconciliación de totales contra el export ERP.
4. Abrir el dashboard y revisar Proyecto -> OF -> Bono.
5. Congelar la V0 antes de añadir automatización semanal y forecasting.


## Deploy en Streamlit Community Cloud

La rama `v0/sql-dashboard` está preparada para ejecutarse tanto en local como en Streamlit Community Cloud.

### Configuración de la app

En Streamlit Community Cloud:

1. Crear una nueva app desde GitHub.
2. Repository: `algichi-hub/planificacion-lse`
3. Branch: `v0/sql-dashboard`
4. Main file path: `app.py`
5. En **Advanced settings / Secrets**, añadir:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require"
```

No guardar nunca la URL real de conexión en el repositorio.

La aplicación busca la conexión en este orden:

1. variable de entorno `DATABASE_URL` / fichero local `.env`;
2. `st.secrets["DATABASE_URL"]` en Streamlit Cloud.

### Antes del primer deploy útil

El dashboard puede publicarse antes, pero para mostrar datos la base Neon debe contener el esquema y al menos un snapshot. La primera carga se realiza con:

```bash
python scripts/import_erp.py \
  --hours data/OOFF_OP_Planif_Terminada.txt \
  --projects data/Proyectos_Sevilla.csv \
  --snapshot-date YYYY-MM-DD
```

El propio importador crea/actualiza el esquema SQL antes de cargar los datos.

### Seguridad

- `.env` está excluido de Git.
- `.streamlit/secrets.toml` está excluido de Git.
- Streamlit Cloud debe recibir `DATABASE_URL` únicamente mediante su gestor de Secrets.
- Los exports ERP bajo `data/\*.txt`, `data/\*.csv` y `data/\*.xlsx` están excluidos del repositorio.

## Tablas compatibles con Excel español

En todas las tablas de consulta de Home, Riesgos, ETC y futuros tableros,
utilizar `excel_compat.excel_copy_frame` para la representación mostrada por
`st.dataframe`. Permite copiar rangos con **coma decimal y sin separador de
miles**, sin modificar el dato numérico de cálculos o de Neon. No aplicar a
`st.data_editor`. Convención y ejemplos: [docs/EXCEL_COPY_TABLES.md](docs/EXCEL_COPY_TABLES.md).
