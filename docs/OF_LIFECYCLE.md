# Seguimiento mensual del ciclo de vida de OF

Se mantiene el pipeline actual: `pre_snapshot.ps1` prepara los cuatro ERP, `load_snapshot.ps1` valida y carga el snapshot mensual, y `closed_of_hours` guarda las **horas totales definitivas de cada OF cerrada**, sin repartirlas por bono.

## Cambio implementado

Al terminar la carga, en **la misma transacción y bajo el bloqueo existente del snapshot**, `scripts/of_lifecycle.py` compara el estado ERP actual con el **último estado observado** de cada OF en un snapshot anterior. Registra exclusivamente cambios en `of_lifecycle_events`:

- `snapshot_date`: mes de detección
- `order_number`: OF
- `previous_snapshot_date`: último snapshot anterior donde constaba
- `previous_status`: estado anterior
- `current_status`: estado actual

Normaliza Activa, Lanzada, Terminada y Cerrada, manteniendo el texto ERP para estados desconocidos. No duplica filas de bonos, horas ni snapshot completos.

**Sin eventos** para primeras apariciones, OF con estado inalterado o ausencias en un export. Una OF ausente **no** se interpreta como cerrada. El bloqueo preexistente de reaperturas `Cerrada -> operativa` continúa deteniendo la importación antes de guardar.

Repetir un snapshot reconstruye sus eventos (DELETE/INSERT bajo la misma transacción): evita duplicidades. Las importaciones deben seguir un orden mensual cronológico; si se corrige retroactivamente un snapshot pasado, regenerar las transiciones de los snapshots posteriores afectados.

## Consultas de control

```sql
SELECT snapshot_date, order_number, previous_snapshot_date,
       previous_status, current_status
FROM of_lifecycle_events
ORDER BY snapshot_date DESC, order_number;

SELECT previous_status, current_status, COUNT(*) AS of
FROM of_lifecycle_events
WHERE snapshot_date = DATE '2026-11-21'
GROUP BY previous_status, current_status;
```

La primera carga tras este cambio puede encontrar OF ya cerradas sin registro operativo anterior: no inventa su transición. `bonus_ct_registry` conserva la relación histórica bono-Ct observada con anterioridad.

## Preparación de prueba y soak

1. `git pull` de `feature/closed-of-importer` en el entorno de pruebas.
2. `python -m unittest discover -s tests -p 'test_of_lifecycle.py'`.
3. `load_snapshot.ps1 -Ct 422 -ValidateOnly` con los archivos ERP del mes.
4. Carga controlada en Neon development; verificar que el número de eventos es el esperado.
5. Repetir el mismo snapshot sin cambiar los archivos y comprobar que no aparecen duplicados.
6. Avanzar al siguiente mes: probar Lanzada -> Activa, Activa -> Cerrada, estado sin cambios, OF desaparecida y primera aparición. Probar el bloqueo de reapertura.

La lógica de conciliación POE, las horas definitivas de OF cerradas, las asignaciones manuales Ct y las vistas del dashboard permanecen sin cambios.
