AOI 两路升级到 v5 上线包 (2026-09-27)
================================================================
目标机器: 工控机 192.168.23.23   程序目录: D:\xspace\ultralytics_AOI
通道端口: 不变 —— 表面还是 10083, 金手指还是 10082 (上层调用方零改动)
旧程序:  一个字都不改(出问题原样回旧版)

一、包里有什么
  surface_10083_work_v5.py        表面 10083 的 v5
  cam_finger_10082_work_v5.py     金手指 10082 的 v5
  upgrade_aoi_v5.ps1              上线脚本(自检 / 试跑 / 正式升级 三合一)
  *.sha256                        校验值(脚本自动核对)

二、v5 相对旧版改了什么
  1) 不检测的时候不再堆图(老倪的要求):
     · GET /picture?grab=1 (只看一眼 / 工位总览的「拍帧」)  → 图只留内存, **不写盘**
     · POST /capture_detect (真检测)                        → 照旧写盘(模型要读文件), 写完按上限清旧图
     · 想看却要存一张: GET /picture?kind=origin&grab=1&save=1
     · 诊断图(标注图/legacy)默认不写, 要写设环境变量 AOI_SAVE_DEBUG=1
     · 保留上限(张): AOI_KEEP_CANON(默认 400) / AOI_KEEP_ORIGIN(默认 120); 超了自动删最旧的
  2) 取图走内存: GET /picture 不再读磁盘(更快, 也避免"文件被删了就没图")
  3) 新增两个自查口:
     GET  /storage   → 每类图多少张 / 占多少 MB / 上限是多少 / 内存帧多大
     POST /prune     → 立刻按上限清一次(不检测时段跑一下, 磁盘就下来了); GET /prune 只预览不删
  4) 其它一律不变: 端口、POST /capture_detect 的回执 {"code":200,"msg":"success"}、
     /picture?kind=...、/last_result、/crop_info、(金手指还有 /region) 全部保持原样

三、怎么上(在你那个 PS D:\xspace\ultralytics_AOI> 里)
  1) 只自检(什么都不改):
       iwr http://192.168.23.50:8794/v5/upgrade_aoi_v5.ps1 -OutFile upgrade_aoi_v5.ps1
       powershell -ExecutionPolicy Bypass -File .\upgrade_aoi_v5.ps1 -CheckOnly
  2) 试跑(把 v5 起在 10084/10085, **不碰产线两口也不停旧程序**):
       powershell -ExecutionPolicy Bypass -File .\upgrade_aoi_v5.ps1
  3) 正式升级(停旧 → 起 v5 → 两路各真拍一张, 会先问你一句 y):
       powershell -ExecutionPolicy Bypass -File .\upgrade_aoi_v5.ps1 -Apply
       (不想被问就加 -Yes)

四、验收判据
  · 工位总览页 http://127.0.0.1:8793/station : 金手指 / 表面 两格 4 秒内出图(实时推流, 帧龄随图走)
  · 当面查:  curl http://192.168.23.23:10083/storage      → 看张数/占用
              curl http://192.168.23.23:10083/last_result   → 判决 OK/NG + 缺陷
              curl "http://192.168.23.23:10083/picture?kind=crop" -o s.jpg   → 模型看的规范图
  · 不检测时不再增图: 连点几次「拍帧」, /storage 的张数**不应该增加**

五、回滚(10 秒)
  停掉 v5 进程:  Get-NetTCPConnection -LocalPort 10083 -State Listen | %{ Stop-Process -Id $_.OwningProcess -Force }
  (10082 同理), 再按你原来的方式启动旧程序即可 —— 旧文件从没被改过。
  注意: 相机是独占设备, 同一路不能同时开两个程序(脚本会先停再起)。

六、可选调参(环境变量, 启动前设)
  AOI_KEEP_CANON=400    规范图最多留多少张
  AOI_KEEP_ORIGIN=120   原图最多留多少张
  AOI_SAVE_DEBUG=1      额外写标注图/legacy 图(排查用, 平时别开)
