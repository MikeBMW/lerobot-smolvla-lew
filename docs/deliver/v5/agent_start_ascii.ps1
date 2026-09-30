# Z-MAX reverse channel to 4060 (2026-09-27). ASCII only, PS 5.1 safe.
# Every 3s: fetch one command from 4060 (192.168.23.50), run it, post the output back.
# Close this window (or Ctrl+C) to disconnect immediately. No credentials, no registry, no autostart.
$t = $env:ZMAX_AGENT_TOKEN
$base = 'http://192.168.23.50:8794/agent'
Write-Host ('[ZMAX] connecting to ' + $base + ' ...') -ForegroundColor Cyan
try {
  $h = (iwr -UseBasicParsing -TimeoutSec 8 "$base/beat?t=$t").Content
  Write-Host ('[ZMAX] CHANNEL OK -> ' + $h) -ForegroundColor Green
  Write-Host '[ZMAX] waiting for commands from 4060 ...' -ForegroundColor Green
} catch {
  Write-Host ('[ZMAX] CANNOT reach 4060: ' + $_) -ForegroundColor Red
}
while ($true) {
  try { $c = (iwr -UseBasicParsing -TimeoutSec 8 "$base/cmd?t=$t").Content.Trim() } catch { $c = 'NONE' }
  if ($c -and $c -ne 'NONE') {
    Write-Host ("`n[ZMAX] >>> " + $c) -ForegroundColor Yellow
    $o = (Invoke-Expression $c 2>&1 | Out-String)
    Write-Host $o
    try {
      $b = [Text.Encoding]::UTF8.GetBytes($o)
      iwr -UseBasicParsing -TimeoutSec 30 -Method POST -Uri "$base/out?t=$t" -Body $b -ContentType 'text/plain; charset=utf-8' | Out-Null
      Write-Host ('[ZMAX] <<< output sent back (' + $o.Length + ' chars)') -ForegroundColor DarkGray
    } catch { Write-Host ("[ZMAX] post failed: " + $_) -ForegroundColor Red }
  }
  Start-Sleep -Seconds 3
}
