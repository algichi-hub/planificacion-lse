param(
    [string]$Ct,
    [string]$HoursFile = "data/OOFF_OP_Planif_Terminada.txt",
    [string]$ProjectsFile = "data/Proyectos_Sevilla.csv",
    [string]$OoffTextoFile = "data/ooff_texto.csv",
    [string]$OutputFile = "data/ooff_texto_consolidado.zip",
    [string]$SnapshotDate = (Get-Date -Format "yyyy-MM-dd"),
    [switch]$Help
)
$ErrorActionPreference = "Stop"
if ($Help) {
    @'
PREPARACIÓN LOCAL DE OF (sin conexión a Neon)

USO:
  .\scripts\pre_snapshot.ps1 -Ct 422
  .\scripts\pre_snapshot.ps1 -Ct 422 -SnapshotDate 2026-10-12
  .\scripts\pre_snapshot.ps1 -Help

PARÁMETROS:
  -Ct             Centro de trabajo obligatorio salvo con -Help (ej. 422).
  -HoursFile      Origen horas; data/OOFF_OP_Planif_Terminada.txt.
  -ProjectsFile   Maestro; data/Proyectos_Sevilla.csv.
  -OoffTextoFile  Textos ERP; data/ooff_texto.csv.
  -OutputFile     ZIP generado; data/ooff_texto_consolidado.zip.
  -SnapshotDate   Fecha de preparación, por defecto hoy (yyyy-MM-dd).
  -Help           Muestra esta ayuda y termina sin procesar archivos.

SALIDA: JSON de cada OF del Ct, indice_of.csv, indice_bonos.csv y manifiesto.json.
No interpreta descripciones ni escribe en Neon.
Más información: docs/SNAPSHOT_WORKFLOW.md.
'@ | Write-Host
    return
}
if ([string]::IsNullOrWhiteSpace($Ct)) {
    throw "El parámetro -Ct es obligatorio. Ejecuta el script con -Help para ver su uso."
}
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoDir = Split-Path -Parent $scriptDir
function Resolve-ProjectPath([string]$candidate) {
    if ([System.IO.Path]::IsPathRooted($candidate)) { return $candidate }
    return Join-Path $repoDir $candidate
}
$hours = Resolve-ProjectPath $HoursFile
$projects = Resolve-ProjectPath $ProjectsFile
$source = Resolve-ProjectPath $OoffTextoFile
$output = Resolve-ProjectPath $OutputFile
foreach ($file in @($hours, $projects, $source)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "No existe entrada: $file" }
}
$python = Join-Path $scriptDir "prepare_snapshot.py"
& python $python --ct $Ct --hours $hours --projects $projects --ooff-texto $source --output $output --snapshot-date $SnapshotDate
if ($LASTEXITCODE -ne 0) { throw "Error en pre_snapshot.py. No se ha generado salida válida." }
Write-Host "Preparación finalizada: $output (Ct. $Ct)" -ForegroundColor Green
Write-Host "No se ha modificado Neon."
