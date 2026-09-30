# ⑤ 消费端取证: 源头有帧, 但「检测节点/面板」里还是空的 (候选链与同源纪律)

场景(2026-09-20 一手): 产线相机链路已判定断在发布端(见 `ros-image-chain-forensics.md`),
但用户仍追问「YOLO 目标检测节点的输入图像还是没有」—— 说明断点在**消费端**:
喂检测器的那条取图路径没被修到。

## 铁律 E: 一个画面 = 多条独立候选链, 改一条只修一条 (本会话最大的坑)

同一个「真机帧」在本工程里至少被**两处独立代码**各扫一遍候选文件, 互不共享配置:

| 消费者 | 文件 | 候选常量 |
|---|---|---|
| L2 检测脚本(常驻) | `tools/ss_yolo_on_real.py` | `CAND = ("cam_rs.png","cam_fp.png","cam_latest.png","srv_cam.png","srv_cam.jpg", ...)` |
| 画布节点「输入图像」窗口 | `tools/gui/yolo_input_viewer.py` | `REAL_FILE_CANDS = ((name,label),...)` |

只改脚本那条 ⇒ 面板窗口照旧空白, 用户看到的现象**一模一样**。
**规矩: 改取图源前先 `grep -rn "cam_rs\|CAND\|候选" tools/ tools/gui/`, 把所有消费者一次改齐。**
两者的「新鲜度阈值」也是各自独立的常量(`FRESH_S` vs `REAL_FILE_FRESH_S=10s`), 要一起看。

## 铁律 F: 兜底源必须自报家门 (禁假值 / 禁混源)

产线相机未出帧时, 可以给检测器一条**兜底源**(例如本机工位相机), 但必须满足:

1. **不混源**: 绝不写进产线那条通道的文件名(`cam_rs.png` 是 RealSense 的槽位) —— 单独文件
   (`cam_local.png`) + 单独 JSON(`cam_local.json`: source/ts/res/mean/std)。
2. **来源入档**: 记录里带 `source_kind`(如 `bench_cam`) 与 `source_label`, 候选表里写清
   「备用·非产线视角」; 面板/日志/落盘 JSON 三处口径一致。
3. **顺序即优先级**: 兜底源放在候选链**最后**, 产线帧(`cam_rs/cam_fp`)一回来自动重新优先。
4. **画面自身标状态**(用户硬偏好: 他会把画面当结果): 在标注图上画一条横幅
   `源: <label> · 帧龄 x.xs · 检出 n`, 兜底源用警示色(黄), 真源用正常色(绿)。
   实现: `ImageDraw.rectangle([0,0,W,22], fill=(0,0,0))` + `dr.text((6,5), banner, fill=...)`。
5. **同源纪律**: 面板显示的源必须与检测器吃的源**严格同一条**(同一文件同一帧), 否则
   「画面里没有目标」和「检测器检出目标」会互相打脸 —— 这也是本会话把兜底文件同时加进
   两条候选链的原因。

## 铁律 G: 看不见 GUI, 也能证明面板会选中 (offscreen 直调真函数)

不要靠肉眼/截图验收 GUI 取图逻辑 —— 用 **offscreen 平台 + 直接调用被改的那个方法**:
```bash
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python - <<'PY'
import sys, types
sys.path.insert(0, "tools/gui"); sys.path.insert(0, "src")
import yolo_input_viewer as yiv                       # 被改的模块
obj = types.SimpleNamespace()                         # 假 self, 只要方法不碰其它成员
pick = yiv.YoloInputViewer._pick_real_file(obj)       # ← 真函数, 真常量
print("选中:", pick[1] if pick else None, pick[2] if pick else "")
for s in getattr(obj, "_real_cand_status", []):       # 逐条候选的真实状态
    print("   ", s)
PY
```
输出形如: `选中: 本机工位相机 (备用·非产线视角 · 与 L2 同源) | 帧龄 0.0s` +
`cam_rs.png: ⚠️ 旧帧 88258s / cam_local.png: ✅ 新鲜 0.0s` ⇒ 一条命令同时证明
「新源被选中」与「旧源确实被拒」。

## 铁律 H: 帧落盘的原子写 —— 临时文件必须带图片扩展名

沿用「原子替换 + 显式 format」纪律时, `cv2.imwrite(tmp, f)` 的 `tmp` 若形如
`x.png.tmp1234`(无图片扩展名) 会直接抛:
`cv2.error: could not find a writer for the specified extension in function 'imwrite_'`
⇒ 写 `x.png.tmp<pid>.png` 再 `os.replace` (PIL 侧同理: `im.save(tmp, format="PNG")` 必须显式给 format)。
(这是每日 0.5s 一帧的取图小进程第一次就踩到的报错, 两行就能修, 但会白白烧一轮。)

## 铁律 I: 设备独占 —— 文件兜底与「直读设备」的源不能同时开

取图小进程持续 `open(/dev/video0)` 时, GUI 面板下拉里那条
「💻 本机摄像头 (UVC 直读 `/dev/video0`)」会**打不开**(UVC 常见单打开者)。
⇒ 兜底走**文件**那条(与检测器同源), 并明确告知用户**不要选直读设备那条**。

## 铁律 J: 改 GUI 代码后的重启要防「双实例」

- 重启: `systemctl --user restart zmax-studio` (改 `tools/gui/*.py` 后必做, 无热载)。
- 陷阱: 桌面上**另一个**自行启动的 studio 实例会继续跑旧代码, 用户很可能正看着它 ⇒
  他的现象「我照旧看不到」不是没修好。
- 判据(区分两个实例): `cat /proc/<pid>/cgroup` —— 服务实例落在
  `.../app.slice/zmax-studio.service`, 会话实例落在 `.../session.slice/org.gnome.Shell@x11.service`;
  `systemctl --user show zmax-studio -p MainPID` 拿权威 PID。
- 收尾: 确认 `ps -eo pid,etime,cmd | grep studio.py` **只剩服务那个**, 再回话。

## 判据速查 (消费端)
| 现象 | 结论 |
|---|---|
| 检测脚本改了源, 面板窗口照旧空 | 面板有**自己**的候选链(`yolo_input_viewer.py`)未改 |
| 面板/记录里没有 source 标签 | 兜底源没自报家门 ⇒ 违反禁假值/禁混源 |
| 标注图无横幅 | 画面不自解释(用户会把画面当结果) |
| `imwrite` 报 no writer for extension | 临时文件缺图片扩展名(用 `.tmp<pid>.png`) |
| 重启后现象不变 | 桌面另有旧 studio 实例(查 `/proc/<pid>/cgroup`) |
