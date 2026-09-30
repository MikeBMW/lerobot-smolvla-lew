# ⑥ 源切换 · 兜底不抢源 · 解码格式 · 只起相机节点 (2026-09-21 一手)

接 `frame-consumer-chain-and-fallback-source.md` 之后的一轮: 用户要「在**本机摄像头**和 **RealSense**
之间来回切换」。过程中把三个消费端、一条优先级判据、一个"已连接却没图"写实了, 并第一次用
**只起相机节点**的方式把产线真图拿回来。

## 铁律 K: 相机画面不止两个消费者, 是三个 (每个失败模式都不同)

| 消费者 | 文件 | 取图逻辑 | 典型失败模式 |
|---|---|---|---|
| L2 检测脚本(常驻) | `tools/ss_yolo_on_real.py` | `CAND` 文件候选链 | 候选链里没有可用源 → 打印"无真机图像帧" |
| 画布「输入图像」窗口 | `tools/gui/yolo_input_viewer.py` | `REAL_FILE_CANDS` + srv/仿真/usbcam 三路下拉 | 候选链未同步改 → 窗口空白 |
| 硬件工具箱「摄像头实时画面」 | `tools/gui/studio.py` (`HardwareModule`) | **只**轮询远端快照 `https://datadrive.world/api/snapshot/latest` | 远端不可达 → 报"连接失败/无图", **与相机在不在无关** |

⇒ 用户说"还是没图"时, 先 `grep -rn "cam_rs\|CAND\|snapshot/latest" tools/ tools/gui/`, **把所有消费者列齐**再改。

## 铁律 L: 兜底源禁止"抢源" —— 优先级必须绝对, 不能按"谁更新"

- 现象(实测): 本机相机帧 2Hz、产线帧 ~1Hz; 原判据「谁新 ≥0.5s 就换谁」⇒ 画面在两路之间**来回跳**,
  检出数跟着跳(同一秒 2 个 peg → 0 个 peg)。
- 修(三处同口径): 只要存在**新鲜的产线帧**(`age ≤ FRESH_S*4`), 就用产线帧; 兜底源仅当前者全不可用时入选。
  ```python
  local = [c for c in cands if basename(c.path) == "cam_local.png"]
  real  = [c for c in cands if basename(c.path) != "cam_local.png"]
  best  = min(real or local, key=lambda c: (idx, age))   # 产线源绝对优先, 再按幼新/次序
  ```
  三个消费端各自维护 `best_real / best_local`, 返回 `best_real or best_local`。

## 铁律 M: 解码格式写死 = "显示已连接, 但没有图像"

- 症状: 面板状态栏"🟢 已连接", 画面框空白。
- 根因: 渲染写死 `pm.loadFromData(data, "JPG")`, 而新增的本地回退帧是 **PNG** → 返回 False、
  `pm.isNull()` → 静默不显示 (`except: pass` 把失败也吞了)。
- 修: 先让 Qt 按**文件魔数**自动识别, 再按显式格式兜底; 仍失败要**如实上屏**:
  ```python
  ok = pm.loadFromData(data)
  if not ok:
      for fmt in ("JPG", "PNG", "BMP"):
          if pm.loadFromData(data, fmt): ok = True; break
  if ok and not pm.isNull(): self.view.setPixmap(...)
  else: self.view.setText(f"⚠️ 帧解码失败 ({len(data)} 字节) — 格式未识别")
  ```
- 自证(offscreen, 不用肉眼看窗口):
  ```python
  from PyQt5.QtGui import QGuiApplication, QPixmap
  app = QGuiApplication([])                      # QPixmap 必须先有 GUI 应用实例, 否则 core dump
  png = open("~/zmax_ss_remote/cam_local.png","rb").read()
  a = QPixmap(); print(a.loadFromData(png, "JPG"), a.isNull())   # 旧口径 → False True (=复现)
  b = QPixmap(); print(b.loadFromData(png), b.isNull(), b.size())# 新口径 → True False 1280x720
  ```

