# Z-MAX 工控机反向通道 (2026-09-27) —— 工控机侧要跑的那一行(等价文件)
# 用法: 在工控机 PowerShell 里整行贴下面这一行; 或者跑本文件。
# 效果: 每 3 秒来 4060(192.168.23.50) 取一条命令 → 执行 → 把输出送回去;
#       关掉窗口 / Ctrl+C 立即断开。命令只能从 4060 本机的队列里出(网络侧只能取, 不能投)。
$t='zmax-7ce74c7f'; iwr -UseBasicParsing -TimeoutSec 8 "http://192.168.23.50:8794/agent/beat?t=$t" | Select-Object -ExpandProperty Content
while($true){ try{$c=(iwr -UseBasicParsing -TimeoutSec 8 "http://192.168.23.50:8794/agent/cmd?t=$t").Content.Trim()}catch{$c='NONE'};
 if($c -and $c -ne 'NONE'){ Write-Host ("`n>>> " + $c) -ForegroundColor Yellow;
   $o=(Invoke-Expression $c 2>&1 | Out-String); Write-Host $o;
   try{ $b=[Text.Encoding]::UTF8.GetBytes($o);
        iwr -UseBasicParsing -TimeoutSec 30 -Method POST -Uri "http://192.168.23.50:8794/agent/out?t=$t" -Body $b -ContentType 'text/plain; charset=utf-8' | Out-Null
   }catch{ Write-Host "回执发送失败: $_" -ForegroundColor Red } }
 Start-Sleep -Seconds 3 }
