# EAC / ETC — prueba de la nueva vista

Rama: `feature/eac-dashboard`, derivada de `v0/sql-dashboard`.

## Arranque en Windows (PowerShell)

Desde la carpeta original, con el entorno virtual ya instalado:

```powershell
git fetch origin feature/eac-dashboard
git worktree add ..\planificacion-lse-eac feature/eac-dashboard
Copy-Item .\.env ..\planificacion-lse-eac\.env
cd ..\planificacion-lse-eac
..\planificacion-lse\.venv\Scripts\python.exe -m streamlit run app.py
```

Si .env se almacena en otro lugar, configura `DATABASE_URL` como siempre. Si tienes ya una worktree o una rama local con ese nombre, revisa antes de repetir el comando.

## Funcionalidad

- El nuevo icono **EAC** del menú inferior abre el módulo `eac_board.py`.
- Crea o selecciona una fotografía `YYYY / Qn`. Cada par año-trimestre es único.
- Todos los proyectos provienen de `projects`; `project_manager` es **agrupación de gestión**.
- Introduce ETC en horas, deja en blanco si todavía no existe dato; cero es un valor explícito.
- Guarda solo las filas modificadas. El guardado comprueba cambios concurrentes y mantiene auditoría.
- Se puede publicar, reabrir para corregir y volver a publicar; no borra históricos.
- La comparación utiliza las horas del último snapshot operativo y los ETC del trimestre seleccionado. No son magnitudes temporalmente equivalentes por defecto.
- Las tablas nuevas son `eac_snapshots`, `eac_project_hours` y `eac_project_hours_audit`. Ya están creadas en Neon production. El archivo `sql/eac_additive.sql` documenta su esquema; no hace falta ejecutarlo de nuevo.
- No se han modificado ni los archivos de importación ERP, ni sus tablas, ni vistas, ni los cálculos de riesgo.

## Pruebas manuales recomendadas

1. Entrar a EAC y crear una fotografía nueva Q4 2026.
2. Introducir ETC de prueba únicamente en un proyecto y guardar.
3. Recargar el navegador y comprobar persistencia.
4. Editar ese ETC y verificar la auditoría.
5. Publicar y comprobar bloqueo; reabrir y corregir.
6. Entrar en Home/Riesgos y comprobar que funcionan como antes.

**Nota:** Esta rama de prueba no ha sido desplegada automáticamente ni incorporada a `main`. No usar valores de prueba en producción si se quiere mantener limpio el histórico ETC.
