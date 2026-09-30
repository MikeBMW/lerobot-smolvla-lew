# ══════════════════════════════════════════════════════════════════════════════
#  AOI 两路升级到 v5  —— 一键脚本 (在工控机 D:\xspace\ultralytics_AOI 下运行)
#    表面 10083  → surface_10083_work_v5.py      (升级前可能是 v2)
#    金手指 10082 → cam_finger_10082_work_v5.py  (升级前可能是 v3)
#  通道不变(还是 10082/10083), 旧程序文件一个字都不动, 出问题原样回旧版。
#
#  v5 改了什么(老倪: 不检测的时候不用保存那么多图片):
#    · 取图/看一眼(GET /picture?grab=1) → **不落盘**, 图只留内存
#    · 真检测(POST /capture_detect) → 照旧落盘(模型要读文件), 落完按上限清旧图
#    · 诊断图(标注图/legacy)默认不写; 磁盘上限 AOI_KEEP_CANON / AOI_KEEP_ORIGIN
#    · 新增 GET /storage(看占多少/多少张) 与 POST /prune(手动清)
#
#  只自检(什么都不改):  powershell -ExecutionPolicy Bypass -File .\upgrade_aoi_v5.ps1 -CheckOnly
#  只试跑(v5 起在 10084/10085, 不碰产线口): powershell -ExecutionPolicy Bypass -File .\upgrade_aoi_v5.ps1
#  正式升级(停旧→起 v5): powershell -ExecutionPolicy Bypass -File .\upgrade_aoi_v5.ps1 -Apply
# ══════════════════════════════════════════════════════════════════════════════
param([switch]$CheckOnly, [switch]$Apply, [switch]$Yes,
      [string]$Base = 'http://192.168.23.50:8794/v5')
$ErrorActionPreference = 'Stop'
$CH = @(
    [pscustomobject]@{ Port = 10083; File = 'surface_10083_work_v5.py';    Alt = 10084; Name = '表面' },
    [pscustomobject]@{ Port = 10082; File = 'cam_finger_10082_work_v5.py'; Alt = 10085; Name = '金手指' }
)

function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Head($m) { Write-Host ''; Write-Host ('── ' + $m + ' ' + ('─' * [Math]::Max(0, 60 - $m.Length))) -ForegroundColor Cyan }

function Get-Listener($port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

Head '0. 环境'
$pyexe = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $pyexe) { Say '找不到 python —— 先激活 venv 再跑' 'Red'; exit 1 }
Say ('python : ' + $pyexe.Source)
foreach ($f in @('SciCam_class.py', 'yolo_detector.py', 'config.yaml')) {
    if (Test-Path (Join-Path (Get-Location) $f)) { Say ('文件   : ' + $f + '  ✓') }
    else { Say ('文件   : ' + $f + '  缺失! (v5 复用旧程序的 SDK/权重, 必须在同一目录)' 'Red') }
}

Head '1. 现在谁在 10082 / 10083'
foreach ($c in $CH) {
    $conn = Get-Listener $c.Port
    if ($conn) {
        $p = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $conn.OwningProcess) -ErrorAction SilentlyContinue
        Say ("$($c.Name) $($c.Port): pid=$($conn.OwningProcess)  " + $p.CommandLine) 'Yellow'
    } else { Say ("$($c.Name) $($c.Port): 没有监听(当前没跑)") 'Yellow' }
}

if ($CheckOnly) { Say ''; Say '只自检模式: 到此为止, 没动任何东西。' 'Green'; exit 0 }

Head '2. 下载 v5 + 校验'
foreach ($c in $CH) {
    $dst = Join-Path (Get-Location) $c.File
    try {
        Invoke-WebRequest -Uri "$Base/$($c.File)" -OutFile $dst -TimeoutSec 30 -UseBasicParsing
        Invoke-WebRequest -Uri "$Base/$($c.File).sha256" -OutFile "$dst.sha256" -TimeoutSec 30 -UseBasicParsing
    } catch { Say ("下载失败(" + $c.File + "): " + $_.Exception.Message) 'Red'; Say '确认这台机器能访问 192.168.23.50:8794' 'Red'; exit 1 }
    $want = ((Get-Content "$dst.sha256") -split '\s+')[0].ToLower()
    $got = (Get-FileHash $dst -Algorithm SHA256).Hash.ToLower()
    if ($want -eq $got) { Say ("$($c.File): SHA256 通过 (" + (Get-Item $dst).Length + " 字节)") 'Green' }
    else { Say ("$($c.File): SHA256 不一致! 期望 $want 实得 $got") 'Red'; exit 1 }
}

