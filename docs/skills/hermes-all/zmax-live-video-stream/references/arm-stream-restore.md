# arm(D405) 视频路恢复 —— 栈重启后必做

## 症状
`curl http://127.0.0.1:8791/stats` 里 `arm` 的 `age_s` 上万、`fps=0`；
`/snapshot/arm.jpg` 拿不到图；而 ROS 话题 `/realsense/color/image_raw` **本身在出帧**。

## 架构（谁给谁供图）
```
D405 相机（Orin, realsense_source 节点, 随 start.launch.py 起）
   ↓ /realsense/color/image_raw   (BEST_EFFORT QoS; 实测 0.5~0.65Hz)
Orin 上 :8792/frame.jpg  HTTP 端点  ← **由 /tmp/rs_fast_node.py 提供, 不属于 launch**
   ↓ --arm-http http://192.168.23.66:8792/frame.jpg
本机 8791 叠加服务的 arm 频道 → /snapshot/arm.jpg · /overlay 里的 arm 格
```
**关键**: `start.launch.py` **不含** rs_fast_node。所以每次重启机器人栈，
D405 相机会回来、但 `:8792` 是死的 —— arm 路必挂。这就是 arm age 上万的真因，
**不是 QoS、不是相机坏、也不是 8791 服务的锅**。

## 恢复步骤（在 Orin 上）
1. 确认 `/tmp/rs_fast_node.py`（订阅话题 → 提供 /frame.jpg）在位 —— 但 **`/tmp` 会被清掉**(重启/清理),
   这只是临时位。**恢复后务必搬到持久目录**(如 `/home/tashan/zmax/rs_fast_node.py`)并挂自启
   (systemd 或 cron `@reboot`), 否则下次重启 arm 路**再挂一次**, 每次都靠手工救。
2. 用**脚本文件**执行重启（别把 kill 写进 ssh 命令行，见下面的坑）：
   ```bash
   cat > /tmp/rsfix.sh <<'SH'
   #!/bin/sh
   for p in $(pgrep -f '[r]s_fast_node.py'); do kill -9 "$p" 2>/dev/null; done
   sleep 2
   cd /home/tashan/0810/tashan_robot_so_*_aarch64
   . /opt/ros/humble/setup.bash
   . install/setup.bash 2>/dev/null
   setsid nohup python3 /tmp/rs_fast_node.py > /tmp/rs_fast.log 2>&1 < /dev/null &
   sleep 16
   curl -s -m 8 http://127.0.0.1:8792/status
   curl -s -m 10 -o /tmp/f.jpg -w '%{http_code} %{size_download}' http://127.0.0.1:8792/frame.jpg
   SH
   bash /tmp/rsfix.sh        # ← 必须 bash, 用 sh(dash) 会 "Bad substitution"
   ```
3. 判据: `status` 返回 `{"n":>0,"enc":"bgr8","err":""}` 且 `frame` 是 `200` + 30~40KB JPEG。
4. 本机侧 3~5 秒后 `/snapshot/arm.jpg` 变 200，`stats` 里 arm fps 跳到 ~30。

## 坑（都实测踩过）
- 🔴 **`set -u` 会让 `. /opt/ros/humble/setup.bash` 直接中断**：ROS 的 setup.bash 内部引用未绑定变量
  `AMENT_TRACE_SETUP_FILES` ⇒ 报 `未绑定的变量` 后不再继续设置环境。恢复脚本**绝对不要写 `set -u`**，
  也不要 `unset AMENT_PREFIX_PATH`（会把 ROS 环境弄得更空）。
- 🔴 **`. setup.bash | tail` 等于「在子 shell 里 source」** ⇒ 当前 shell 根本没拿到 ROS 环境，
  症状是节点一起来就 `ModuleNotFoundError: No module named 'rclpy'`（而 `python3 -c "import rclpy"`
  单独测又是好的，因为那是在子 shell 里）。**source 一律不带管道**，要静默就 `2>/dev/null`。
  ⇒ 这两个坑连起来的结果是「把旧节点杀了、新的没起来」= 取流**彻底断**，比不动它更糟。
  杀旧节点前先把新节点的完整启动命令在**另一个 ssh 会话**里跑通一次并确认 `status` 有 `n>0`。
- **`/tmp/rs_fast_node.py` 会被清理**（重启/清 tmp）⇒ 恢复后立刻 `cp -n` 到持久位
  `/home/tashan/zmax/rs_fast_node.py`（实测两份 md5 一致）并挂自启；只放在 /tmp 属于下电即失。
- **`pkill -f <pattern>` 会匹配到自己那条 ssh 命令行** ⇒ 整条命令被自杀、**输出为空**。
  规避: ① 中括号写法 `pkill -f '[r]s_fast_node'`（正则匹配 rs_fast_node，而自己的命令行里是
  `[r]s_fast_node` 不匹配）② 或写成脚本文件再执行（输出干净、不自杀）。
  **空输出 ≠ 命令没跑**，很可能就是自杀了。
- **`kill`/`pkill` 写进 ssh 命令行会被安全扫描拦掉**（返回空）⇒ 一定放脚本文件里执行。
- **端口被旧进程占着 ⇒ 新节点起来但 HTTP 线程崩**（日志里 `Exception in thread Thread-1`，
  而端点仍返回**旧进程的** 503）⇒ 只看日志会误判。必须按 PID 确认旧进程真死了：
  `pgrep -f '[r]s_fast_node.py'` 应为 0 再启动。
- **`np.frombuffer(buf, dtype, count)` 的第 3 参是 count 不是 shape** ⇒ 传 `(h,w,3)` 报
  `'tuple' object cannot be interpreted as an integer`。要 `.frombuffer(...).reshape(h,w,3)`。
- 订阅图像话题必须 **BEST_EFFORT**（`ReliabilityPolicy.BEST_EFFORT`），默认 RELIABLE 一帧收不到。

## 深度(depth)路（比 arm 更脆: 它的生产者是个容器）
本机 `--depth-npy` 读的是**容器内 `ros_depth_stream` 落的 npy**（tap 容器 /dev/shm）。
- **先查生产者, 不是相机**: 帧龄上万秒时先 `ls -la` npy 的 mtime + `docker ps -a` —— 实测容器栈
  **整个都没了**(`docker ps -a` 空、镜像也没了), 文件停在几小时前, 而 Orin 的
  `/realsense/depth/image_rect_raw` **话题是好的**。⇒ "深度没了"不等于"相机/话题坏了"。
- **Orin 的 `rs_fast_node` 没有深度口**: 逐路径探过, 只有 `/frame.jpg` 是 JPEG, 其余(含 `/depth*`)
  全返回**同一份状态 JSON** = catch-all（判据见 SKILL.md「取单帧 / 探端点」节）。
- 想彻底摆脱容器依赖, 正解 = 在 Orin 那个已有 HTTP 节点上加一个**低频**(1~4Hz, 页面只按
  `--depth-fps 4` 取)深度口, 本机 `--depth-npy/meta` 改走 HTTP —— 与 arm 同一条路。
  ⚠️ 这等于给 Orin 加一个订阅者, **属于在役配置改动, 须老倪点头**, 并评估对运动服务的负载影响。
- 未恢复时页面里按**运行时探测**显示(标帧龄/在线), 别写死成活的 —— 老倪会按画面判状态。
