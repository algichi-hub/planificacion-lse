param(
    [Parameter(Mandatory=$true)][string]$Ct,
    [Parameter(Mandatory=$true)][string]$SnapshotDate,
    [switch]$ValidateOnly,
    [switch]$Execute,
    [switch]$Confirm
)
$ErrorActionPreference = "Stop"

if ($ValidateOnly -and ($Execute -or $Confirm)) {
    throw "-ValidateOnly no puede combinarse con -Execute ni -Confirm."
}
if (-not $ValidateOnly -and -not ($Execute -and $Confirm)) {
    throw "Selecciona -ValidateOnly para simular, o -Execute -Confirm para eliminar."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$argsPython = @(
    (Join-Path $scriptDir "delete_snapshot_ct.py"),
    "--ct", $Ct,
    "--snapshot-date", $SnapshotDate
)
if ($Execute -and $Confirm) {
    $expected = "ELIMINAR:$($Ct):$($SnapshotDate)"
    $argsPython += @("--execute", "--confirm", $expected)
    Write-Warning "BORRADO REAL de Ct $Ct y fecha $SnapshotDate. No ejecutes este comando si no deseas eliminar estos registros."
} else {
    Write-Host "VALIDATE ONLY: simulacion sin cambios en Neon."
}

& python @argsPython
if ($LASTEXITCODE -ne 0) {
    throw "El proceso ha fallado. Revisa el error anterior."
}
