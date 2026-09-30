# 帧率上不去：逐条证伪（节流 vs 设备上限）

适用：ROS 相机话题实测帧率**低于其参数里配置的目标帧率**，用户要求「提高帧率/要实时」。
原则：**每一条假设都用一条只读命令排除**，全排除完才允许下「设备上限」的结论；
中途试过的**任何生产参数都必须还原并回读确认**。

---

## 0. 先确立基准：直接从发布者量，不要经由自己的 tap
```bash
# 起一个一次性 ROS 容器（网络 host + 同 domain），只读
sudo docker run --rm --network host -e ROS_DOMAIN_ID=0 \
  --entrypoint bash ros:humble-ros-base -lc \
  'source /opt/ros/*/setup.bash 2>/dev/null; timeout 20 ros2 topic hz /<color_topic> 2>&1 | grep "average rate"'
```
必须这样量，否则测到的是"你的 tap 的节流"而不是"发布者的帧率"。
**同节点的多个图像话题若帧率完全一致 → 瓶颈在该节点的主循环或设备，不在单个话题。**

## 1. 读节点真正拿到的参数（含启动下发的 params 文件）
```bash
ros2 param dump /<node>            # 或逐个 ros2 param get /<node> <p>
cat /tmp/launch_params_*           # launch 生成的实际下发文件（常有 dump 里看不到的）
```
关注：`color_fps` / `depth_fps` / `publish_rate` / `frame_timeout_ms` / `startup_warmup_frames` / `*_exposure`。
**若配置值明显高于实测值 → 不是配置写低了，继续往下证伪。**

## 2. 判断能不能运行时改（大多数厂商节点：不能）
```bash
ros2 param set /<node> <p> <v>   # 设完立刻再量 topic hz
```
- ⚠️ **类型必须严格匹配**：数值参数多为 `DOUBLE`，传整数会报
  `Wrong parameter type, expected 'Type.DOUBLE' got 'Type.INTEGER'`（传 `15.0` 而非 `15`）。
- 实测：`publish_rate 5→15.0`、`color_fps 15→30`、`depth_fps 15→30`、
  关自动曝光 + 曝光压到极小、点云 `max_points 50000→0` —— **帧率一律无变化**。
- **结论：这类节点只在启动时读参数**（参数改了 `param get` 回读是新值，但设备端没重新配置）。

## 3. 排除链路 / 算力 / 旁路可能
```bash
lsusb -t                                  # 看相机所在端口速率: 5000M=USB3 SuperSpeed
ps -eo pid,pcpu,comm | grep -i <node>     # 节点自身 CPU%
fuser /dev/videoN                         # 视频节点被谁独占
```
- USB 报 `5000M` ⇒ 带宽与线缆**不是**瓶颈（真机实测 640x480@1.9Hz 仅用千兆的 1.4%）。
- 节点 CPU 只有几十 % ⇒ **不是**算力不足，说明它在"等设备"。
- 所有 `/dev/videoN` 被**同一 PID** 独占 ⇒ 该进程活着时打不开设备
  （`xioctl(VIDIOC_S_FMT) failed ... Device or resource busy`，errno=16）。
  🔴 **但这不等于"没有旁路"** —— 不要就此写"唯一入口就是那个节点"。
  停掉该进程后用厂商 SDK 直驱即可拿到设备真实高帧率（实测 30/60/90 全达标）。见下节。

## 2.5 直驱旁路：先查厂商 SDK 是否已经装好
设备主机上先问一句"有没有这个相机的官方 SDK"（大多数机器人厂商镜像里都有）：
```bash
python3 -c "import pyrealsense2 as rs; print(rs.__version__)"    # RealSense 系
python3 -c "import pyzed, cv2; print('ok')"                       # ZED 系；其他品牌类推
```
**装了就说明可以绕开厂商节点直驱**，而且能拿到**唯一的权威能力证据** —— 设备自己报的模式表。
纯查询**不启流、不占设备**（厂商节点照常跑）：
```python
import pyrealsense2 as rs
for d in rs.context().query_devices():
    print(d.get_info(rs.camera_info.name), d.get_info(rs.camera_info.firmware_version),
          d.get_info(rs.camera_info.usb_type_descriptor))
    for s in d.sensors:
        print(" sensor:", s.get_info(rs.camera_info.name))      # 有几个传感器就已经是答案
        for p in s.get_stream_profiles():
            v = p.as_video_stream_profile()
            if v: print("  ", v.stream_type(), v.format(), v.width(), v.height(), v.fps())
```
- ⚠️ 枚举结果的排序键是 pyrealsense2 枚举对象，**不能直接 `sorted(agg.items())`**（TypeError:
  `<` not supported between instances of `format`）⇒ 用 `key=lambda kv: (str(kv[0][0]), str(kv[0][1]))`。
