表面检测通道 10083 升级到 v4 —— 上线包 (2026-09-27)
================================================================
目标机器: 工控机 192.168.23.23   程序目录: D:\xspace\ultralytics_AOI
通道端口: 还是 10083 (上层调用方不用改任何东西)
v2 文件: 一个字都不改 (出问题原样回 v2)

一、包里的东西
  surface_10083_work_v4.py          新程序(独立文件, 不覆盖 v2)
  surface_10083_work_v4.py.sha256   校验值(下载后必须核对)
  upgrade_10083_v4.ps1              上线脚本(自检 / 升级 二合一)

二、在哪台机器上操作
  在你正开着的那个 PowerShell (PS D:\xspace\ultralytics_AOI>, 已激活 venv) 里操作即可。
  工控机能直接访问这台 4060 工作站的 192.168.23.50:8794 (同一网段, 本机无防火墙)。

三、第一步: 只自检 (什么都不改, 安全)
  1) 把脚本拉下来:
       iwr http://192.168.23.50:8794/upgrade_10083_v4.ps1 -OutFile upgrade_10083_v4.ps1
  2) 自检:
       powershell -ExecutionPolicy Bypass -File .\upgrade_10083_v4.ps1 -CheckOnly
  → 会打印: python/依赖/SDK 文件是否齐、10083 现在是不是 v2 在跑(打印它的 pid 和命令行)、
    /picture 是否已存在。**不会启动、不会停止任何东西。**

四、第二步: 试跑 v4 (起在 10084, 仍然不碰 v2 / 不碰 10083)
       powershell -ExecutionPolicy Bypass -File .\upgrade_10083_v4.ps1
  → 下载 v4 + 核对 SHA256 + 起在 10084 验证 4 个路由都在, 然后自动停掉 10084。
  → 到这一步结束, v2 依然是唯一在 10083 上跑的程序。

五、第三步: 正式升级 (停 v2 → 起 v4 → 真拍一张验图)
       powershell -ExecutionPolicy Bypass -File .\upgrade_10083_v4.ps1 -Apply
  → 会先问一句 "确认继续? 输入 y" 再停 v2(不想被问就加 -Yes)。
  → 起来后自动 POST /capture_detect 真拍一张, 并把两张图存到当前目录:
       v4_check_crop.png    = 模型真正看到的规范图(1280×1280, 保比例 letterbox)
       v4_check_origin.png  = 原图(相机全幅)
  → 打开看一眼就知道成没成。

六、验收判据 (在 4060 这台机器上)
  工位总览页 http://127.0.0.1:8793/station 的「🔍 表面检测」那一格:
    · 4 秒内出现画面(原来写"没有取图路由"的红字会消失)
    · 标题栏变成: 帧龄 x.xs · 拍照 hh:mm:ss · 模型看的规范图 kind=crop · 上轮判定 OK/NG (n 缺陷 · 推理 xxms)
  命令行也可以直接查:
       curl "http://192.168.23.23:10083/picture?meta=1"    # JSON: 文件/大小/规范图指标/上轮判决
       curl "http://192.168.23.23:10083/last_result"       # 判决: verdict OK/NG + defects[] + 推理耗时
       curl "http://192.168.23.23:10083/crop_info"         # 规范图亮度/清晰度(上线核对曝光用)

七、v4 相对 v2 的升级点 (只加不减, 产线调用口径完全不变)
  · POST /capture_detect  回执与 v2 完全一致 {"code":200,"msg":"success"} —— 上层不用改
  · 新增 GET /picture     ?kind=crop(默认, 规范图) | origin(原图) · ?meta=1 只回 JSON · ?grab=1 才真拍
  · 新增 GET /last_result 判决: verdict OK/NG · count · defects[{class_name,conf,bbox}] · ms
  · 新增 GET /crop_info   规范图指标: 尺寸/letterbox 比例/亮度 mean/对焦清晰度 → 核曝光用
  · 相机常驻 + 单 worker 异步队列: /capture_detect 秒回, 模型只加载一次(原版实测推理 ~7.8s)
  · 规范图口径 = config.yaml housing 的 yolo.imgsz=1280, 按比例 letterbox(表面是全幅检测, 不拉伸)
  · 判决/图/指标全部落盘 ./surface_images/ + 终端打印自证

八、回滚 (10 秒)
  停掉 v4 进程(脚本启动的是最小化窗口, 关掉它; 或 Get-NetTCPConnection -LocalPort 10083 找到 pid 后
  Stop-Process -Id <pid> -Force), 然后按你原来的方式启动 v2:
       python cam_surface_10083_work_v2.py
  v2 的文件从没被改过, 相机、端口、上层调用都回到升级前。

九、注意
  · 相机是独占设备: v2 和 v4 不能同时开着拍。切换时必须先停一个。
  · 同一时刻只有一个程序能占 10083。v4 起不来并打印"端口已被占用" = v2 还在跑。
  · 首次上线请核对曝光: GET /crop_info 的 mean 应在 60~200; 偏暗调环境变量 SURFACE_EXPOSURE_US(默认 80000)。