## 铁律 N: 面板要有「来源」切换, 且切换必须驱动候选过滤

- UI: 连接按钮旁一个 `QComboBox` = `🔁 自动 / 🎥 产线RealSense (cam_rs.png) / 💻 本机工位相机 (cam_local.png)`;
  读下拉实时值做过滤 ⇒ **已连接时下一轮轮询即换源**(1.5s), 不用断开重连。
- `pref != 0` 时**必须跳过远端探测** —— 否则用户选了本地源还要白等 4s 超时。
- 面板显示的源要与检测器吃的源**严格同一条文件**(`cam_rs.png` 两边都吃), 否则画面与检出互相打脸。
- 切换后要在状态栏写清"当前来源 + 未连接请点连接/已连接下一轮生效", 别让用户猜。

## 铁律 O: 只起「产线相机节点」拿真图 (要用户授权; 绝不顺手起整条 launch)

背景: 产线相机节点**不自启**(无 systemd 单元、无 rc.local), 机器重启后没人拉它 ⇒ 话题 0 发布者。
起整条 `start.launch.py` 会连 `/motion` 一起拉起 ⇒ 状态机可能自己跑流程 = 真机运动指令。
**只起相机节点**的步骤:
1. 从产线 launch 配置 1:1 抄参数段(色/深/点云话题、宽高、fps、`frame_id`、`publish_rate`、
   `startup_warmup_frames`)写成 `/tmp/<x>_params.yaml`, 顶层键用 `/**` 配 `ros__parameters`。
2. 脚本里 **`set +u`** —— ROS `setup.bash` 引用未绑定变量, `set -u` 会让 source 直接失败
   (`AMENT_TRACE_SETUP_FILES: 未绑定的变量`)。
3. `source /opt/ros/humble/setup.bash && source <bundle>/install/setup.bash; export ROS_DOMAIN_ID=0`
4. `setsid nohup ros2 run camera realsense_source --ros-args -r __node:=realsense_source --params-file <yaml> > /tmp/rs.log 2>&1 &`
5. 三层验收(见铁律 P) + 我这侧 `tap recv.img` 从 0 开始涨、`cam_rs.png` 帧龄秒级、std>5 真图。
6. **收尾必须交代**: 这是手工进程; 用户若之后要起整条产线程序, 先停它, 否则两进程抢设备, 产线那条起不来。

## 铁律 P: "节点起来了但不出帧"按三层查, 别被单条 WARN 带偏

1. 进程/设备: `pgrep -af realsense_source` · `ls -l /proc/<pid>/fd | grep -c /dev/video`(握着设备≠在出帧)
2. 话题真出帧: `ros2 topic hz /realsense/color/image_raw` —— **Publisher count=1 只说明有人"声明"在播**
   (advertised ≠ published); hz 空 = 没帧。
3. 设备层传感器: `python3 -c "import pyrealsense2 as rs;print([[s.get_info(rs.camera_info.name) for s in d.sensors] for d in rs.context().query_devices()])"`
   (D405 正常 = Stereo + RGB; 只剩 Stereo ⇒ 彩色传感器没枚举 → 现场拔插 USB/断电复位, 不是软件问题)。
- 反例留档: 本会话日志只有一条 `[WARN] RealSense color sensor not found, skip color option config`,
  我一度据此判定"彩色不可用", 但随后彩色流正常出帧 ⇒ **WARN 不是结论, 用 hz/收帧计数说话**。

## 判据速查 (源切换)
| 现象 | 结论 |
|---|---|
| 状态栏"已连接"但画面空 | 解码格式写死(`loadFromData(data,"JPG")` 喂 PNG) |
| 画面/检出数在产线源与本机源之间来回跳 | 兜底源抢源 ⇒ 产线帧优先必须是**绝对**判据 |
| 硬件工具箱「连接摄像头」失败 | 该面板只认远端 ECS 快照, 与相机无关; 需本地回退 |
| 换了源但面板没变 | 三处消费者没改齐 / GUI 未重启 / 桌面另有旧 studio 实例 |
