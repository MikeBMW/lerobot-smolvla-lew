# ZMAX AOI keepalive (ASCII only, PS 5.1 safe). 2026-09-27 rev2
# For each channel (10082/10083):
#   - not listening             -> start the v5 program for it
#   - listening but no v5 face  -> listener is NOT our v5 (v2 / half-dead copy): kill it, start v5
# v5 face = GET /storage returns HTTP 200 (v2 has no /storage; a wedged copy times out).
# Logs only when it acts (no routine noise).
$ErrorActionPreference = 'SilentlyContinue'
$dir = 'D:\xspace\ultralytics_AOI'
$log = Join-Path $dir 'zmax_keepalive.log'
$py  = Join-Path $dir 'venv\Scripts\python.exe'
$prog = @{ 10082 = 'cam_finger_10082_work_v5.py'; 10083 = 'cam_surface_10083_work_v5.py' }

function PortPid($p) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -EA SilentlyContinue | Select-Object -First 1
  if ($c) { return [int]$c.OwningProcess }
  return 0
}
function IsV5($p) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Uri ('http://127.0.0.1:' + $p + '/storage')
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}
function LogName($p) {
  if ($p -eq 10082) { return 'v5f.log' }
  return 'v5s.log'
}
function StartOne($p) {
  $sh = New-Object -ComObject WScript.Shell
  $cmd = 'cmd /c cd /d ' + $dir + ' && ' + $py + ' ' + $prog[$p] + ' > ' + $dir + '\' + (LogName $p) + ' 2>&1'
  $sh.Run($cmd, 0, $false) | Out-Null
}

$acts = @()
foreach ($p in 10082, 10083) {
  $owner = PortPid $p
  if ($owner -eq 0) {
    StartOne $p
    $acts += ('start ' + $p + ' (' + $prog[$p] + ')')
    continue
  }
  if (-not (IsV5 $p)) {
    Start-Sleep -Seconds 4
    if (-not (IsV5 $p)) {
      Stop-Process -Id $owner -Force -EA SilentlyContinue
      Start-Sleep -Seconds 5
      StartOne $p
      $acts += ('replace ' + $p + ': pid ' + $owner + ' had no /storage face -> killed, started ' + $prog[$p])
    }
  }
}
if ($acts.Count -gt 0) {
  Add-Content -Path $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + ($acts -join ' | ')) -Encoding ASCII
}