- **`sensors` 只有一项且名字是 `Stereo Module`** ⇒ 该相机没有独立 RGB 传感器，这已直接解释
  `color sensor not found`（见 3.5），不用再猜参数。
- **模式表就是天花板**：实测 D405 在 640×480 列出 `5/15/30/60/90` ⇒ 厂商节点只给 1.9Hz 属于实现问题，
  不是设备能力问题。**“设备上限”这个结论必须以这张表为依据，不能靠“参数改了没反应”推断。**

**直驱实测（先在厂商节点停掉、腾出设备后做）**：`rs.pipeline()` 按目标 fps 同时启 color+depth，
预热 10 帧再数 8 秒。实测 30→30.0 / 60→59.9 / 90→89.9 fps（彩色+深度同跑）⇒ 硬件完全够。

## 3.5 认型号 + 查节点日志的 `skip`/`not found`（能一次终结整条证伪链）
```bash
lsusb | grep -iE "intel|realsense|<厂商>"                # 认型号: 型号决定"这个传感器到底有没有"
grep -iE "sensor|skip|not found|WARN|ERROR" <节点日志>   # 厂商节点自己的告警
```
- 实测：`8086:0b5b Intel RealSense **D405**` —— 405 是**立体深度相机, 没有 RGB 传感器**,
  节点日志 `RealSense color sensor not found, skip color option config` ⇒
  `color_fps`/曝光/分辨率这些**彩色参数被整段跳过**, 节点跑内部回退路径。
- ⇒ 这一条**解释了此前所有"改参数零效果"**: 不是改错了, 是参数针对的传感器不存在。
- ⇒ **分层报**: 配置层(能改) / 链路层(能改) / **型号层(改不了)** —— 型号层只能报厂商或换相机。
- ⇒ 反过来说: **"改参数没反应" ≠ "设备上限已证"**, 必须先在日志里排除 `skip`/`not found`。
- 注意: 相机话题存在 + 设备在 `lsusb` + 6 个 `/dev/video*` 全部枚举 **都不代表**你需要的那个传感器在。

## 3.6 「慢」与「挂死」的区分（用户说"一卡一卡"时必做）
进程在 + CPU 高 **不等于** 在发帧。判活三条一起看：
```bash
ros2 node list | grep <node>                     # 不在图里 = 节点已退出 ROS 图
ros2 topic info <topic> -v | grep -i publisher   # Publisher count: 0 = 没人在发
stat -c %Y <tap 落盘文件>                         # 帧计数/时间戳是否还在推进
```
- 实测挂死形态: 进程活着烧 40%CPU(自两天前起)、但 **不在 `node list`**、`Publisher count: 0`、
  tap 帧计数冻结在 21668 ⇒ 已挂死 ✗ (不是慢)。
- 挂死会污染交付物: 录像**后半段整段静止**、看板帧龄 **466s** ✗
  ⇒ **交付录像前必须回看视频里有没有长冻结段**(逐帧比左半画面差异, 连续 >2s 不变即为冻结)。
- 挂死还可能**中途发生**(跑着跑着死) ⇒ 长动作录像要边录边看 `age_s`, 不能只在开头确认一次。

