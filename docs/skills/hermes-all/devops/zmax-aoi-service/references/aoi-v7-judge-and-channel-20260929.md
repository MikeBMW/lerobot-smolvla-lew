# AOI 判据图口径 (工控机 v7) + 反向通道排障 (2026-09-29)

## 一、落盘/展示的 topview = 「判据图」口径 (工控机程序 v7, 只改 10082)

老倪: 「工控机的金手指…点击请求检测后, 在工控机保存的 topview图片, 不是我在判据图的样子; 改成判据图的样子」

**差在哪(实测量)**: 改前 topview = **960x960 方图**(1455x70 条带纵向拉 ~13.7 倍填满方框);
网页判据图 = **900x332**(原比例条带 + 纵向×2 + 反倾角 + 定尺)。同一张原图两种口径 ⇒ 肉眼两张图。

**修法**: 把 4060 侧 `tools/aoi_exposure_fix.py` 口径**逐条移植**进工控机 `render_judge()`:
过曝带切除 → 只留金手指条 → 列方向裁死白列 → 短边×2 → 按实测倾角反旋(白底) → 定尺 **900x332**。
落盘 + `?kind=crop|topview` 都给判据图; `/crop_info.judge` 出台账
(保留行/切过曝行数/列裁区间/倾角/定尺/饱和比); 渲染失败**回退+打印警告**, 不硬裁一张错的。

- ⚠️ 灰度加权必须 `0.299R+0.587G+0.114B`(进出各转一次颜色); 喂 BGR 会**裁错行**(4060 侧踩过)。
- ✅ **模型输入逐位不变**: YOLO 仍吃 960x960 模板法规整图(`imgsz=960` ⇒ 召回不受影响), 另存
  `Finger_ModelIn_W960_H960_No_*.png` 并送检; `/last_result` 同时报 `topview`(人看的=判据图) 与
  `model_input`(模型吃的)。**改"人看的图"时绝不动"模型吃的图"**, 两者都落盘+进台账。
- `Finger_ModelIn_*` 要加进 `_PRUNE_PATTERNS`, 否则新文件无限堆。

**验收口径(可复现, 别只看尺寸)**: 工控机 `?kind=crop` vs 4060 网页判据图帧 → **r≥0.98**
(实测 0.9847, 行剖面 0.9971; 两帧差几秒, 场景静止); 离线对同源原图 → r≥0.99(实测 0.9973)。
工控机侧文件尺寸自检(经反向通道): `saved_topview=900x332` ✅。

**离线契约测试**: `cd ~/aoi_v4 && ~/zmax_rel/gui-venv311/bin/python test_v7_judge_offline.py`
桩相机喂**真实原图**(`?kind=origin` 存下的那张) + 桩 detector **记录它被喂了哪张文件** ⇒ 硬证"模型输入没变"。
桩的三坑: ①桩路比真相机多一道去马赛克(桩喂的是已处理好的 PNG) ⇒ 它自测的倾角会偏(-1.50° vs 真值 -0.75°),
直调对比必须用**真相机 /region 的实测倾角**; ②桩会**原地改**你传进去的像素数组(直调要重新 imread 一份);
③离线无监听端口 ⇒ `PORT_TO_DETECT_TYPE["80"]` 要映射一下, 否则 `/capture_detect` 回 400。

**交付件** `docs/deliver/v7/`(程序 + `judge_render.py` + 离线测试 + SHA256, 与场侧 SHA256 逐位一致);
报告 `reports/aoi/topview_judge_v7_20260929.md`。回滚: 场侧 `cam_finger_10082_work_v6.py.bak`(=真 v6),
仓库 `docs/deliver/v6/cam_finger_10082_work_v6.py`。

