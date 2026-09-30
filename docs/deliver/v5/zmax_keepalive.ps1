# ZMAX AOI keepalive (ASCII only, PS 5.1 safe). 2026-09-27 rev3
# For each channel (10082/10083):
#   1) not listening            -> start the v5 program
#   2) listening, no v5 face    -> that listener is NOT our v5 (v2 / wedged copy): kill it, start v5
#   3) too many copies          -> keep only the port owner (+ its launcher parent), kill the strays
#      (a stray copy can steal the camera when the live one restarts -> live one then fails to open)
# v5 face = GET /storage returns HTTP 200.  Logs only when it acts.
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
function LogName($p) { if ($p -eq 10082) { return 'v5f.log' } return 'v5s.log' }
function StartOne($p) {
  $sh = New-Object -ComObject WScript.Shell
  $cmd = 'cmd /c cd /d ' + $dir + ' && ' + $py + ' ' + $prog[$p] + ' > ' + $dir + '\' + (LogName $p) + ' 2>&1'
  $sh.Run($cmd, 0, $false) | Out-Null
}
function Copies($name) {
  return @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -EA SilentlyContinue |
           Where-Object { $_.CommandLine -and $_.CommandLine.Contains($name) })
}

$acts = @()
foreach ($p in 10082, 10083) {
  $owner = PortPid $p
  if ($owner -eq 0) {
    $stale = Copies $prog[$p]
    if ($stale.Count -gt 0) {
      foreach ($s in $stale) { Stop-Process -Id $s.ProcessId -Force -EA SilentlyContinue }
      Start-Sleep -Seconds 4
      $acts += ('clean ' + $stale.Count + ' stale ' + $prog[$p] + ' (port was free)')
    }
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
      continue
    }
  }
  # healthy: make sure there is exactly one copy (owner + its launcher) - kill the rest
  $all = Copies $prog[$p]
  if ($all.Count -gt 2) {
    $parent = (Get-CimInstance Win32_Process -Filter ("ProcessId=" + $owner) -EA SilentlyContinue).ParentProcessId
    $killed = 0
    foreach ($x in $all) {
      if ($x.ProcessId -eq $owner -or $x.ProcessId -eq $parent) { continue }
      Stop-Process -Id $x.ProcessId -Force -EA SilentlyContinue
      $killed++
    }
    if ($killed -gt 0) { $acts += ('dedup ' + $prog[$p] + ': killed ' + $killed + ' stray copy(ies), kept pid ' + $owner) }
  }
}
if ($acts.Count -gt 0) {
  Add-Content -Path $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + ($acts -join ' | ')) -Encoding ASCII
}