## 3.7 定位瓶颈「在哪一跳」：分层卸载测速（比逐条证伪更快出答案）
逐条证伪只能排除"是不是带宽/算力/参数"；**分层卸载才能直接指出"时间花在哪一行"**。
把管线拆成递进的、每层只加一件事的循环，各跑 6~8 秒数帧：
```
A1 只 wait_for_frames          → 不发布、不对齐
A2 A1 + 深度对齐(align)        → 加一层的代价
A3 A2 + np.asanyarray 拷贝     → 加拷贝的代价
B  A3 + 发布到 DDS(RELIABLE)   → 加发布的代价
B' 同上但 BEST_EFFORT / 另一 QoS → 排除 QoS 背压
C  BEST_EFFORT + 不发布点云     → 排除点云开销
```
实测（D405 → 本机 DDS，640×480 bgr8）：
| 层 | 帧率 | 解读 |
|---|---|---|
| A1 只读相机 | **30.0** | 匹配传感器 33ms 节奏 |
| A2 +对齐 | **30.0** | 对齐**免费** |
| A3 +拷贝 | **30.0** | 拷贝**免费** |
| B/C +发布 | **4.6** | **发布一步就吃掉 6.5 倍** |
⇒ **瓶颈是"发布"本身，与相机/对齐/拷贝/QoS/点云都无关。**
一帧 921KB 走本机 DDS 需 **216ms** ⇒ 这是链路特性，不是你的代码慢。

**机制**（能在现场直接查到）：大消息走 UDP 分片，而内核 socket 缓冲远小于一帧：
```bash
cat /proc/sys/net/core/rmem_max /proc/sys/net/core/wmem_max    # 实测 212992 = 208KB
```
⇒ 921KB 的帧装不下 → 溢出丢包 → RELIABLE 重传 → 216ms/帧。
- **根治**：调大 `rmem_max/wmem_max`（需 root）**并重启相关进程**（已开的 socket 不会变大）。
  没有 root 时把这条**作为"需要 root/厂商执行"的事项写进交付**，不要假装绕过它。
- **绕过**（不碰 DDS 也不碰权限）：高帧率画面走**小消息通道**（JPEG/HTTP），DDS 只留低频保订阅方。
  见 `references/high-rate-camera-bypass-node.md`。
- 顺带量一下 `free -g` 与 `uptime`：**本机已满载（load≈核数）时，发布线程会连采集一起拖慢**，
  这也是下面"发布必须独立线程"的原因。

## 4. 找实现（决定"能不能读源码确证"）
```bash
readlink -f /proc/<pid>/cwd               # launch 进程的 cwd → 定位 launch 与 install 树
ls <install>/lib/python3.*/site-packages/<pkg>/<sub>/
strings <node>.cpython-*-aarch64-linux-gnu.so | grep -iE 'fps|rate|sleep|timeout'
```
- ROS 包的入口常是 **easy-install 脚本**（`EASY-INSTALL-ENTRY-SCRIPT`），真实实现在
  `site-packages/<pkg>/` 下，且**可能是编译好的 Cython `.so`（无源码）**。
- `.so` 里 `strings` 只捞出日志节流符（`_error_throttled`/`_warn_throttled`）而**没有帧率常量** ⇒
  无法从静态证据确证节流点，别再继续挖，转为结论汇报。
- 参数运行时不生效 + 无源码 ⇒ **重启该节点是唯一可能改变帧率的动作**。

## 5. 判断重启是否安全（这一步才是能不能动手的关键）
```bash
grep -n "respawn" <launch>/*.launch.py
grep -nE '\.launch\.py|include|generate_' <launch>/*.launch.py
```
- launch 里没有 `Node(` 注册、只有一个 `generate_*_launch_description(...)` 调用 ⇒
  **节点注册在别处动态生成，无法静态确认 `respawn`**。
- **放弃前必须回答**：kill 之后谁把它拉起来？答不出来就**不要 kill**。
  生产相机节点被杀而不自动重启 = 产线直接丢感知，代价远大于慢帧率。
- 报给用户的正确形态："设备上限已确证（列出逐条证据）；唯一修法是重启该节点，
  但它是产线感知链一环且无法确认自动拉起 ⇒ 需要你确认 + 现场有人"，并附安全窗口证据
  （状态机话题为空 = 产线空档）。

### 用户点头授权后的重启执行配方（1:1 复现, 可回退）
1. **从活着的进程抄出还原材料**, 别靠猜:
   ```bash
   tr '\0' ' ' < /proc/<pid>/cmdline           # 完整 argv(含 --params-file /tmp/launch_params_*)
   tr '\0' '\n' < /proc/<pid>/environ | grep -E 'ROS_|AMENT|LD_LIBRARY|PYTHONPATH'
   ```
   launch 生成的 params 文件在 `/tmp/launch_params_*`, 用 `grep -l -iE 'color_fps|publish_rate'` 找出该相机那一个。