**⚠️ 列裁是逐帧自适应的, 不要拿不同帧的长度差异当 bug**: `trim_x` 按"本帧列饱和>60%"裁死白列
⇒ 同一台件不同帧可能给出 **12 根 vs 21 根**金手指(实测: 现场那帧右端过曝 ⇒ x_span[441,1311]=870px=12 根;
同一程序另一帧 ⇒ x_span[440,1896]=1456px=全宽 21 根)。**判 bug 必须同帧比**: 同帧下工控机与网页判据图
的列裁区间/节距/上取景逐项吻合(实测同尺寸 900x332、节距均 73px、均 12 根、死白行剖面逐带吻合,
灰度相关 0.9841, 亚像素位移仅 0.25px, 残差只在高对比边缘=JPEG 重编码)。

## 二、反向通道"死了" ≠ agent 死了 (三故障, 排障顺序照抄)

症状: `aoi_remote_deploy.py` 卡「通道没回执」; `aoi_watch.sh` 报「agent 已 N 分钟没轮询」;
而 AOI 产线本身正常(10082/10083 由工控机自己的分钟任务托管)。**先别信"agent 死了"**:

1. `sudo ss -ltnp | grep 8794` → hub 在不在? 手工起的断一次就没了(通道就"死"了)
   ⇒ 已建 `zmax-agent-hub.service`(enabled, Restart=always)。
2. 抓包看**它到底发了什么**:
   `sudo timeout 20 tcpdump -A -s 0 -n -i <产线网卡> 'host 192.168.23.23 and port 8794' | grep -aE 'GET|HTTP/|403'`
   实测客户端每 5s 都在 `GET /agent/cmd?t=ZMAX_AOI_KeepAlive`, 而我们回 **403 token 不对**
   ⇒ **客户端活着, 是主节点这头拒它**。两端 token 可能不一致 ⇒ hub 支持多 token(`--token a,b`), 两个都认。
3. 队列若还在 `/tmp`: 服务以 root 跑、队列属主是 ubuntu ⇒ root 重写 sticky 目录下他人文件被内核
   `fs.protected_regular` 拒(`PermissionError: /tmp/zmax_agent_cmd.jsonl`) ⇒ 队列**取不走**, 表象就是"通道断"。
   运行态统一搬 `~/zmax_data/agent_hub/`(`cmd.jsonl`/`out/`/`hub.log`/`beat`; 旧的 `/tmp/zmax_agent_beat` 仍写,
   兼容 `aoi_watch.sh`)。同一坑的变体: 工具里的 `OUT_DIR` 必须与 hub 一致, 否则"命令跑了但收不到回执"(假超时)。

- 取回执一行命令: `./gui-venv311/bin/python tools/station_cmd.py "<PowerShell>"`;
  回执里 `whoami` = `nt authority\system` ⇒ 计划任务真的跑起来了(不是用户会话里跑)。
- 教训: **通道健康要用"它发来的请求"判**, 不能用日志行数/本机自检判(本机 curl 会把 beat 探活;
  看门狗脚本已特意排除本机来源, 但抓包最硬)。
- 部署被卡时**别急着改程序**: 先确认通道, 再跑 `tools/aoi_remote_deploy.py`(它自己会核 SHA256/备份/验收/回滚)。
- ⚠️ 通道断时手工"补下载"会**不留备份就覆盖场侧文件**(那个 `iwr -OutFile` 是直接覆盖) ⇒ 恢复通道后
  重跑一次 deployer 才有真 `.bak`; 否则 `.bak` 可能是新版本(假备份, 回滚等于没回滚)。

---

## 🆕 v10 (2026-09-30): 只落判据图一张 + 模型吃 960 同帧派生图(不落盘) + 通道事故三修

老倪口径: `Finger_ModelIn_*` 不要了; 保留 `Finger_TopView_W900_H332_*`; 要确认模型吃的是哪张。

**实测结论**: 改前模型吃的是 `Finger_ModelIn_W960_H960_*`(960 方图 = 训练口径), topview 只看不喂。
 v10 起: 只落**判据图一张**; 模型吃**同帧派生的 960x960**(与 v6/v7 逐位同口径 ⇒ 召回不变), 写 %TEMP% 检测完即删;
 `/last_result` 明写 `model_input` / `model_input_kind` / `judge` / `topview` + 影子对照(判据图压 960, 前 10 张, 判决取并集)。

