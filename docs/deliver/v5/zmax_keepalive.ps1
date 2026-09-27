# ZMAX AOI keepalive (ASCII only, PS 5.1 safe). 2026-09-27
# Checks 10082/10083; if a channel is down, (re)starts the v5 program for it.
# Logs only when it actually starts something (no noise otherwise).
$ErrorActionPreference = 'SilentlyContinue'
$dir = 'D:\xspace\ultralytics_AOI'
$log = Join-Path $dir 'zmax_keepalive.log'
function IsUp($p) { return [bool](Get-NetTCPConnection -LocalPort $p -State Listen) }
$py = Join-Path $dir 'venv\Scripts\python.exe'
$need = @()
if (-not (IsUp 10082)) { $need += 'finger' }
if (-not (IsUp 10083)) { $need += 'surface' }
if ($need.Count -gt 0) {
  $sh = New-Object -ComObject WScript.Shell
  if ($need -contains 'finger') {
    $cmd = 'cmd /c cd /d ' + $dir + ' && ' + $py + ' cam_finger_10082_work_v5.py > ' + $dir + '\v5f.log 2>&1'
    $sh.Run($cmd, 0, $false) | Out-Null
  }
  if ($need -contains 'surface') {
    $cmd = 'cmd /c cd /d ' + $dir + ' && ' + $py + ' surface_10083_work_v5.py > ' + $dir + '\v5s.log 2>&1'
    $sh.Run($cmd, 0, $false) | Out-Null
  }
  $line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' started: ' + ($need -join ',')
  Add-Content -Path $log -Value $line -Encoding ASCII
}
