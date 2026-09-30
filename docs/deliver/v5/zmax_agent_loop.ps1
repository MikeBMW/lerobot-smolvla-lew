# ZMAX reverse-channel agent, resilient loop (ASCII only, PS 5.1 safe). 2026-09-27
# Keeps the polling agent alive: if it exits (network blip / console close), restart after 10s.
# No credentials, no registry. Stop with: Stop-ScheduledTask -TaskName ZMAX_Agent
$dir = 'D:\xspace\ultralytics_AOI'
$agent = Join-Path $dir 'zmax_agent.ps1'
while ($true) {
  if (Test-Path $agent) {
    & powershell -ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File $agent
  }
  Start-Sleep -Seconds 10
}
