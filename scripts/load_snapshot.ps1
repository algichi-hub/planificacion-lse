param(
    [string]$SnapshotDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$HoursFile = "data/OOFF_OP_Planif_Terminada.txt",
    [string]$ProjectsFile = "data/Proyectos_Sevilla.csv"
)

$ErrorActionPreference = "Stop"

if (-not $env:DATABASE_URL) {
    Write-Host "Falta DATABASE_URL en la sesion de PowerShell." -ForegroundColor Yellow
    Write-Host 'Ejemplo: $env:DATABASE_URL = "postgresql://..."'
    exit 1
}

if (-not (Test-Path $HoursFile)) {
    throw "No existe $HoursFile"
}

if (-not (Test-Path $ProjectsFile)) {
    throw "No existe $ProjectsFile"
}

python scripts/import_erp.py --hours $HoursFile --projects $ProjectsFile --snapshot-date $SnapshotDate

if ($LASTEXITCODE -ne 0) {
    throw "La importacion ha fallado."
}

Write-Host ""
Write-Host "Carga completada. Snapshot: $SnapshotDate" -ForegroundColor Green
