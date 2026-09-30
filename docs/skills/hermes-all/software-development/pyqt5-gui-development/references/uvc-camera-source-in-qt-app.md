# Qt 应用里接本机 UVC 摄像头当一路输入源 (2026-09-17 实战)

> 场景: 「输入图像」类窗口原本只有 真机(远端)/仿真 两路, 要加第三路「💻 本机摄像头」——
> 没连远端设备也能出**真像素**做标定/YOLO 域适应。交付前必踩的三个坑都在下面。

## 设备侧先自证 (别先改代码)

```bash
ls -l /dev/video*                                   # 多路 = 同一相机的多个 UVC 节点
for d in /sys/class/video4linux/*; do echo "$(basename $d): $(cat $d/name)"; done
lsusb | grep -iE "cam|webcam|integrated"            # 认内置相机型号
```
- 内置 RGB 相机通常在 `/dev/video0`; `/dev/video1`、`video3` 常是 UVC **metadata 节点**
  (`ffmpeg -f v4l2 -i` 报 "Inappropriate ioctl for device" = 正常, 不能取图);
  另一路 640x360 `gray` 往往是 IR / Windows Hello 相机 (会抓到近黑帧, 别误判"驱动坏了")。
- 取帧自证 (有 ffmpeg 就行, 不必装 v4l2-ctl): `ffmpeg -f v4l2 -i /dev/video0 -frames:v 1 /tmp/x.jpg`,
  再算 `mean/std` —— **std 太小 = 黑帧/无画面**; 连抓多帧比相邻帧差 = 是不是"实时在动"。
- 能力枚举: `ffmpeg -hide_banner -f v4l2 -list_formats all -i /dev/video0` (MJPG/YUYV + 分辨率表);
  MJPG 1280x720@30 一般能跑满 (3 秒 90 帧实测)。

## 坑 1: cv2 的 V4L2 后端**不能按设备名(path)打开**

- 现象: `cv2.VideoCapture("/dev/video0", cv2.CAP_V4L2)` → `isOpened()=False`,
  日志 `open VIDEOIO(V4L2): backend is generally available but can't be used to capture by name`
  (cv2 5.x 实测)。而同一条路径**不加** CAP_V4L2 (默认后端) 又能开 —— 行为随版本变, 别赌。
- 正解: 把 `/dev/videoN` 换算成**索引 N** 再打开:
  ```python
  m = re.match(r"^/dev/video(\d+)$", dev)
  cap = cv2.VideoCapture(int(m.group(1)), cv2.CAP_V4L2) if m else cv2.VideoCapture(dev)
  ```
- **cv2 必须在主线程 import 好再传给 worker 线程** (它自带 Qt 插件路径, 后台线程首导会跟主程序 Qt 打架;
  同 `pyqt-gui-auto-verification` 的 cv2/Qt 插件坑)。

## 坑 2: UVC 设备独占 + 起线程不幂等 = 设备被永久占用 ★

- 症状: 第一次切到摄像头源好好的, 之后**任何一路都"打不开摄像头"**, 重启窗口也不恢复。
- 根因: `_start_source()` 被**调了两次** (典型来源: `__init__` 里 `QTimer.singleShot(200, self._start_source)`
  + 用户在 200ms 内手切了下拉 → `currentIndexChanged` 再调一次) → 第二次把 `self._cam` 覆盖成新线程,
  **旧线程没人置 stop_flag 成了孤儿, 一直握着 `/dev/videoN`** → 独占设备谁都开不了。
- 修法 (两条都要):
  1. **入口幂等**: `_start_source()` 开头先收掉在跑的采集线程 (`stop_flag=True` + `join(timeout=1.5)` 等它 release);
  2. **停源要 join**: `_stop_source()` 里对摄像头线程 `join(timeout=1.5)` 再返回 —— 不等它 release,
     立刻切回来就会"打不开" (自愈重试要 1s, 体验上就是坏的)。
- 打开失败文案要写清两种可能: **被占用**(另一路摄像头源/别的程序在读) vs **设备号不对**, 并给出
  `ZMAX_USBCAM_DEV=/dev/videoN` 这种可改项 —— 独占冲突是用户最常遇到的。

## 坑 3: 多源窗口的"口径隔离"与"手动源保护"

- 每路源要有**独立的数据根/会话/类别表** (真机 `yolo_annot` / 仿真 `yolo_annot_sim` /
  本机 `yolo_annot_usbcam`): 仿真 `peg` 与真机光模块不是一回事, 混一个 classes.txt 训练会让语义打结。
  实现 = 上游 `root_for(source)` / `session_tag_for(source)` 加一条分支即可, 窗口侧只传 source 字符串。
- **手动选的那一路不许被自动跟随逻辑拽走**: 画布/上游切换"数据源"时会 push 窗口切源 (真机⇄仿真),
  若用户手动选了本机摄像头, 跟随逻辑必须检测当前 source 并跳过 (本次加了 `if _w.source == "usbcam": 不动它`
  + 日志说明), 否则用户会觉得"我明明选了摄像头又自己跳回去了"。
- 每路源都要有自己的**占位画面**(`waiting-<source>`): 切换瞬间先清屏 + 显示"等第一帧 + 设备名 + 这一路
  经不经过远端", 别让上一路画面残留 (同 `display-refresh-honesty-and-window-stubs-2026-09-17.md`)。
- 帧口径统一: 摄像头 BGR→RGB (`fr[:, :, ::-1]`), 与仿真/真机同一条上屏路径, 状态栏写明来源
  (设备名 + 分辨率 + 实测 FPS), **不冒充**其它源。

## 验证断言 (tools/verify_usbcam_source.py 的骨架)

1. **数据根隔离**: `len({root_for("real"), root_for("sim"), root_for("usbcam")}) == 3` + 类别表可建。
2. **下拉真的加了第 3 项**, 选中后 `source`/`annot_root`/`_session` 都跟着切。
3. **真取帧**: 拿到 ≥5 帧; 尺寸 ≥320x240; `std > 1` (不是黑屏); 首末帧平均差 > 0 (实时在动);
   实测帧率可打印 (目标 15fps 实测常 ~11fps, 正常)。
4. **上屏 + 文案**: 喂一帧假图 → `w_orig.pixmap()` 非空 + `_view_tag == "usbcam"` + 状态栏含"本机摄像头/UVC"
   且**不含** "RealSense"/"metaworld" (不冒充其它源)。
5. **手动源保护**: 窗口 source=usbcam 时调上游打开入口 (`open_input_viewer(source="real")`) → 下拉索引不变。
6. **设备释放**: 关源后轮询"能否独占打开"直到成功 (证明 join 生效); 失败说明设备泄漏。

### 测试自身两个假 FAIL (本次踩到, 已修)
- **自己的测试窗口在抢设备**: 测试里每构造一个窗口, `__init__` 的 singleShot 就会起一个采集线程 →
  紧接着由测试再起一个 grabber 必然"打不开"。对策: 只测上屏/文案的窗口把 `_start_source` 换成 no-op,
  真要抢设备的阶段之间**轮询等设备空闲**再开。
- 断言"会话名 = xxx"时忘了 `session_name()` 会**带时间戳前缀** (`s20260917_1811_usbcam`) →
  应断言 `endswith("usbcam")`。
