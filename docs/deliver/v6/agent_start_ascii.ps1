# Z-MAX reverse channel to 4060 (2026-09-27 rev2). ASCII only, PS 5.1 safe.
# Every 3s: fetch one command from 4060 (192.168.23.50), run it in a CHILD powershell,
# post the output back. rev2: a bad command can no longer kill this loop
# (isolated child process + try/catch everywhere) - rev1 died once on a command that threw.
$t = $env:ZMAX_AGENT_TOKEN
$base = 'http://192.168.23.50:8794/agent'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $here) { $here = 'D:\xspace\ultralytics_AOI' }
# rev3: single instance - a second copy exits (a duplicate agent just doubles polling)
$me = $PID
$others = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains('agent_start_ascii.ps1') -and $_.ProcessId -ne $me })
if ($others.Count -ge 1) {
  Write-Host ('[ZMAX] another agent already running (pid ' + $others[0].ProcessId + ') -> exit') -ForegroundColor Yellow
  exit
}
Write-Host ('[ZMAX] connecting to ' + $base + ' ...') -ForegroundColor Cyan
try {
  $h = (iwr -UseBasicParsing -TimeoutSec 8 "$base/beat?t=$t").Content
  Write-Host ('[ZMAX] CHANNEL OK -> ' + $h) -ForegroundColor Green
} catch {
  Write-Host ('[ZMAX] CANNOT reach 4060: ' + $_) -ForegroundColor Red
}
# self-bootstrap: also pull the newest keepalive (it restarts me if I ever die)
try {
  iwr -UseBasicParsing -TimeoutSec 20 'http://192.168.23.50:8794/v6/zmax_keepalive.ps1' -OutFile (Join-Path $here 'zmax_keepalive.ps1')
  Write-Host '[ZMAX] keepalive refreshed' -ForegroundColor DarkGray
} catch { }
# rev3: pull the watchdog script and make sure its task exists (it restarts me if I die)
try {
  $wd = Join-Path $here 'zmax_agent_watchdog.ps1'
  iwr -UseBasicParsing -TimeoutSec 20 'http://192.168.23.50:8794/v6/zmax_agent_watchdog.ps1' -OutFile $wd
  $ex = (& schtasks /query /tn ZMAX_Agent_Watchdog 2>$null | Out-String)
  if ($ex -notmatch 'ZMAX_Agent_Watchdog') {
    & schtasks /create /tn ZMAX_Agent_Watchdog /tr ('powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ' + $wd) /sc minute /mo 1 /ru SYSTEM /f | Out-Null
    Write-Host '[ZMAX] watchdog task installed (every minute)' -ForegroundColor DarkGray
  } else {
    Write-Host '[ZMAX] watchdog task already present' -ForegroundColor DarkGray
  }
} catch { }
Write-Host '[ZMAX] waiting for commands from 4060 ...' -ForegroundColor Green
while ($true) {
  $c = $null
  try { $c = (iwr -UseBasicParsing -TimeoutSec 8 "$base/cmd?t=$t").Content.Trim() } catch { $c = $null }
  if ($c -and $c -ne 'NONE') {
    Write-Host ("`n[ZMAX] >>> " + $c) -ForegroundColor Yellow
    $o = ''
    try {
      $f = Join-Path $env:TEMP 'zmax_cmd.ps1'
      $body = 'Set-Location -LiteralPath ' + "'" + $here + "'" + "`r`n" + $c
      [IO.File]::WriteAllText($f, $body, (New-Object System.Text.UTF8Encoding($true)))
      $o = (& powershell -NoProfile -ExecutionPolicy Bypass -File $f 2>&1 | Out-String)
    } catch { $o = '[ZMAX] command failed: ' + $_ }
    if (-not $o) { $o = '(no output)' }
    Write-Host $o
    try {
      $b = [Text.Encoding]::UTF8.GetBytes($o)
      iwr -UseBasicParsing -TimeoutSec 30 -Method POST -Uri "$base/out?t=$t" -Body $b -ContentType 'text/plain; charset=utf-8' | Out-Null
      Write-Host ('[ZMAX] <<< output sent back (' + $o.Length + ' chars)') -ForegroundColor DarkGray
    } catch { Write-Host ("[ZMAX] post failed: " + $_) -ForegroundColor Red }
  }
  Start-Sleep -Seconds 3
}
