# 「输入图像」窗口的仿真实况帧 + 无帧不假冒 (2026-09-17 老倪两问, 都已修+取证)

> 老倪①: 「点击运行后, 仿真渲染的图像不动呢? 应该是实时的, 与运行保持同步啊」
> 老倪②: 「我现在是没有连接真机的, 但是现在选择真机后, 为什么仍旧打开模拟 metaworld 的数据视频呢?」
> 两条根因完全不同 (一条是"看错了环境", 一条是"旧画面残留"), 但都是同一族纪律:
> **画面必须可解释 —— 显示哪一路、哪一帧、帧龄多少, 三者不许打架。**

## ① 「点了运行图像不动」= 窗口渲染的是另一个从没 step 过的 env

| 谁 | env | 行为 |
|---|---|---|
| 窗口仿真源 `_SimGrabber` | `node_logic._YOLO_ALIGNER.env` (单例, 只 `reset(seed=0)` 一次) | **从来没人 step** → 永远同一张初始画面 (FPS 还照样显示 12.5, 骗眼睛) |
| ▶运行 真跑的 | `state_space_sim_real.RealStateSpaceSim` (`state_space_sim_real.py` `_make_env()`) | 每步 `env.step()` 真物理 + 视觉档每步 `_render_frame() → detect_3d` |

⇒ 真画面一直在生成, 只是窗口在看**另一个环境**。

### 修法: 进程共享实况帧槽 (生产者 = 引擎, 消费者 = 窗口)

`tools/gui/state_space_sim_real.py` 模块级:

```python
SS_LIVE_FRAME: dict = {"t": 0.0, "step": None, "rgb": None, "tag": "", "consumed": 0,
                       "want": False, "_file_t": 0.0}
SS_LIVE_STATUS = "/tmp/ss_live_frame.json"   # 1Hz 落盘: step/viewer_consumed → 外部可核对

def ss_publish_live_frame(rgb, step=None, tag="engine"):   # _render_frame() 内调用
    ...  # 只存引用 (不拷贝不渲染), 1Hz 节流写状态文件
def ss_latest_live_frame(max_age=2.0):        # → (rgb, step, age) | None (引擎停了/帧太旧 = None)
def ss_mark_live_frame_consumed():            # 窗口真显示了一帧 → consumed += 1
def ss_set_viewer_wants(want: bool):          # 窗口在看 → 引擎非视觉档也节流渲染
def ss_should_render_for_viewer(step, vision_on, every=5) -> bool:
    # 非视觉档 (R0/L2, 每步本来不渲染) 且有窗口在看 → 每 every 步补渲一帧进槽; 没人看 = 零开销
```

发布点 = `_render_frame()` 里 `np.asarray(self.env.render())` 之后 (⚠️ **必须是这一步 detect_3d
拿到的同一帧**, 不许另开渲染器 —— mujoco 渲染非线程安全); 步号靠 run() 循环开头 `self._live_step = step`。

窗口侧 `tools/gui/yolo_input_viewer.py`:
- `_SimGrabber._grab_once(nl)` (从 `run()` 里拆出来才可单测): 有实况帧 → `info={"engine": True, "step", "age"}` +
  src `engine:▶运行 实况 (metaworld corner2)`; 无实况 → 回退对齐器 env 静态渲染 + **如实标注**
  `sim:metaworld corner2 (引擎未运行 → 静态初始帧)`; 用了实况帧才 `_engine_live_frame_consumed()`。
- 状态栏区分两支: `🎥 引擎实况帧 · 与 ▶运行 同步 · step=N · 帧龄 x.xxs` vs `🧪 仿真渲染帧 … ⚠️ 引擎未在跑 →
  这是**静止的初始帧**; 点 ▶运行 后本窗口自动切到引擎实况`。
- `_start_source`/`_stop_source` 调 `_engine_viewer_wants(True/False)` (关窗/切源即关掉补渲, 零开销)。

### 取证 (`tools/verify_engine_live_frame.py`, 15 项全绿)
- 帧真挂槽 + 1Hz 落盘 (step 正确); **相邻步渲染帧逐帧平均差 0.139/0.132/0.111** = "跟着运行动"的硬证据
  (env 推 `act=[±0.02,0,∓0.02,0.6]` 让场景真变);
- `age=30s` 的旧帧 → `ss_latest_live_frame` 返回 None (引擎停了不许假动);
- 窗口取帧走实况分支 (engine=True/step/age), 无实况且无 node_logic → `(None, None)` 由 run() 兜底;
- R0 门控真值表: want=True 非视觉档 → `[0,5,10]`; 视觉档 → 不再额外渲染; want=False → 全 False。

**坑**: ①测试别断言"首帧落盘就是最新 step" —— 1Hz 节流下首帧写的就是当时那一步 (本次测试第一版因此误报
FAIL, 正确断言 = 睡过节流窗口后再发一帧, 文件必须刷新)。②`_make_env()` 只建 env, 推进前必须 `env.reset()`
(否则 `AssertionError: self._target_pos is not None`)。