**四条硬教训(每条都现场踩过, 别再犯)**:
1. **别让模型直接吃判据图**: 把 900x332 原样喂 `detector.detect()` ⇒ 工控机 app 检测卡死(CPU 空转、几分钟不返回、
   incoming 不落图、%TEMP% 堆 90+ 临时图); 同一张图换 venv 解释器单独跑 0.7s ⇒ 差异在 app 那个解释器/环境 ⇒ **不可用**。
   要"模型吃判据图"就**压成方形**再喂(方形安全), 或只喂同帧派生的训练口径图。
2. **临时图绝不写在高频调用的路径上**: v9 把临时图写进 `GrabAndSaveImage`, 而"只看一眼"的 grab(页面 0.5s 一次)
   也走这个函数 ⇒ 9 分钟泄漏 2180 张。**只在校验通过、会入队的那条路径上写**, 并且每次先 `_sweep_temp()` 清 60s 以上的残留。
3. **经反向通道下发的命令必须有界**: agent 循环是"一问一答+串行+**无超时**", 一条会挂的命令(清理类最容易)就能堵死通道
   (实测 20+ 分钟零回执), 而 watchdog/keepalive 只看"进程在不在" ⇒ **不会自愈**。修法: 命令里用
   `Start-Job { ... }` + `Wait-Job -Timeout N` 包裹; 机器侧 `zmax_keepalive.ps1` rev6 会杀掉挂在 `zmax_cmd.ps1`
   上超过 10 分钟的子进程(只在 agent 重启后拉取生效)。
4. **部署器验收**: `http_get` 必须保留 HTTP 状态码(走 `except Exception` 会把 404 变成 0 ⇒ 认不出
   "合法 404 尚无检测结果" ⇒ 首帧推理慢就假失败并**误回滚**); 验收判据只看 `--only` 指定的那一路,
   另一路只报状态(10083 自己抽风不该回滚 10082 的修复)。

**现场实测(v10)**: 判决 1611ms · %TEMP% 残留 25→0 · 目录只剩 Image/CropNatural/TopView 三条 · 离线 `test_v10_temp_leak.py` 全绿。

### 往工控机送脚本/大东西: 走 hub 静态目录, 别用超长命令 (2026-09-30 踩过)
- hub 是 `python tools/agent_hub.py --port 8794 --dir /home/ubuntu/aoi_v4/deliver` ⇒ 机器上 `iwr 'http://192.168.23.50:8794/v6/<文件>' -OutFile <文件>` 就能取
  (keepalive 自己就是这么更新自己的)。所以: 要在机器上跑的新脚本, **先落到 `/home/ubuntu/aoi_v4/deliver/v6/` 再 iwr 下去跑**, 不要拼巨型命令。
- 经通道下发的**单条命令 ~3KB 就会被弄坏**(实测 base64 内嵌 3KB 脚本 ⇒ `$b64` 变空、文件写出 0 字节)。脚本超 1KB 一律走 hub 文件。
- 本地 `write_file` 对"本会话没读过"的已存在文件会拒写(结果是静默没改) ⇒ 改已有文件先 `read_file`, 或直接换个新文件名。
- 发到机器前先本地 `python3 -m py_compile` 过一遍: 文档字符串里的 `\x`、`\W` 这类转义会在机器上报 SyntaxError, 白跑一轮。
- 想核对"模型到底看不看得见": 在机器上跑 `ab_check_defect_v2.py`(本 skill 同目录已随 hub 发布) —— 它对最新一帧的判据图/原图/960 送检图各跑一遍真模型, 不改文件、不占端口。
- 停/起在役程序的正确姿势: 局部起法 = `$sh=New-Object -ComObject WScript.Shell; $sh.Run('cmd /c cd /d <dir> && venv\Scripts\python.exe <prog> > <log> 2>&1',0,$false)`(与 keepalive 一致)
  —— 直接 `Stop-Process` 掉在役 python 后, **keepalive 不一定 1 分钟内拉起来**(实测 75s 未回) ⇒ 手工起一把, 再 `iwr /storage` 验 200。
