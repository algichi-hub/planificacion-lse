# Convención de tablas copiables a Excel (es-ES)

**Obligatoria para nuevas tablas de consulta** en Home, Riesgos, ETC y futuros tableros de Planificación LSE.

Streamlit puede mostrar números localizados y seguir copiando valores crudos con punto decimal.
Por eso, para tablas **de consulta exclusivamente**, se debe transformar una copia:

```python
from excel_compat import excel_copy_frame

st.dataframe(
    excel_copy_frame(dataframe_original[["project_code", "hours_granted", "hours_incurred"]]),
    hide_index=True,
    use_container_width=True,
    column_config={
        "project_code": st.column_config.TextColumn("Proyecto"),
        "hours_granted": st.column_config.TextColumn("Concedidas"),
        "hours_incurred": st.column_config.TextColumn("Incurridas"),
    },
)
```

- Decimal: coma; sin separador de miles; horas: dos decimales; porcentajes: un decimal (sin signo '%' en las celdas, en el nombre de columna).
- Futuros campos decimales float/Decimal: dos decimales por defecto, o indicar `precision={"campo": 3}`.
- No convertir ID/códigos a números: sus ceros iniciales se mantienen en Streamlit (Excel puede interpretarlos por su cuenta).
- **No utilizar** `excel_copy_frame` para `st.data_editor`, cálculos, gráficas, persistencia PostgreSQL/Neon ni exportaciones internas.
- Las columnas visuales se convierten a texto: su ordenación en Streamlit es lexicográfica. Los datasets analíticos siguen siendo numéricos.
- Para exportación masiva y tipos numéricos fiables, usar un fichero XLSX con celdas numéricas en vez de basarse en el portapapeles.

Regresión rápida: ejecutar `python -m unittest discover -s tests -p test_excel_compat.py` y verificar en navegador que seleccionar, copiar y pegar celdas produce números reconocidos por Excel con configuración regional española.

No requiere ningún cambio en esquema o datos de Neon.

## Exportación CSV compatible con Excel español (obligatoria)

El CSV integrado en el menú de `st.dataframe` utiliza un formato propio,
normalmente con comas como separadores de columna: **no sirve para Excel español
abierto directamente**. Mantener la opción nativa, pero proporcionar siempre
un botón visible **Descargar CSV · Excel español** junto a cada tabla de consulta:

```python
from excel_compat import excel_copy_frame, excel_csv_bytes

visible = df[["project_code", "hours_granted", "hours_incurred"]]
st.dataframe(excel_copy_frame(visible), use_container_width=True)
st.download_button(
    "Descargar CSV · Excel español",
    data=excel_csv_bytes(visible),  # dataframe original, no el de visualización
    file_name="proyectos.csv",
    mime="text/csv; charset=utf-8",
    key="csv_proyectos",
)
```

Contrato: codificación UTF-8 con BOM, separador de columnas `;`, coma decimal,
sin separador de miles, saltos de línea CRLF, sin índice. Se conservan las
comas dentro de las descripciones porque el delimitador es `;`. Para validar:
`python -m unittest discover -s tests -p test_excel_compat.py` y apertura del
CSV descargado en Excel (España).

**Importante:** el menú nativo de descarga CSV de Streamlit puede continuar
ofreciendo archivos delimitados por comas. Para Excel español usar siempre el
botón específico de exportación. No modificar Neon ni el editor ETC.
