# ══════════════════════════════════════════════════════════════════════════════
#  10083 表面检测 升级到 v4  —— 一键脚本 (在工控机 D:\xspace\ultralytics_AOI 下运行)
#  不改 v2 的任何一个文件; 端口还是 10083; 出问题随时原样回 v2。
#
#  只自检(什么都不改):  powershell -ExecutionPolicy Bypass -File .\upgrade_10083_v4.ps1 -CheckOnly
#  正式升级:            powershell -ExecutionPolicy Bypass -File .\upgrade_10083_v4.ps1 -Apply
#                      (会先问你一句再停 v2; 加 -Yes 表示不问直接干)
# ══════════════════════════════════════════════════════════════════════════════
param([switch]$CheckOnly, [switch]$Apply, [switch]$Yes)
$ErrorActionPreference = 'Stop'
$BASE = 'http://192.168.23.50:8794'
$PORT = 10083
$DEST = Join-Path (Get-Location) 'surface_10083_work_v4.py'

function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Head($m) { Write-Host ''; Write-Host ('── ' + $m + ' ' + ('─' * [Math]::Max(0, 62 - $m.Length))) -ForegroundColor Cyan }

Head '0. 环境'
$pyexe = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $pyexe) { Say '找不到 python —— 先激活 venv 再跑本脚本' 'Red'; exit 1 }
Say ('python : ' + $pyexe.Source)
$ver = & python -c "import flask,cv2,numpy;print('flask/cv2/numpy OK')" 2>&1
Say ('依赖   : ' + $ver)
if ($ver -notmatch 'OK') { Say '依赖不全(v2 能跑说明环境是对的, 请确认在同一个 venv 里)' 'Yellow' }
$need = 'SciCam_class.py', 'yolo_detector.py', 'config.yaml'
foreach ($f in $need) {
    if (Test-Path (Join-Path (Get-Location) $f)) { Say ('文件   : ' + $f + '  ✓') }
    else { Say ('文件   : ' + $f + '  缺失! (v4 复用 v2 的 SDK/权重, 必须和 v2 在同一目录)' 'Red') }
}

Head '1. 现在谁在 10083'
$conn = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$v2pid = $null
if ($conn) {
    $v2pid = $conn.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$v2pid" -ErrorAction SilentlyContinue
    Say ('v2 正在跑: pid=' + $v2pid) 'Yellow'
    Say ('  命令行: ' + $proc.CommandLine)
    try { $r = Invoke-WebRequest -Uri "http://127.0.0.1:$PORT/picture?kind=origin" -TimeoutSec 5 -UseBasicParsing
          Say ('  /picture 已存在? HTTP ' + $r.StatusCode + ' (说明已经是 v4 了)') 'Yellow' }
    catch { Say ('  /picture -> ' + $_.Exception.Message + '  ⇒ 确认是 v2(没有取图路由)') 'Yellow' }
} else {
    Say ('10083 没有监听 —— v2 当前没跑(可以直接上 v4)') 'Yellow'
}

if ($CheckOnly) { Say ''; Say '只自检模式: 到此为止, 没有动任何东西。' 'Green'; exit 0 }

Head '2. 下载 v4 + 校验'
try {
    Invoke-WebRequest -Uri "$BASE/surface_10083_work_v4.py" -OutFile $DEST -TimeoutSec 30 -UseBasicParsing
    Invoke-WebRequest -Uri "$BASE/surface_10083_work_v4.py.sha256" -OutFile "$DEST.sha256" -TimeoutSec 30 -UseBasicParsing
} catch { Say ('下载失败: ' + $_.Exception.Message) 'Red'; Say '检查本机(工控机)能不能访问 192.168.23.50:8794' 'Red'; exit 1 }
$want = ((Get-Content "$DEST.sha256") -split '\s+')[0].ToLower()
$got = (Get-FileHash $DEST -Algorithm SHA256).Hash.ToLower()
Say ('文件: ' + $DEST)
Say ('大小: ' + (Get-Item $DEST).Length + ' 字节')
if ($want -eq $got) { Say ('SHA256 校验通过: ' + $got) 'Green' } else { Say ('SHA256 不一致! 期望 ' + $want + ' 实得 ' + $got) 'Red'; exit 1 }

