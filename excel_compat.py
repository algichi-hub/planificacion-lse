"""Display-only Spanish decimal strings for read-only Streamlit tables.

Use excel_copy_frame(df) immediately before st.dataframe(...). Never apply it to
st.data_editor, data feeding charts, aggregate computations, or database writes.
The actual stored numeric data and the original dataframe remain untouched.
"""
from decimal import Decimal
from numbers import Real

import pandas as pd


def excel_copy_frame(frame: pd.DataFrame, *, precision: dict[str, int] | None = None) -> pd.DataFrame:
    """Return a copy whose decimal cells paste as numeric values in Spanish Excel.

    Floats and Decimals are formatted without thousand separators. Integer counts
    stay numeric; IDs/codes stored as strings are never converted. Known percent
    columns use one decimal; hour columns use two. Override with precision when
    a future table requires a different number of decimal places.
    """
    result = frame.copy()
    overrides = precision or {}
    for column in result.columns:
        series = result[column]
        name = str(column).lower()
        count_or_identifier = name in {"project_count", "row_count", "id"} or name.endswith("_id")
        if count_or_identifier or pd.api.types.is_bool_dtype(series):
            continue
        if column in overrides:
            digits = overrides[column]
        elif name.endswith("_pct") or name in {"consumption_pct"}:
            digits = 1
        elif "hours" in name or name in {"etc", "etc_hours"}:
            digits = 2
        else:
            # Covers any future numeric decimal column while leaving integer
            # counts and textual identifiers intact.
            numeric_dtype = pd.api.types.is_float_dtype(series)
            decimal_objects = (series.dropna().map(
                lambda value: isinstance(value, (Decimal, float))
            ).any() if series.dtype == object else False)
            if not (numeric_dtype or decimal_objects):
                continue
            digits = 2
        if not isinstance(digits, int) or not 0 <= digits <= 8:
            raise ValueError("precision must be between 0 and 8 decimal places")
        result[column] = series.map(
            lambda value: "" if pd.isna(value)
            else f"{value:.{digits}f}".replace(".", ",")
        )
    return result
