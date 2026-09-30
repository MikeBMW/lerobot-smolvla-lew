# 高帧率相机旁路节点（直驱 + 双通道，保产线订阅方）

适用：设备主机上有个厂商相机节点只能给 1~2Hz，而你已确认：
- 设备真实支持高帧率（`pyrealsense2` 模式表，见 `frame-rate-ceiling-diagnosis.md` §2.5）；
- 直驱能跑满（30/60/90 实测达标）；
- 但**一发布到本机 DDS 就崩到 4.6fps**（大消息 216ms/帧，§3.7）。

前提：**必须拿到用户授权**（这是在换产线在役感知节点），且已抄下原节点完整 argv + params 文件用于回滚。

---

## 一、架构：两条通道，各走各的

```
设备主机一个进程（直驱相机，独占设备）：
 捕获线程（目标 30fps）
   ├─ ① 高速旁路: cv2.imencode JPEG(q70~72, ~32KB) → 原子写 /dev/shm/<cam>.jpg
   │              + 内置 HTTP :PORT/frame.jpg（stdlib http.server）
   │              ⇒ 32KB 小消息，绕开大消息传输的死结
   └─ ② 保兼容: 队列(非阻塞) → 独立发布线程 → DDS 原话题名/原类型/原 QoS，限流 ~2Hz
                 ⇒ 原订阅方（vision/标定节点）不回退
```

**为什么必须双通道**：高帧率画面只有你和看板需要 → 走小消息通道；
原订阅方按 RELIABLE 订着原话题名 → 停发就是产线丢感知。限流后的 DDS 速率**要 ≥ 原节点的速率**，
这样交付里能写"订阅方不回退"，而不是"我为了自己的画面把产线降级了"。

## 二、关键实现点（每条都踩过）

1. 🔴 **DDS 发布必须放独立线程** —— 大消息发布一次 216ms，放在采集循环里会把整条流水拖垮：
   实测同代码，1/6 限流内联发布 → **12.9fps**；改成独立线程 + 队列 → **22.9fps**。
2. 队列用 `queue.Queue(maxsize=3)` + `put_nowait`，满就**丢帧**（`except queue.Full: pass`）——
   绝不阻塞采集；发布线程慢就让它慢。
3. **JPEG 原子写**：先写 `.tmp` 再 `os.replace()`，否则消费者会读到半帧。
4. JPEG 编码留在**有 cv2 的那一侧**做；容器里常只有 numpy。
5. HTTP 端点除 `/frame.jpg` 再给一个 `/stats`（JSON：fps / frames / dds / jpeg_ms）——
   这是唯一不受客户端影响的权威帧率口径，用它取证，别拿"客户端数出来几个帧"当结论
   （Python urllib 每次新建连接 ≈38ms，客户端读数会低于真实产出）。
6. `cv2.imencode` 耗时是**负载指示器**：同一段代码 4~7ms → 22~46ms 的跳变就意味着主机 CPU 被抢
   （通常是发布线程在吃核）。看到它涨就降 DDS 频率，别去优化 JPEG。

## 三、两通道的频率取舍（实测）

| DDS 限流 | 高速通道 | DDS 通道 | CPU |
|---|---|---|---|
| 1/6 | 12.9 fps | 2.7 Hz | 100% |
| 1/15 | 25.0 fps | 1.6 Hz ✗ 低于原节点 | 75% |
| **1/10（推荐）** | **22.7 fps** | **~2.2 Hz** ✓ ≥原节点 | 76~92% |

⇒ 先按 1/10 起，再按 "DDS ≥ 原节点速率" 这条线收：**两边都不回退**才算交付。

## 四、切换编排（带自动回滚）

```
1. 只读确认生产空闲（状态机话题无发布 = 空档；把证据列给用户）
2. 备份：tr '\0' ' ' < /proc/<pid>/cmdline  → 原命令；grep -l 'color_fps|publish_rate' /tmp/launch_params_*
3. kill -TERM 原节点 → 轮询等退出 → 等 ~3s 让 /dev/video* 释放（TERM 超时才 -9）
4. nohup 起直驱节点 → 等 25~40s（含预热）
5. 验：/stats 的 fps **且** ros2 topic hz 原话题（两个都要，缺一不可）
6. 达标 → 保留；不达标 → **自动回滚**：kill 直驱节点 → 用原命令+原 params 拉起厂商节点 → 再量一次
```
- 回滚分支写成脚本里的 `restore_vendor()` 函数，在阈值判断里调用 —— **不要靠人记得回滚**。
- ⚠️ 脚本里**不要开 `set -u`**（`source /opt/ros/*/setup.bash` 遇未绑定变量 `AMENT_TRACE_SETUP_FILES` 会直接中断）。
- 加一个守护循环：`while true; do pgrep -f <node> || nohup 拉起; sleep 10; done`（用 `setsid` 起）。
- ⚠️ **本机 `nohup/&` 前台起服务会被拦** ⇒ 常驻服务用工具的 background 模式起（带 persist），不要拼命包 wrapper。

## 五、消费端（看板/录制）取新源

`cam_live_stream.py` 加 `--arm-http <url>`（urllib 直接转发已压好的 JPEG，**不重压**）：
```bash
cam_live_stream.py --port 8791 --quality 72 --fps 30 \
  --arm-http http://<host>:8792/frame.jpg --arm-fps 30 --local-dev 0
```
- 🔴 **`--fps` 默认 15 会封顶**，只传 `--arm-fps 30` 没用 ⇒ 两个都传 30，否则卡在 15fps 还以为没生效。
- 单独试：先从本机 `curl -o /tmp/x.jpg http://<host>:8792/frame.jpg`，用 `cv2.imread` 验真图
  （`std>5`）再改代码——先证通路再改实现。

## 六、实测结果（作为验收基线）

| 项 | 原厂商节点 | 旁路节点 |
|---|---|---|
| 手臂相机（用户看到的） | 1.86 fps | **16.6 fps（8.9×）** |
| 设备端产出 | — | 22.9 fps |
| DDS（原订阅方） | 1.9 Hz | 2.2 Hz（不回退） |
| 主机 CPU | 92%（只出 1.9fps） | 76~92%（出 22.9fps） |
| 单帧 | 921KB raw | 32KB JPEG ✓ |

## 七、交付时必须同时说出的两件事
1. **状态变化**：相机现在由手工拉起的节点驱动，**不再由厂商 launch 托管** ⇒ 设备重启/整套 launch 重启
   会抢回设备（表现为画面又变慢）。告知用户"那时告我一声，我一分钟切回来"（切换脚本与守护都在）。
2. **没做成的部分**：DDS 通道仍受 208KB socket 缓冲所限 ⇒ "要让 DDS 本身也上 30fps，需要 root 调
   `net.core.rmem_max/wmem_max`"。把这条明确列为**需 root/厂商执行**的后续项，不含含糊糊算在自己头上。
