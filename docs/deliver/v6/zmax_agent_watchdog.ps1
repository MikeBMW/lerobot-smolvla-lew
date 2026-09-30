# ZMAX agent watchdog (ASCII only, PS 5.1 safe). 2026-09-27 rev1
# Independent of the AOI keepalive: if the reverse-channel agent is not running, start it.
# Runs as SYSTEM every minute (task ZMAX_Agent_Watchdog). Logs only when it acts.
$ErrorActionPreference = 'SilentlyContinue'
$here = 'D:\xspace\ultralytics_AOI'
$log  = Join-Path $here 'zmax_keepalive.log'
$ag = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains('agent_start_ascii.ps1') })
if ($ag.Count -eq 0) {
  $f = Join-Path $here 'agent_start_ascii.ps1'
  if (Test-Path $f) {
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden `
      -ArgumentList @('-NoProfile','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-File',$f)
    Add-Content -Path $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' watchdog: agent was dead -> started it') -Encoding ASCII
  } else {
    Add-Content -Path $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' watchdog: agent script missing: ' + $f) -Encoding ASCII
  }
}
