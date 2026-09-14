# 原子技能 SK 阶段高亮 + 3D 视频生成 (2026-09-08, 老倪: 运行到哪个技能高亮哪个)

## 需求
状态空间画布点 ▶运行, 其他模块逐节点高亮 (running 金色/绿), 原子技能 SK01-08
也应**运行到哪个阶段就高亮哪个技能节点** (老倪: "这些原子技能也应该运行到哪个技能
就高亮哪个技能")。

## 画布节点高亮机制 (SimulinkModule / simulink_module.py)
- 节点高亮 = 节点 dict `status` 字段: `"running"` (金色/提亮) vs `"success"` (绿)。
  改 status 后必须 `self._items[n["id"]].update()` + `self.canvas._scene.update()` 才重绘。
- **_ss_tick 播放路径** (引擎快演/轨迹回放): 已有节点轮转 — 上一节点→success,
  当前节点→running (每 exec_every tick)。SK 节点 (id `sssk1-8`, type=model, 画布
  state_space_obs.json 910 行起「🧩 原子技能层」) 也在 `_ss_order` 里会被轮转到,
  但顺序是画布拓扑序 → **不是按 接近→对位→…→完成 的阶段顺序**。

## 实现: stage → SK 高亮映射
阶段字符串 → 技能节点 id 的固定映射 (引擎 tr["stage"] / RealStateSpaceSim
`sched.stage()` 取值 "接近"…"完成", 可能带"阶段 "前缀或 "·SK07" 后缀, 清洗后匹配):
```python
_SK_MAP = {"接近": "sssk1", "对位": "sssk2", "下降": "sssk3", "抓取": "sssk4",
           "抬起": "sssk5", "转移": "sssk6", "插入": "sssk7", "完成": "sssk8"}
```
清洗: `str(stage).replace("阶段 ", "").split("·")[0].strip()`。

两处接入 (共用方法 `_highlight_sk_for_stage(stage_text)`):
1. **`_ss_tick`** (播放路径): 每 tick 读 `tr["stage"][idx]` → 设对应 sssk 为
   running、其余 sssk success。**位置放节点轮转逻辑之后** (每 tick 覆盖轮转对
   SK 节点的干扰, SK 高亮优先)。
2. **`_on_real_poll`** (真实化 worker 路径, 400ms 轮询): 读 worker 线程共享的
   `sim._vis["stage"]` → `_highlight_sk_for_stage`。⚠️ **真实化 sim.run() 在
   daemon 线程跑 5-9 分钟, 画布节点完全不动的** — GUI 必须轮询共享变量刷 SK,
   不能等 _real_finish (完成才 _ss_tick 播放)。
   配套: state_space_sim_real.py `_vis_refresh()` 每帧写 `self._vis["stage"] = st`
   (线程安全共享, GUI 只读)。

## ⚠️ 真实化 vs 快演两条运行路径 (排查"终端有输出但节点没高亮")
- ▶运行 → start_sim → 状态空间画布 → `chk_engine_demo` 未勾 → `_start_real_sim()`
  (RealStateSpaceSim worker, 逐帧 YOLO ~1s/步); 勾了 ⚡引擎快演 → `_start_state_space_sim()`
  (快 0.1s 后 _ss_tick 播放)。
- **运行中 (worker 阶段) 画布节点本来就零高亮** — 只有 SK 经 _on_real_poll 轮询
  _vis["stage"] 才动; 其余节点等 _real_finish 后播放才轮转。诊断先确认走哪条路径
  (日志 "🎥 真实化运行" vs "▶ 真实轨迹播放中")。

## 3D 对比视频生成 (PyQt5 + ffmpeg, 不用 cv2)
肌肉记忆/模型对比要"视频证明"时, 用轨迹喂 DreamView3D 逐帧 grab → PNG → ffmpeg:
1. 跑轮次收集 tr (真实化 R0 vision=False 0.2s/轮, 秒出)。
2. 每轨建 `DreamView3D()`, resize(900,560), show(), processEvents, set_trajectory(tr)。
3. 循环 `w.set_frame(i)` (每 ~3 步一帧) + `w.grab().toImage().save(f"{dir}/f{cnt:04d}.png")`
   + processEvents。
4. `ffmpeg -y -framerate 30 -i f%04d.png -pix_fmt yuv420p -crf 23 out.mp4`。
5. ⚠️ **PyQt5 进程里禁止 import cv2**: cv2 自带 Qt 平台插件目录
   (site-packages/cv2/qt/plugins) 会覆盖 QT_QPA_PLATFORM_PLUGIN_PATH → xcb 加载失败
   crash (core dump, "could not load xcb even though it was found")。**正解 = 根本
   不 import cv2**, 帧存 PNG 走 ffmpeg 子进程; 或先设
   `QT_QPA_PLATFORM_PLUGIN_PATH` 指向 PyQt5 真实插件目录 (cv2 未 import 时有效,
   cv2 import 后会被重新污染)。GL item 绘制 warning (pyqtgraph opengl error) 无害,
   帧有内容 (非纯黑) 即有效。
6. 事后 env.render() 不可行 (metaworld env reset 后回到初始态) — 渲染必须边跑边采
   或回放 tr。

## 相关
- muscle-memory 机制 (SK 高亮配合的固化/快通道) 见 zmax-metaworld-real-loop
  references/muscle-memory-2026-09-08.md
- 画布远程操作/中键平移/双实例坑: references/gui-canvas-remote-ops-2026-09-07.md