2. **环境靠 `source` 工作空间 overlay 复现**(比手工拼 `AMENT_PREFIX_PATH` 可靠), 但:
   🔴 **脚本里不能开 `set -u`** —— `source /opt/ros/*/setup.bash` 会因未绑定变量 `AMENT_TRACE_SETUP_FILES`
   直接中断, 表现为"脚本刚 source 就退出"(此时**还没动相机**, 是安全的)。用 `set -o pipefail` 代替。
3. **停**: `kill -TERM`(温柔, 让它释放设备) → 轮询等进程真退出 → 等 ~3s 让 `/dev/video*` 释放 →
   TERM 超时才 `kill -9`。
4. **起**: `nohup /usr/bin/python3 <bin> --ros-args --disable-external-lib-logs \
   --ros-args -r __node:=<name> --params-file <orig> [覆盖参数] > /tmp/cam.log 2>&1 &`
5. **验**: `ros2 topic hz <topic>` **且** `ros2 topic info <topic>` 的 `Publisher count` (两个都要看)。
6. **A/B 归因(必做)**: 先**用原配置重启**量一次, 再用覆盖参数重启量一次 ——
   否则分不清是"重启"还是"我改的参数"起了作用。实测: 原配置 1.860Hz vs `color_fps=30`+`depth_fps=30`+
   `publish_rate=30` 三覆盖 1.875Hz ⇒ **覆盖完全无效**, 这才是"参数路径是死的"的硬证据。
7. **状态变化要如实告知**: 手工拉起的节点**不再由 launch 托管** ⇒ 功能一致但不自动重启;
   整套 launch 重启时可能**抢设备**。这条必须写进交付, 别默默留下。
8. 未能恢复时把原命令原样再跑一次, 并明确说"我没能恢复, 需要厂商/现场介入"。

## 6. 收尾：还原 + 回读
把所有改动过的参数逐项设回原值，并**逐条 `param get` 打印确认**后才算收尾完成。
交付里明确写出"生产参数已还原原值：<逐项=值>"。

---

## 汇报口径（诚实边界）
- 说清"**哪一环已优化到底**"：若帧龄已降到相机周期的一半以下，延迟这一环就没有优化空间了，
  剩余卡顿全部来自相机帧率本身。
- 不把"优化了压缩比/延迟"说成"解决了卡顿"。用户说的"卡"= 帧率，帧率不动就是没解决。
- 给用户的选项要可执行且互斥：① 重启生产节点（有风险，需现场）；② 换一路能对准目标的相机；
  ③ 先只读查清重启路径再决定。

## 帧率"够不够"怎么算（用户必问）
```
每帧盲走距离 = 运动速度 ÷ 帧率         # 一帧之内目标滑过的距离
差  距  倍  数 = 需求帧率 ÷ 实测帧率
```
把"每帧盲走"和**任务精度**并列, 答案就不需要形容词:
- 实测 10 mm/s ÷ 1.86 fps = **每帧盲走 5.4mm**; 精细插拔要控到 ~0.1mm ⇒ 一帧之内滑过 50 倍精度 ⇒
  相机看不见"插入"这个动作本身; 帧率差 30÷1.86 ≈ **16 倍**。
- 依据: 对齐→接触→插入这些关键事件只有 **50~200ms**, 帧间隔必须 ≤33ms(30fps) 才不漏。

| 场景 | 最低 | 推荐 |
|---|---|---|
| 遥操作 / 视觉伺服 | 15 fps | **30 fps** |
| **精细插拔(金手指这类)** | **30 fps** | **60 fps** |
| 模仿学习采数据 | 10 fps | **30 fps** |
| 纯监控看个大概 | 5 fps | 15 fps |

汇报结构（用户问「为什么卡 / 现在多少 / 应该多少 / 够不够 / 能不能平顺」时按序答）:
1. 实测数字(帧率/帧龄/每帧盲走) 2. 根因链(配置层/链路层/型号层分开) 3. 需求档 + 差距倍数
4. **"我能做的" 与 "必须厂商做的" 分列**, 最后给一个不碰产线的可执行建议(如另加一路 USB 相机对准目标)。
