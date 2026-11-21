# OF cerradas — persistencia de Ct y descripciones (rama development)

## Fuente y prioridad

- El preparador `scripts/prepare_snapshot.py` conserva las OF operativas del Ct solicitado y genera además `indice_of_cerradas_descripciones.csv` con los títulos ERP de las OF cerradas que aparecen en `ooff_texto.csv`. No inventa operaciones ni distribuye horas cerradas por bono.
- El gate `scripts/validate_snapshot.py` exige que los códigos estén en `indice_of_cerradas.csv`, que no existan duplicados o títulos vacíos y que coincida el recuento del manifiesto. Los hashes originales se verifican antes de conectar a Neon.
- `scripts/closed_of_pipeline.py` guarda los títulos en `closed_of_source_descriptions` por `snapshot_date, order_number`. Al repetir una fecha, reemplaza únicamente los títulos ERP de esa fecha: nunca sobrescribe `closed_of_manual_assignments.manual_description`.
- La vista `v_reporting_of_hours` elige: (1) descripción interpretada del snapshot, (2) descripción manual validada, (3) título ERP original, (4) «OF cerrada».
- El Ct manual de `closed_of_manual_assignments` se reaplica en cada importación. Si entra un bono con Ct contradictorio, la importación aborta. La tabla `closed_of_hours` se reconstruye dentro de la misma transacción.
- La importación preserva los datos de otras fechas y, para horas operativas, de otros Ct. Las OF cerradas son totales por OF; nunca se reparten entre bonos.

## Verificación del snapshot 2026-11-21

Efectuar sobre **Neon development**, nunca producción sin validación independiente:

```sql
SELECT order_number, project_code, work_center, order_description, hours_incurred
FROM v_reporting_of_hours
WHERE snapshot_date = DATE '2026-11-21'
  AND order_number IN ('967341','967342','967343','967344')
ORDER BY order_number;

SELECT sum(f.hours_incurred) AS incurred_ct422
FROM v_reporting_of_hours f
JOIN projects p ON p.project_code=f.project_code
WHERE f.snapshot_date=DATE '2026-11-21'
  AND f.work_center='422'
  AND p.project_manager LIKE '500084 %';
```

Resultado de referencia: OF 967341/Ct 010/1227.3892 h; 967342/Ct 422/1773.2626 h/«Formación LSE y manuales». Total director 500084 Ct 422: 2820.7526 h, frente al POE real acumulado de 2774 h (diferencia +46.7526 h). La comparación requiere una misma fecha de corte.

## Riesgos y límites

- El índice de descripciones contiene títulos ERP **de origen**, no necesariamente interpretaciones técnicas LLM. Las interpretaciones por bono siguen reservadas a las OF operativas seleccionadas en el ZIP.
- Las OF cerradas con múltiples Ct y sin decisión manual permanecen sin atribuir; no se reparte su total entre centros.
- Las correcciones manuales prevalecen sobre títulos ERP genéricos; una descripción interpretada validada en `of_descriptions` tiene prioridad.
- No ejecutar una importación de producción con credenciales de development. `import_erp.py` exige `--expected-branch-id` y usa un bloqueo transaccional por snapshot.
