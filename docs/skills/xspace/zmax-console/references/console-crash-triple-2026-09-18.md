# 控制台崩溃三连 + 取帧新鲜度口径 (2026-09-18 实测)

一天内三个不同故障, 一个通式: **Qt 槽/定时器里的事都必须"只记日志, 绝不冒泡", 且所有取图入口共用同一套新鲜度口径。**
(主 SKILL.md 的「控制台两个高频故障」节是 ①② 的简版; 本文件含 ③④ 与排查/自检配方。)

## ① 模式下拉切「🔌 本地连接 (Local)」→ 整进程消失 (无弹窗)
`_on_mode_changed`: `modes=["sim","local","real"]` 而 `Z700_ROS2_NODES` 只有 `sim`/`real`
→ `KeyError: 'local'` 在 Qt 槽里没人接 → qFatal → **SIGABRT**。日志: `Fatal Python error: Aborted` + traceback 直指行号。
修: 未知/越界模式键一律退回 `sim` 表 + 如实打日志; 槽体总兜底。同类坑 2026-09-14 也出现过(`Z700_ROS2_NODES["real"]` 被当 dict 用 `.get()`)。

## ② 「输入图像」真机源永远无画面, 但 L2 一直在吃帧
窗口真机源只认 srv 落盘 `live_frame.jpg/.json`(Orin `/zmax/live_frame` → Docker `ss_frame_srv_client.py`)。
服务不可达(容器日志 `❌ 服务 /zmax/live_frame 不存在 → 退出`) → 该文件冻结在旧时间戳 → 窗口按纪律显示占位。
**而真机图像一直在流**: Docker tap 只读订阅落盘 `cam_rs.png`(0.x 秒龄), L2(`ss_yolo_on_real.py` CAND)吃的就是这条。
修: 真机源候选链 `cam_rs.png → cam_fp.png → cam_latest.png → srv_cam.png/.jpg`, 逐文件 mtime 新鲜度(≤10s),
有新鲜帧就上屏且状态栏标「来源 / 帧龄 / 为什么回退」; 全不新鲜 → 占位逐条列候选状态。**别改回"只认 srv"**(Orin 红线=零自研程序, 话题落盘才是常驻正解)。

## ③ 「⏭ 保存并下一帧」取回**历史帧** → 标定数据被污染
`_next_frame()` 对真机源**无条件读** `live_frame.jpg`(实测 62221s 龄 = 昨天的帧) → 标定时把历史帧当"下一帧", 保存即污染训练集。
**通式: 实时刷新修好了 ≠ 取新帧按钮修好了 —— 所有"取下一帧/取新图"的入口必须共用同一套新鲜度判定。**
修(三步): ①srv 帧须 `ok ∧ 非 stale ∧ age≤5s` ②否则取 tap 落盘新鲜帧 ③都不新鲜 → **拒绝 + 说明原因**, 不回退历史帧; 日志打「来源 + 帧龄」。
自检: 桩对象直接调 `_next_frame`, 断言日志出现 `cam_rs.png` 且不含 srv 历史帧。
污染复查: `find data/yolo_annot* -name '*.png' -newermt '<日期>' | wc -l`(0 才放心) + 同帧 md5 重复计数 + `grep <日期> .../annotations.jsonl`。

## ④ SIGSEGV (原生段错误) 无栈排查 + 四层硬化
实测: `Fatal Python error: Segmentation fault`, faulthandler 只有线程转储(主线程在 Qt 事件循环), **无 Python traceback、无 core**。
处置顺序:
1. **先留栈**: systemd 默认 `LimitCORE=0` → drop-in `~/.config/systemd/user/zmax-studio.service.d/core.conf` 写
   `[Service]` + `LimitCORE=infinity`; `sudo sysctl -w kernel.core_pattern=/tmp/core.%e.%p`; `systemctl --user daemon-reload`(下次启动生效)。
2. **槽体总兜底**: 66ms 刷新等所有定时器/槽包 try/except(只记日志不冒泡)。
3. **读图健壮**: 别人 10Hz 覆盖写的 PNG, 读者要**整块读入内存再解码, 失败返回 None**; cv2 可用时**它就是权威**
   (解码失败直接判该帧不可用), 不要把坏 buffer 再交给 Qt 解码器 —— 实测截断 buffer 走 Qt 路径, 无 QApplication 时
   `QPixmap: Must construct a QGuiApplication` → SIGABRT。
4. **写侧原子化**: `open(path,"wb").write(png)` 先把文件截断 → 读者可能读到半张图; 改 `tmp + fsync + os.replace`
   (示例 `tools/ss_remote_tap.py::_save_png`)。

## 排查入口 (照抄)
```
journalctl --user -u zmax-studio --since "<HH:MM>" --no-pager | grep -viE "Unknown property cursor|Debugger warning"
#   → 找 Fatal Python error / Segmentation / Aborted; 再看 Current thread 的 文件:行号 = 落到具体槽
/tmp/studio_launch.log        # 历史实现留的 faulthandler 转储 (线程栈全量)
/tmp/closeEvent.log           # 有窗口正常关闭的记录 = 那次是"关窗"而非崩溃
/tmp/studio_show_diag.log · /tmp/zmax_simulink_init.log   # 启动/显示自检时间线 (epoch 秒, 用来对时间)
```
改 GUI 代码后**必须重启**才生效: `systemctl --user restart zmax-studio`(Restart=no 不自拉), 重启后 `ps` 查双开;
`wmctrl -l` 可核对「画布」「📺 输入图像」两个窗口是否真起来。