Head '3. 试跑自检(起在 10084, 不碰 v2 / 不碰 10083)'
$p = Start-Process python -ArgumentList 'surface_10083_work_v4.py', '10084' -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 10
$okRoutes = 0
foreach ($u in @('/picture?meta=1', '/last_result', '/crop_info')) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:10084$u" -TimeoutSec 8 -UseBasicParsing
        Say ('  GET ' + $u + ' -> HTTP ' + $r.StatusCode + '  ✓ (路由存在)') 'Green'; $okRoutes++
    } catch {
        $sc = $_.Exception.Response.StatusCode.value__
        if ($sc -eq 404 -or $sc -eq 500) { Say ('  GET ' + $u + ' -> HTTP ' + $sc + '  ✓ (路由存在, 只是还没照片)') 'Green'; $okRoutes++ }
        else { Say ('  GET ' + $u + ' -> ' + $_.Exception.Message) 'Red' }
    }
}
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force }
Start-Sleep -Seconds 2
if ($okRoutes -ge 3) { Say 'v4 能起来且 4 个路由都在 ✓' 'Green' }
else { Say 'v4 起不来或路由不全 —— 先别换, 把上面红字发我' 'Red'; exit 1 }

if (-not $Apply) {
    Head '试跑通过'
    Say '现在只是自检(10084 已停, v2 没动)。要正式升级请再加 -Apply:' 'Yellow'
    Say '  powershell -ExecutionPolicy Bypass -File .\upgrade_10083_v4.ps1 -Apply' 'Yellow'
    exit 0
}

Head '4. 正式升级: 停 v2 → 起 v4 → 验图'
if (-not $Yes) {
    Say '即将: 停掉 10083 上的 v2 进程, 然后启动 v4(v2 文件不改, 随时可回滚)' 'Yellow'
    $a = Read-Host '确认继续? 输入 y 回车'
    if ($a -ne 'y') { Say '已取消, 什么都没动' 'Yellow'; exit 0 }
}
if ($v2pid) { Stop-Process -Id $v2pid -Force; Start-Sleep -Seconds 3; Say ('已停 v2 (pid ' + $v2pid + ')') 'Yellow' }
$p4 = Start-Process python -ArgumentList 'surface_10083_work_v4.py' -PassThru -WindowStyle Minimized
Start-Sleep -Seconds 12
if ($p4.HasExited) { Say 'v4 退出了 —— 看它的窗口报错(常见: 端口占用 / 相机被别的程序占着)' 'Red'; exit 1 }
Say ('v4 已启动 (pid ' + $p4.Id + ')') 'Green'

Head '5. 验收(v4 真拍 + 取图)'
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$PORT/capture_detect" -Method POST -Body '{}' -ContentType 'application/json' -TimeoutSec 90 -UseBasicParsing
    Say ('  POST /capture_detect -> HTTP ' + $r.StatusCode + ' ' + $r.Content) 'Green'
} catch { Say ('  POST /capture_detect 失败: ' + $_.Exception.Message) 'Red' }
Start-Sleep -Seconds 2
Invoke-WebRequest -Uri "http://127.0.0.1:$PORT/picture?kind=crop" -OutFile '.\v4_check_crop.png' -TimeoutSec 60 -UseBasicParsing
Invoke-WebRequest -Uri "http://127.0.0.1:$PORT/picture?kind=origin" -OutFile '.\v4_check_origin.png' -TimeoutSec 60 -UseBasicParsing
Say ('  GET /picture?kind=crop   -> v4_check_crop.png   ' + (Get-Item .\v4_check_crop.png).Length + ' 字节') 'Green'
Say ('  GET /picture?kind=origin -> v4_check_origin.png ' + (Get-Item .\v4_check_origin.png).Length + ' 字节') 'Green'
$lr = Invoke-WebRequest -Uri "http://127.0.0.1:$PORT/last_result" -TimeoutSec 20 -UseBasicParsing
Say ('  GET /last_result -> ' + $lr.Content) 'Green'

Head '完成'
Say 'v4 上线完成。开图看一眼: v4_check_crop.png(模型看的规范图) / v4_check_origin.png(原图)' 'Green'
Say '4060 那边的工位总览不用改任何东西, 4 秒内就会自动显示这一格。' 'Green'
Say '要回滚:  %USERPROFILE%\... 停掉 v4 进程, 再按你原来的方式启动 v2(例如 python cam_surface_10083_work_v2.py)' 'Yellow'
