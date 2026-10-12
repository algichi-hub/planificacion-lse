param(
    [Parameter(Mandatory = $true)]
    [string]$Ct,
    [string]$HoursFile = "data/OOFF_OP_Planif_Terminada.txt",
    [string]$ProjectsFile = "data/Proyectos_Sevilla.csv",
    [string]$OoffTextoFile = "data/ooff_texto.zip",
    [string]$OutputFile = "data/ooff_texto_consolidado.zip",
    [string]$SnapshotDate = (Get-Date -Format "yyyy-MM-dd")
)
$ErrorActionPreference = "Stop"
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
