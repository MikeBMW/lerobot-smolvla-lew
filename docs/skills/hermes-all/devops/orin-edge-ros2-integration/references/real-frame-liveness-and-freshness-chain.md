# 真机图像链路地图 + 「画面不实时/冻帧」诊断序 (2026-09-18 实测)

问题原话: 「为什么真机的输入图像，不是实时的了？」—— 本次答案是**三层原因叠加**, 不是单点故障。
本篇给链路地图 + 逐层判据, 下次同类问题按序查, 别一上来就重启。

## 链路地图 (谁养活谁, 各自的速率上限)

```
Orin 产线: realsense_source 节点
  /realsense/color/image_raw   实测 1.17Hz  (参数 color_fps=15 / publish_rate=5.0 → 源本身就没跑满)
        │  (跨机 DDS, domain 0, 无压缩 — 大图别指望高频)
        ▼
4060 侧 systemd `ss-remote-tap.service` → docker run --rm ros:humble-ros-base --network host
        /repo:ro + -v ~/zmax_ss_remote:/out, ROS_DOMAIN_ID=0
  · 10Hz 采样循环 → state_YYYYMMDD.jsonl + status.json (每样本还 HTTP 调 /infer, 实际 ~2.5Hz)
  · 1Hz `_tick_img`: 反序列化最新 raw → PNG 落盘
        cam_rs.png  ← RealSense 优先 (L2 吃的就是这条)
        cam_fp.png  ← 其他图像话题 (foundationpose 等) [容器内 /out → 宿主 ~/zmax_ss_remote]
        ▼
GUI tools/gui/yolo_input_viewer.py「打开输入图像」
  ① 首选: Orin /zmax/live_frame srv → live_frame.jpg (UVC 直取+JPEG, 按需拉起, idle 25s 自退)
  ② 回退: cam_rs → cam_fp → cam_latest (同源, 新鲜度 = 文件 mtime ≤ ZMAX_VIEWER_FILE_FRESH_S=10s)
  ③ 都不新鲜 → 占位画面, **绝不回退历史帧** (老倪红线: 不用旧图冒充实时)
L2 侧 tools/ss_yolo_on_real.py CAND 顺序同上 (旁路 YOLO 出 yolo_annotated.png, 只做可视化)
```

## 三层原因 (逐层查, 每层都有独立判据)

**L1 代码判据被时钟弄死 (本次主因)**: 采样节拍与解码节流都用 `time.time()` 差值 →
NTP 把钟回拨 8h 后判据反转 → **进程还在、CPU 空转、一行产出都没有** (冻 13 分钟)。
通用修法与扫描清单见 `unattended-pipeline-supervision` → `references/clock-step-freezes-daemons-and-freshness.md`。

**L2 新鲜度判据把旧帧当新帧**: 文件 mtime 落在未来 (回拨前写的) → `age = now - mtime` 为负 →
`age <= 10s` 恒真 → 冻住的画面照样上屏且不换占位图; GUI 断流自愈 (`_stale_since`/`_last_recover`) 也变恒假, 没人救。
⇒ 修法: `age < -1.0` 一律拒用并标「⏰ 时钟异常」, live_frame.json 的 `age_s` 必须落在 `[0, 5]`。

**L3 真源帧率天花板**: `ros2 topic hz /realsense/color/image_raw` = 1.17Hz。
**这层不是故障**, 但"每秒 1 帧"会被当成"不实时"; 报现象时必须连这一层一起说清, 否则用户以为修好了还是1fps是没好。

## 诊断序 (先证源头速率, 再看落盘, 最后看窗口)

```bash
# 0) 时钟本身 (一切判据的前提)
date; timedatectl | head -4
# 1) 真源速率 (在 Orin 上测, 权威)
ssh tashan@192.168.23.66 'source /opt/ros/humble/setup.bash; timeout 8 ros2 topic hz /realsense/color/image_raw'
# 2) 落盘是否在推进 (间隔 ≥10s 量两次; 或 --time-style 看 mtime)
ls -l --time-style=+%H:%M:%S ~/zmax_ss_remote/cam_rs.png ~/zmax_ss_remote/state_$(date +%Y%m%d).jsonl
# 3) 采集器内部计数 (样本数/收包是否在涨; img 计数 ≈ 真源 Hz)
sudo docker logs --tail 3 ss-remote-tap
# 4) 落盘的帧元数据 (topic/w/h/std/age; std>5 = 真图不是黑图)
tail -c 4000 ~/zmax_ss_remote/state_$(date +%Y%m%d).jsonl | tail -1 | python3 -c "import json,sys;print(json.load(sys.stdin)['image'])"
```
**冻帧指纹 (一眼区分"死"与"卡")**: 进程在 + CPU 空转 + 产出 mtime **落在未来** → 时钟事故;
进程不在 / 退出码非 0 → 真崩。判据是**产物 mtime 在推进**, 不是 `ps` 有进程。

## 服务/重启地图 (改码后按这张表重启)

| 组件 | 归属 | 重启 |
|---|---|---|
| 远程采集 tap | system 服务 `ss-remote-tap.service` (Restart=always, ExecStart=docker run --rm) | `docker restart ss-remote-tap` 即可 (unit 仍跟踪同一容器) |
| 旁路记录器 | system `ss-bypass.service` | `systemctl restart ss-bypass` |
| 本机推理 / L2 旁路 YOLO | system `ss-local-infer` / `ss-yolo-bypass` | `systemctl restart <unit>` |
| 控制台 GUI | **user** 服务 `zmax-studio.service` (Restart=no; 桌面图标启动的实例不在这个 unit 里) | `systemctl --user restart zmax-studio`, 之后 `ps` 查双开 |

`Restart=always` 救不了时钟事故 —— 进程**没退出**, 只是空转, 必须手动重启。
GUI 改码必须重启 (无 autosave), 且桌面图标拉起的实例与 user unit 是两路, 容易双开。

## 回归自检 (修完自跑通, 别只看"现在有图了")

`tools/verify_clock_skew_guard.py` 模式: offscreen 导入 GUI 模块 → monkeypatch `SHARED`/候选文件表到临时目录 →
造 未来8h / 未来30s / 新鲜1s / 旧60s 四种 mtime → 断言 拒用/拒用/入选/拒用; 最后对现场真目录断一次 "帧龄 ≤ 阈值"。
跑法 `gui-venv311/bin/python tools/verify_clock_skew_guard.py` (全绿才算修好, 本次已落档)。

## 报现象纪律

- 报"图像不实时"必须分层给数: 真源 Hz (Orin 实测) / 落盘 mtime 间隔 / 窗口新鲜度阈值。
- 时钟事故波及面要主动扫: cron `next_run_at` + 所有常驻循环 + 帧新鲜度, 只修一处会二次复发。
- 长内联命令 (heredoc / 多行 `python3 -c`) 在 Hermes 会被硬拦 → 用 `write_file` 落脚本再跑。
