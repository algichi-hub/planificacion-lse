param(
    [Parameter(Mandatory = $true)]
    [string]$Ct,
    [string]$SnapshotDate = (Get-Date -Format "yyyy-MM-dd"),
    [string]$HoursFile = "data/OOFF_OP_Planif_Terminada.txt",
    [string]$ProjectsFile = "data/Proyectos_Sevilla.csv",
    [string]$OfTextFile = "data/ooff_texto_interpretado.csv",
    [string]$BonusTextFile = "data/bono_texto_interpretado.csv",
    [string]$PreparedZip = "data/ooff_texto_consolidado.zip",
    [switch]$ValidateOnly
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
$ofText = Resolve-ProjectPath $OfTextFile
$bonusText = Resolve-ProjectPath $BonusTextFile
$prepared = Resolve-ProjectPath $PreparedZip

foreach ($file in @($hours, $projects, $ofText, $bonusText)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Entrada obligatoria ausente: $file"
    }
}

$arguments = @(
    (Join-Path $scriptDir "import_erp.py"),
    "--hours", $hours,
    "--projects", $projects,
    "--of-text", $ofText,
    "--bonus-text", $bonusText,
    "--ct", $Ct,
    "--snapshot-date", $SnapshotDate
)

if (Test-Path -LiteralPath $prepared -PathType Leaf) {
    $arguments += @("--prepared-zip", $prepared)
}

if ($ValidateOnly) {
    $arguments += "--validate-only"
} elseif (-not $env:DATABASE_URL) {
    throw "Falta DATABASE_URL en la sesión. Usa -ValidateOnly para probar sin Neon."
}

& python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "El Gate de validación o la carga en Neon ha fallado. Revisa el error anterior."
}
if ($ValidateOnly) {
    Write-Host "Gate VALIDATE ONLY superado. Neon no modificado." -ForegroundColor Green
} else {
    Write-Host "Snapshot cargado en Neon: fecha $SnapshotDate, centro $Ct." -ForegroundColor Green
}
