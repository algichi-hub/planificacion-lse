param(
    [string]$Ct,
    [string]$SnapshotDate,
    [switch]$ValidateOnly,
    [switch]$Execute,
    [switch]$Confirm,
    [switch]$Help
)
$ErrorActionPreference = "Stop"
if ($Help) {
    @'
ELIMINACION SEGURA DE SNAPSHOT EN NEON POR CENTRO Y FECHA

USO:
  .\scripts\delete_snapshot.ps1 -Ct 422 -SnapshotDate "2026-10-15" -ValidateOnly
  .\scripts\delete_snapshot.ps1 -Ct 422 -SnapshotDate "2026-10-15" -Execute -Confirm
  .\scripts\delete_snapshot.ps1 -Help

PARAMETROS:
  -Ct             Centro de trabajo (obligatorio excepto con -Help).
  -SnapshotDate   Fecha exacta YYYY-MM-DD (obligatoria excepto con -Help).
  -ValidateOnly   Simula y muestra registros afectados, sin eliminar nada.
  -Execute        Autoriza ejecutar el borrado real; exige -Confirm.
  -Confirm        Confirma explicitamente el borrado; exige -Execute.
  -Help           Muestra esta ayuda y finaliza sin conectar a Neon.

SEGURIDAD:
  Requiere DATABASE_URL excepto con -Help.
  Sin modo explicito, o combinando -ValidateOnly con -Execute/-Confirm,
  se rechaza la operacion.
  Las tablas de proyectos y los registros compartidos con otros Ct se conservan.
  El borrado real se ejecuta en una transaccion; no modifica otros snapshots.
'@ | Write-Host
    return
}
if ([string]::IsNullOrWhiteSpace($Ct) -or [string]::IsNullOrWhiteSpace($SnapshotDate)) {
    throw "Debes indicar -Ct y -SnapshotDate. Ejecuta -Help para ver el uso."
}

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