## ② 「没连真机, 选真机还在放 metaworld」= 切源只切链路, 没清屏

`_tick_real` 原来只在**帧文件签名变化**时重画 (`if sig != self._last_sig: rgb_from_file(...)`) ——
真机没数据 ⇒ 签名不变 ⇒ **不重画** ⇒ 屏上一直挂着切源前那副 metaworld 画面。状态栏文字确实写了
`❌ 链路无数据`, 但画面骗人。现场数据侧事实 (核对过): `~/zmax_ss_remote/live_frame.json`
= `{"ok": false, "reason": "服务 /zmax/live_frame 不可达"}`, `live_frame.jpg` 还是 3 小时前的旧帧 —— 没连 Orin 属正常。

### 修法三条 (都在 `yolo_input_viewer.py`)

```python
def _placeholder_rgb(self, lines, w=640, h=480):   # QImage 深底 + QPainter 写文字 → RGB ndarray
def _show_placeholder(self, lines, tag):           # 同时清框 (上一路的框属于上一路帧坐标系) + 记 _view_tag
def _reset_view_for_source(self, source):          # 清 _last_sig/_pending_sig/_real_last_fresh + 占位提示
    # real → "🎥 真机源 · 等 Orin 帧 …" (写明通道/排查项) ; sim → "🧪 仿真源 · 等 metaworld 渲染帧 …"
```
- `_start_source()` 两个分支各调一次 `_reset_view_for_source(self.source)` ⇒ **切源即清屏** (别再靠"数据变了"触发)。
- `_tick_real()` 重排: **先判新鲜度** `_fresh = meta.ok and not stale(age>5s)`; 只有 `_fresh` 才允许
  `sig != _last_sig` 上屏; 否则 `_real_last_fresh` 不更新, 超过 10s (`_stale_gap_s`) 且未冻结 →
  `stale-real` 占位 (写明原因 + 最后真机帧时间); 没有帧文件同理给 `no-frame-real` 占位。
- `_frozen` (标定中) 时**不顶掉画面** (标定员正在标的帧不许被占位冲掉)。
- `_view_tag` 标记画面来源 (`real` / `sim-engine` / `sim-idle` / `waiting-real` / `waiting-sim` /
  `stale-real` / `no-frame-real`) —— 显示语义可被程序断言, 不再只靠人看。

### 取证 (`tools/verify_viewer_source_placeholder.py`, 8 项全绿)
真窗口 (offscreen) + 真代码: ①切到真机 → 画面像素已变 (旧仿真帧不留) + `waiting-real`;
②老帧 + `ok=false` → `stale-real` + 状态栏含"无数据/不可达"; ③`ok=true` 但 `age=9999` → 照样不上屏;
④**新鲜帧 → `real` 且画面 = 真机帧** (左上角均值 255 比对, 证明真机路没被修坏); ⑤冻结中保持原帧;
⑥切回仿真 → `waiting-sim`。

测试桩写法: `ZMAX_SS_REMOTE_DIR`/`ZMAX_ANNOT_ROOT` 指到临时目录; `_RemoteChain.ensure/stop =
classmethod(lambda cls: ...)` 打桩 (否则真去 ssh Orin / docker exec); `win._chain_stopped = True` 防自愈重连;
**别把 `win._start_source` 换成 lambda** —— 那样清屏代码根本不执行, 断言会假过 (本次第一版踩过:
真窗口的 `QTimer.singleShot(200, self._start_source)` 是 __init__ 里捕获的原始 bound method, 换属性只挡住后续调用)。

## 通病化 (跨功能复用)
1. **"显示类"刷新条件不能只有"数据变了"**: 输入源切换/连接建立/断流恢复都必须**显式清屏 + 占位 + 写原因**;
   老倪红线 = 不拿旧图、不拿异源图冒充实时。无数据时画面本身要给结论。
2. **同进程共享槽 + 1Hz 状态文件** = 最省事的"跨模块实况同步 + 外部取证"手法 (GUI 进程内 pub/sub,
   进程外可核对 step/consumed), 比截图/OCR 可靠。状态文件要节流, 别每帧写盘。
3. **消费者声明 `want` → 生产者决定是否干活**: 非视觉档引擎本来不渲染, 有窗口在看才节流补渲, 没人看零开销
   (不为"可能有人在看"付代价)。
4. **验证要覆盖"反面"**: 除了"有实况 → 用实况", 必须断言"无实况/帧太旧 → 不许上屏", 否则修完还会以另一种方式骗人。
5. 本机 Hermes 命令坑: 反引号/`$(...)` 命令替换 + 巨型一行会被硬拦 (`BLOCKED (hardline)` →
   `~/.hermes/cache/blocked-scripts/`), 拆成小命令并用 `search_files`/`read_file` 取代码, 别在 shell 里套命令替换。