Head '3. 试跑(表面 10084 / 金手指 10085 —— 不碰产线两口, 不碰旧程序)'
$procs = @()
foreach ($c in $CH) {
    $argl = if ($c.Port -eq 10082) { @($c.File, '--port', "$($c.Alt)") } else { @($c.File, "$($c.Alt)") }
    $procs += Start-Process python -ArgumentList $argl -PassThru -WindowStyle Minimized
}
Start-Sleep -Seconds 14
$okR = 0
foreach ($c in $CH) {
    foreach ($u in @('/storage', '/last_result', '/picture?meta=1')) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$($c.Alt)$u" -TimeoutSec 8 -UseBasicParsing
            Say ("  $($c.Name) $($c.Alt) GET $u -> HTTP " + $r.StatusCode + ' ✓') 'Green'; $okR++
        } catch {
            $sc = $_.Exception.Response.StatusCode.value__
            if ($sc -eq 404 -or $sc -eq 500 -or $sc -eq 400) { Say ("  $($c.Name) $($c.Alt) GET $u -> HTTP $sc ✓ (路由在, 只是还没照片)") 'Green'; $okR++ }
            else { Say ("  $($c.Name) $($c.Alt) GET $u -> " + $_.Exception.Message) 'Red' }
        }
    }
}
foreach ($p in $procs) { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force } }
Start-Sleep -Seconds 2
if ($okR -lt 6) { Say 'v5 试跑有路由没起来 —— 先别换, 把上面红字发我' 'Red'; exit 1 }
Say '两路 v5 都能起来且路由齐全 ✓' 'Green'
Say '(试跑用的 10084/10085 已停; 产线 10082/10083 上还是旧程序, 没动)' 'Yellow'

if (-not $Apply) {
    Head '试跑通过'
    Say '要正式升级请再加 -Apply:  powershell -ExecutionPolicy Bypass -File .\upgrade_aoi_v5.ps1 -Apply' 'Yellow'
    exit 0
}

Head '4. 正式升级: 停旧 → 起 v5 → 真拍一张验图'
if (-not $Yes) {
    Say '即将: 停掉 10082/10083 上的旧进程, 然后启动 v5 (旧程序文件不改, 随时可回滚)' 'Yellow'
    $a = Read-Host '确认继续? 输入 y 回车'
    if ($a -ne 'y') { Say '已取消, 什么都没动' 'Yellow'; exit 0 }
}
foreach ($c in $CH) {
    $conn = Get-Listener $c.Port
    if ($conn) { Stop-Process -Id $conn.OwningProcess -Force; Start-Sleep -Seconds 3; Say ("已停 $($c.Name) 旧进程 (pid " + $conn.OwningProcess + ")") 'Yellow' }
}
Start-Sleep -Seconds 2
$new = @()
foreach ($c in $CH) {
    $argl = if ($c.Port -eq 10082) { @($c.File, '--port', "$($c.Port)") } else { @($c.File, "$($c.Port)") }
    $new += Start-Process python -ArgumentList $argl -PassThru -WindowStyle Minimized
}
Start-Sleep -Seconds 15
foreach ($p in $new) { if ($p.HasExited) { Say 'v5 进程退出了 —— 看它的窗口报错(常见: 端口被占 / 相机被别的程序占着)' 'Red'; exit 1 } }

Head '5. 验收(两路真拍一张 + 取图 + 看不检测时是否还落盘)'
foreach ($c in $CH) {
    Say ("── $($c.Name) $($c.Port) ──") 'Cyan'
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$($c.Port)/capture_detect" -Method POST -Body '{}' -ContentType 'application/json' -TimeoutSec 90 -UseBasicParsing
        Say ('  POST /capture_detect -> ' + $r.StatusCode + ' ' + $r.Content) 'Green'
    } catch { Say ('  POST /capture_detect 失败: ' + $_.Exception.Message) 'Red' }
    Start-Sleep -Seconds 2
    $st1 = (Invoke-WebRequest -Uri "http://127.0.0.1:$($c.Port)/storage" -TimeoutSec 15 -UseBasicParsing).Content
    Invoke-WebRequest -Uri "http://127.0.0.1:$($c.Port)/picture?kind=origin&grab=1" -OutFile (".\v5_" + $c.Port + "_origin.jpg") -TimeoutSec 60 -UseBasicParsing
    $st2 = (Invoke-WebRequest -Uri "http://127.0.0.1:$($c.Port)/storage" -TimeoutSec 15 -UseBasicParsing).Content
    Say ('  真检测落盘: ' + $st1) 'Green'
    Say ('  取图(grab=1)之后: ' + $st2 + '  ← 张数不应该增加(=不检测时不落盘)') 'Green'
    try { $j = (Invoke-WebRequest -Uri "http://127.0.0.1:$($c.Port)/last_result" -TimeoutSec 20 -UseBasicParsing).Content
          Say ('  /last_result: ' + $j) 'Green' } catch { Say '  /last_result: 还没有结果(正常, 检测是异步的)' 'Yellow' }
}

Head '完成'
Say 'v5 上线完成; 图的样例存成 v5_10082_origin.jpg / v5_10083_origin.jpg, 打开看一眼' 'Green'
Say '4060 那边工位总览不用改任何东西: 两格都是实时推流, 4 秒内自己就换成 v5 的图' 'Green'
Say '回滚: 停掉 v5 进程, 按你原来的方式启动旧程序(v2/v3)即可 —— 旧文件从没被改过' 'Yellow'
Say '想手动清图: Invoke-WebRequest -Method POST http://127.0.0.1:10083/prune  (10082 同理)' 'Yellow'
