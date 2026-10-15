param(
    [Parameter(Mandatory=$true)][string]$Ct,
    [Parameter(Mandatory=$true)][string]$SnapshotDate,
    [switch]$Execute,
    [string]$Confirm
)
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$argsPython = @(
    (Join-Path $scriptDir "delete_snapshot_ct.py"),
    "--ct", $Ct,
    "--snapshot-date", $SnapshotDate
)
if ($Execute) {
    $expected = "ELIMINAR:$($Ct):$($SnapshotDate)"
    if ($Confirm -cne $expected) {
        throw "Confirmacion incorrecta. Para ejecutar utiliza -Confirm '$expected'."
    }
    $argsPython += @("--execute", "--confirm", $Confirm)
}
& python @argsPython
if ($LASTEXITCODE -ne 0) {
    throw "El proceso ha fallado. Revisa el error anterior."
}
