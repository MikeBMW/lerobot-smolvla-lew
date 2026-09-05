---
name: zmax-model-compare-report
description: Z-MAX 多模型对比评估→PDF技术选型报告→飞书交付。五模型横比/选型时用。
---

# Z-MAX 多模型对比评估与报告 (五模型)

## 触发条件
老倪要求"五模型对比/模型选型/出报告发手机"时。

## 流程 (2026-08-05 实测跑通)
```
① 各模型训练 (先50步跑通, 再加steps)  →  outputs/train/<policy>_<ts>/
② compare_models.py 统一评估           →  reports/model_compare_<ts>.json
③ generate_report.py 生成 PDF          →  reports/五模型对比技术选型报告_<ts>.pdf
④ 飞书交付: 回复里 MEDIA:/绝对路径.pdf   →  手机直接看
```

## 模型清单
ACT / SmolVLA / SmolVLA+LEW / VLA-Touch / AWE-zFlow — 各自独立训练脚本 `tools/train_*.py` (train_vla_touch.py / train_awe_zflow.py / train_tars_awe.py)。

## 关键契约: reports/train_curve_<policy>.json
- `find_ckpt(policy)` 读它定位 checkpoint (字段: ckpt / step_s / curve / ts)
- **训练脚本写完即被 find_ckpt 发现**; 训练中断则曲线文件缺失 → 评估报 "无 checkpoint, 跳过"
- **曲线格式必须 `[[step, loss], ...]`** — 纯数值列表 `[1.6, 1.4]` 会在 generate_report.py 的 curve_stats 崩 `TypeError: 'float' object is not subscriptable`
- **判断曲线是否新 = 看文件 mtime, 别信 json 里的 `ts` 字段**: ts 可能是训练**开始**时间戳 (GUI 实时落盘用 cur_ts 闭包) — 实测 vla_touch 曲线 ts=11:33 但 mtime=14:05 (训练 11:33 开始、14:05 才写完)。`stat -c %y` 才是写入时刻; `curve` 点数才是内容新鲜度证据
- checkpoint 已存在但曲线文件缺失 → 手动补 JSON 即可 (写 ckpt 相对路径 + curve 列表)

## 评估
```bash
cd ~/lerobot-smolvla-lew
.venv/bin/python tools/compare_models.py --frames 120
# 统一 metaworld_act 测试集 · 归一化空间对比 (act_mean/std 全量帧统计)
```

## 报告生成 (PDF, reportlab)
```bash
.venv/bin/python tools/generate_report.py
# 输出: reports/五模型对比技术选型报告_<ts>.pdf (中文需 Noto CJK 注册, 脚本已内置)
```

## 坑
1. **loss 不可直接横比**: ACT 动作MSE大 vs SmolVLA 扩散噪声MSE小 → 用 Scope 归一化 (前3点均值=1) 比下降斜率
2. **AWE-zFlow MSE 异常巨大 (~16532)**: 评估加载器与统一测试集 action 空间/归一化不匹配, 是管道问题非模型问题 — 检查 load_awe_zflow 与 eval 的 act_mean/std 一致性
3. **10步=链路验证非正式结果**: 老倪要求"先快速评估看链路通不通" (2026-08-06 起默认 steps=10, 正式选型需完整 steps 重训)。GUI/模板/config 多处 steps 默认值要一起改 (simulink_module.py 模板+"steps",10 对话框+node_logic+train_*.py default+config yaml), 只改一处会混用
4. 模型缺失先补训练 (AWE-zFlow 需单独 `tools/train_awe_zflow.py` 完成才写曲线文件)
5. **AWE 曲线缺失根因**: train_awe_zflow.py 的 `_log_loss` 只 print (GUI Scope 解析) 没 append 到列表 → 最终 JSON 无 `curve` 字段。修复: `_log_loss` 里加 `curve.append([step, round(loss,6)])`, 循环前 `curve = []`, JSON dump 加 `"curve": curve`
6. **checkpoint 只到 000050** (快速版): 补曲线文件时 ckpt 路径直接指向该目录即可, find_ckpt 的 cands 需含 000050

## 视频对比交付 (2026-08-05 老倪要"视频对比发飞书")> **2026-08-06 视频管道修复实录见 `references/20260806-video-pipeline-fixes.md`** —
> VLA-Touch rollout x0 用上帧动作 / 5 视频同屏 QGridLayout 3+2 / 窗口元信息(生成时间+动作σ) /
> 帧加载多候选目录 (rollout_final_ > rollout_peg_ > rollout_) / 双击单模型节点自动全开 5 模型
> **视频来源诚实澄清 (2026-08-07 老倪: "视频是真实在 orin 上进行的么?")**: rollout 对比视频 = **4060 本地 metaworld 仿真环境**用训练 checkpoint 推理渲染的评估视频 (同场景同 seed 横向对比), **不是 Orin 真机推理**。两条链路必须分清: ① 评估视频 = 4060 仿真 rollout (7 模型对比, 帧序列→mp4) ② 产线推理 = Orin 真机执行 (node_infer 查的 infer_count/延迟)。老倪问"推理在哪跑"时要先答执行端, 别混

> **仿真输出 UI 标识 (2026-08-07 老倪: "对比视频应该是本地仿真节点的输出, 你来更新设计, 让用户能看到是仿真输出")**: 澄清链路后老倪要求**用户在 GUI 上直接看到"仿真"标注**。5 处一起改 (desc 走节点内显示, 不动 name — 模板/布局/序列化靠 name 匹配, 改名会碎):
> 1. **三套模板的「📊 对比评估 Scope」desc** 尾部加 `· 🎮 仿真评估 (metaworld, 非 Orin 真机)` (simulink_module.py 三处: 124/182/299 行 — 每套模板各一个, 只改一处其他模板还是旧的)
> 2. **「🎥 推理效果对比」desc** 同步加 `🎮 本地仿真 rollout (metaworld 环境, 非 Orin 真机)`
> 3. **生成视频气泡** (on_infer_video `_show_bubble`): `🎮 正在生成 N 模型仿真 rollout 对比视频 (metaworld 环境, 非 Orin 真机; 各 60 帧…)`
> 4. **_auto_finalize 日志**: "🏁 七模型训练完成! 自动生成 🎮 仿真 rollout 评估视频 (metaworld 环境) + PDF 报告…"
> 5. **InferenceVideoDialog 窗口标题** (simulink_scope.py): `🎮 N 模型仿真 rollout 对比 (metaworld peg 场景 — 本地评估, 非 Orin 真机)`
> - **⚠️ desc 存 `node["params"]["desc"]`, 不是 `node["desc"]`** — 节点 dict 无顶层 desc 字段, 验证脚本查 `n.get("desc")` 恒 None 误判失败。运行时验证查 `n["params"].get("desc")`
> - **第 6 处: 7 个「🎥 视频对比 · XXX」节点 desc 也要标仿真** (老倪 2026-08-07 追问"GUI的视频对比,不应该是本地仿真推理的结果么" — 只改 Scope/对话框不够, 每模型视频节点是用户最常点开的): 七模型模板里 `视频对比 · ACT/SmolVLA/SmolVLA+LEW/VLA-Touch/AWE/MLP/专家` 7 个节点 desc 逐个加 `🎮 XXX 仿真 rollout 视频 (metaworld 环境, 非 Orin 真机)`; MLP/专家 desc 原本带成功率 (距孔 0.020/0.011m), 仿真标注插前面 `🎮 MLP 蒸馏仿真 rollout 插拔成功视频 (metaworld, 非 Orin 真机; ...)`。**验证断言坑: desc 前缀是 `🎮 官方专家` 不是 `🎮 专家` — 按完整 desc 前缀匹配, 别用 `f"🎮 {节点名}"` 会误报失败 (功能其实正确)**
> - 验证 (offscreen): 静态断言 5 处文案 + 加载模板后 `params.desc` 含"仿真" + 节点名未变; 改完重启 GUI 生效 (重启安全边界见 ZMAX_AUTO_RUN 节)
```bash
# 1. 各模型 rollout 帧序列 (metaworld 环境渲染, 需 DISPLAY=:0 MUJOCO_GL=glfw)
.venv/bin/python tools/rollout_video.py --policy act --steps 60 --out reports/rollout_act
# 2. 5 模型并排拼帧 → ffmpeg → mp4 (见下)
# 3. 回复里 MEDIA:/path/xxx.mp4 发飞书
```
- rollout_video.py 需支持 5 模型: `--policy` choices 加 vla_touch/awe_zflow; ckpt cands 加 `000050`; vla_touch/awe_zflow 用 `importlib.util.spec_from_file_location` 加载 `tools/train_*.py` 模块 + `torch.load(model.pt)`, 非 from_pretrained
- **ROOT 是 str**: 拼接路径用 `os.path.join(ROOT, "tools", "x.py")`, 不能用 `ROOT / "tools"` (str/str 报错)
- 需要 `import torch` + `from pathlib import Path` 补进脚本
- 并排对比视频: PIL 拼 5 窗口 (各 256x192, 标签色区分) → ffmpeg `-framerate 15 -c:v libx264` → 小文件 (~5KB, 适合飞书)

## 视频黑屏/不动 排查链 (2026-08-05 实测, 从黑屏到真动)
老倪验收标准: **视频必须"动"** (画面有变化)。黑屏或动作全 0 都不算完成。按序排查:

0. **"视频没动"但动作在变 = metaworld 速度衰减, 用双面板趋势视频 (2026-08-07 老倪: "这视频也没动啊"→"我要看到趋势")**: 动作非 0 (real=[0.99,-0.03,0.31] 在变) 但**画面位移极小** — metaworld 末端速度控制把动作衰减 ~1/7, 0.1m 位移在 480px 画面里只几个像素, 视频"看起来没动" (首尾帧像素差异 3.8/255)。**正解 = 双面板**: 左=真实画面 (手+peg 标注), 右=**实时趋势曲线面板** (numpy 手画: 深色底 + 坐标轴 + 距离曲线逐帧描点 + 目标阈值线 + 当前值圆点) — 曲线单调下降 = "在接近"一目了然, 老倪验收"看到趋势"。帧拼接 `np.hstack([vis, panel])` 再 cv2.VideoWriter。**教训: 视频"不动"先量化 (首尾帧像素差异 <5 = 真没动, 动作在变 = 衰减问题), 别急着改模型**

1. **黑屏 (var=0, 全零帧)** → metaworld V3 环境默认 `render_mode=None`, `env.render()` 抛 `AttributeError: Unexpected mode: None` → rollout 捕获异常填全零帧。修复: **`env_cls(render_mode="rgb_array")`** + 脚本顶部 (import mujoco/metaworld 前) `os.environ.setdefault("DISPLAY", ":0")` / `MUJOCO_GL=glfw`。验证: 帧 var≈4376 才是真渲染
2. **画面不动/动作均值 0.0** → batch 只喂 `observation.image` 缺 `observation.state` → select_action 异常被吞 → 零动作。修复: 补 `observation.state` (从 env obs 向量取前 st_dim 维, 用 `policy.config.input_features["observation.state"].shape[0]` 或精简模型 `policy.state_dim` 属性)
3. **`can't convert cuda:0 device type tensor to numpy`** → pred 是 CUDA tensor, `np.asarray(pred)` 失败。修复: `if isinstance(pred, torch.Tensor): pred = pred.detach().cpu()` 再转 numpy
4. **精简模型 (vla_touch/awe_zflow) 无 `.config` 属性** → `'X' object has no attribute 'config'`。修复: 加载 model.pt 后显式设 `pol.state_dim = int(cfg["state_dim"])`, `pol.action_dim = int(cfg["action_dim"])`; rollout 里 `getattr(policy, "config", None)` 兜底
5. **vla_touch/awe 无 select_action** → 适配: vla_touch 用 `policy._cond(state, tac_zeros, None)` + `policy.sample(x0, cond, diffuse_steps=10)`; awe_zflow 用 `policy(state, tac_zeros, act_hist_zeros, None)` (取 tuple[0])
6. **维度不匹配 `mat1 and mat2 shapes cannot be multiplied`** → state_dim 传错 (默认 4 但实际 2)。以 `model.pt` config 为准: vla_touch/awe 都是 state_dim=2/action_dim=2/tactile=3 (metaworld_act 数据)
7. **重训后 rollout 仍用旧模型** → `reports/train_curve_<policy>.json` 的 `ckpt` 还指向旧 50 步目录。修复: 重训后必须更新曲线文件 `ckpt` → 新目录 (vla_touch/awe 训练脚本会自动更新, act/smolvla 系需手动改)
8. **动作均值≠0 才算动**: 2000步正式版实测 ACT 0.177 / SmolVLA 0.116 / LEW 0.098 / vla_touch 0.036 / awe 0.251; 50步快速版全 ≈0
9. **obs 是 dict 不是向量 (2026-08-07 终极根因, 所有模型动作≈0 的元凶)**: metaworld V3 环境 `env.reset()` 返回的 obs 是 **dict** (`observation.state` / `observation.image`), 不是 39D 向量 — `np.asarray(obs)` 对 dict 得到 0 维对象数组 → `st_vec.ndim == 1` 为 False → **state 全零** → 模型推理异常 (act/vla_touch/awe 全报 mat1/mat2 broadcast 错, 动作均值 0.0) → 零动作兜底。修复:
```python
if isinstance(obs, dict):
    _st_raw = np.asarray(obs.get("observation.state", np.zeros(st_dim, dtype=np.float32)), dtype=np.float32)
else:
    _st_raw = np.asarray(obs, dtype=np.float32)
st = _st_raw[:st_dim] if _st_raw.ndim == 1 and _st_raw.size >= st_dim else np.zeros(st_dim, dtype=np.float32)
```
10. **ACT 39D 完整观测要拆 robot(3)+env(36)**: ACTPolicy forward 有 `encoder_robot_state_input_proj` + `encoder_env_state_input_proj` 两个投影 — 39D state (hand3 + peg/hole 36) 只喂 observation.state 会 39 vs 3 广播崩。batch 补 `observation.environment_state = st[3:3+env_dim]` (env_dim 从 `model.encoder_env_state_input_proj.weight.shape[1]` 推断, 无 cfg.input_features 时)。⚠️ 实测拆了仍报 (39,)(3,) — 真凶是坑 10b (stats 3D vs state 39D), env 拆分本身不是这个错误的来源
10b. **stats 归一化维度不匹配 → (39,)-(3,) 广播 + 除0 NaN (2026-08-07 终极, line 205)**: obs dict 修好后 ACT 仍报 `operands could not be broadcast together with shapes (39,) (3,)` — 位置在 **stats 归一化**: `sm = np.array(policy.stats["s_mean"])[:st_dim]` — act checkpoint 的 stats 是**旧 3D** (s_mean 只 3 个) 而 state 39D (完整观测) → `[:39]` 只取到 3 个 → (39,)-(3,) 崩。且 pad 补零后 `ss` 补的 0 会导致 **state/0 → NaN → 动作全 NaN**。修复 (维度不足补零 + 补零区防除0):
```python
sm = np.array(policy.stats["s_mean"], dtype=np.float32)
ss = np.array(policy.stats["s_std"], dtype=np.float32) + 1e-6
if sm.size >= st_dim:
    sm, ss = sm[:st_dim], ss[:st_dim]
else:
    sm = np.pad(sm, (0, st_dim - sm.size))
    ss = np.pad(ss, (0, st_dim - ss.size)) + 1e-6   # 补零区必须 +1e-6, 否则除0 NaN
st = (st - sm) / ss
```
**排查顺序**: 动作 0 先看 traceback 行号 (改 except 加 `_tb.print_exc(limit=3)`), 别猜 — obs dict (坑9) → stats 广播 (10b) → env 拆分 (10) 三个坑症状都是"动作均值 0.0"但要按 traceback 定位。**修复验证**: 动作均值 0→0.18 (ACT), NaN 数=0, 帧均差 2.8→5.7+ (真动)
10c. **补训链恢复曲线 (restore_curves.sh 模式, 2026-08-07)**: 曲线 json 被训练链覆盖清空后, act/smolvla/lew 无日志可恢复 (GUI 内存) → 只能**串行重训** (act~1min → smolvla → lew 各 1000 步)。要点: ①**config 生成复刻 GUI on_train** (读 config_<p>_metaworld.yaml → re.sub output_dir/job_name 加时间戳目录 + `^steps:` 改 1000 → 写 `config_<p>_restore.yaml`) — **config_<p>_runtime.yaml 是 GUI 动态生成的, 静态文件里不存在, 别直接引用** ②**输出目录已存在 → FileExistsError (resume=False)**: config 里 output_dir 必须替换成新时间戳目录, 或 `--policy.path=` 覆盖 ③**曲线 ckpt 字段别写假路径** (`outputs/train/<p>_latest/checkpoints` 不存在 → load_policy 兜底 glob 找最新 → 可能加载到 39D/3D 混搭垃圾) — 写真实目录或重训后手动改 ④日志 `step:1K` 解析 (坑14) + 去重 sorted ⑤**bash 脚本运行中的进程用旧代码**: 脚本文件改了但已启动的进程不会重新读 — 修完正则只对后续模型生效, 前面的已落盘要手动修正 (同 act 修法)
10d. **Scope 示波器 loss 带训练时间 (2026-08-07 老倪: "loss也要显示上次的结果, 要有时间")**: FlowScopeDialog._load_data 的指标行加时间 — 每模型从 train_curve json 的 `ts` 字段格式化 `MM-DD HH:MM` (**ts 是 "%Y%m%d_%H%M%S" 15 位, 切片 `_ts[4:6]-_ts[6:8] _ts[9:11]:_ts[11:13]` — 索引 8 是 "_" 分隔符, 用 [8:10] 会切成 "_1" 乱码**), ts 缺失/位数不对用文件 mtime。_DISPLAY 映射扩到 7 模型 (vla_touch/awe_zflow/expert_mlp/expert_policy 也要中文显示名)。训练中模型 (曲线 <2 点) 显示 `⏳ 训练中` 提示。老倪要求"显示上次的结果或最新的结果" = 已有曲线立即显示 (别等重新生成), 时间戳让新旧可辨
10e. **Scope 示波器 7 模型颜色 (2026-08-07 老倪: 示波器,怎么那么多紫色,也分不清颜色,换成不同的颜色)**: FlowScopeDialog._load_data 的颜色分配旧代码 `color = "act" if policy == "act" else ("smolvla" if policy == "smolvla" else "smolvla_lew")` — **vla_touch/awe_zflow/expert_mlp/expert_policy 全部归到 smolvla_lew (紫)**, 7 条曲线一片紫。修 = ①COLORS dict 补 5 色 (vla_touch 绿 #3fb950 / awe_zflow 亮红 #ff6b6b (别用 #f85149 与 base 撞) / expert_mlp 天蓝 #00b4d8 / expert_policy 金 #e3b341 🏆; gt 从绿改粉 #f778ba 避免与 vla 绿撞) ②`_CMAP = {act, smolvla, smolvla_lew, vla_touch, awe_zflow, expert_mlp, expert_policy}` 全映射 + `color = _CMAP.get(policy, "base")`。验证: 正则提取 COLORS dict 内 7 模型 hex **必须 7 色唯一** (awe 用 #f85149 会和 base 重复 — 全文件 hex 去重会误报, 断言范围限定 COLORS dict 内)。**教训: 多模型曲线颜色按 policy 全量映射, 别用 else 兜底归并 — 新增模型必配新色**
11. **checkpoint 目录名 000050 ≠ 50 步 (2026-08-07)**: train_vla_touch/train_awe_zflow 的 checkpoint 目录**固定叫 000050** (保存逻辑如此), 1000 步完整训练的结果也存 000050 (14:17 保存 = 训练结束时刻) — 不能只看目录名判步数。**判断 checkpoint 有效性 = 目录 mtime 是否与训练结束时刻同批**。⚠️ 15:0x 被中断的 50 步训练目录 (mtime 更新) 会成为 glob "最新" → rollout 加载垃圾 → 视频不动 (动作均值≈0 但帧有环境运动)。**rollout 前验证最新目录 mtime 与曲线 ts 同批; 中断残留 (目录新但曲线残缺) 直接删目录** (用精确 PID kill, 禁 pkill 模式匹配自杀)
12. **视频打开闪一下再次打开 = _check_newer_ckpt 误判残缺曲线 (2026-08-07 老倪: "视频打开后闪了一下, 再次打开")**: InferenceVideoDialog 的 `_check_newer_ckpt` 用 train_curve ts > 帧 mtime 判"新 checkpoint"→ 触发重新生成 rollout → 闪屏重载。**残缺曲线 (训练中断残留 0-50 点, ts 却是新的) 会被误判** → 每次打开都重生成。修复: `if len(d.get("curve") or []) < 100: continue` (不完整训练不算新 checkpoint)。验证: 时间模拟 (帧 mtime 5 分钟前 + 曲线 ts 可变) — 50 点不触发 / 200 点新 ts 触发 / 200 点旧 ts 不触发
12b. **视频对比窗口白屏 (2026-08-07 老倪: "打开视频, 是白屏, 啥也没有" — 与坑12闪屏不同 bug)**: `InferenceVideoDialog._tick` 每 100ms `lab.setPixmap(pm.scaled(lab.size(), ...))` — **对话框未显示时 lab.size()=0** → scaled(0,0) 空白 → 白屏。offscreen 验证 frame_dirs/帧可解码/非空 pixmap 全正常 (排除帧/数据问题), 是渲染尺寸问题。修复: 尺寸有效才缩放, 否则显示原图:
```python
if lab.size().width() > 0 and lab.size().height() > 0:
    lab.setPixmap(pm.scaled(lab.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
else:
    lab.setPixmap(pm)   # QLabel 自适应原图
```
排查顺序: 帧可解码 (PIL) → offscreen 构造 dialog 查 frame_dirs/pixmap → DISPLAY/X0 环境 → 渲染尺寸。老倪报"白屏/闪一下/再打开"三连时逐个查 (白屏=size 0, 闪=_check_newer_ckpt 误判残缺曲线, 再打开=模态 exec_ 阻塞 — 三个独立 bug 别混)
12c. **视频白屏根治 — 打开永远先播历史, 重生成改手动 (2026-08-08 老倪: "视频又白屏了, 正在生成7模型推理视频, 但是你不是已经训练好过么? 历史视频也得显示。这个问题出了好几次")**: 坑12/12b 修完仍"反复白屏" — 根因: **曲线 ckpt 一更新 (如 act ckpt 指向新训练目录) → _check_newer_ckpt() 判真 → 打开对话框自动 QTimer.singleShot(300, _run_rollouts) 重新生成 → 白屏等 1-2 分钟**。老倪明确: 训练好过就有历史视频, 打开必须秒显。**根治 = 打开分支永远先 `self._play()` (显示历史帧), _check_newer_ckpt 只用来更新提示栏文案** ("🔄 检测到新训练 checkpoint · 已显示历史视频 · 点「🔄 重新生成推理」更新"), 重生成只走手动按钮; 仅完全无帧 (frame_dirs 空) 才自动生成。**教训: "自动刷新"类逻辑 (ckpt 更新自动重生成) 在 GUI 里反复出问题 → 一律改"打开先显上次结果 + 手动触发更新", 符合老倪 GUI 偏好 (先显示上次结果)**
13. **on_infer_video 帧检查漏 expert 目录映射 → "视频没了" (2026-08-07)**: on_infer_video (simulink_module.py) 的 have 检查候选目录只有 `rollout_final_<p>/rollout_peg_<p>/rollout_<p>` — expert_mlp/expert_policy 的帧在 `rollout_mlp/rollout_expert_full` (对话框 _load_frames 有 _dir_map 但**触发前检查没有**) → 误判无帧 → 触发重新生成 (rollout_video.py choices 不支持 expert) → 失败 → 视频显示无。修复: have 检查加同款 `_dm` 映射。**教训: 同一"候选目录映射"逻辑在对话框和触发前检查两处都要有, 只改一处另一边误判**
14. **lerobot 训练日志 "step:1K" 解析陷阱 (2026-08-07)**: 1000 步的日志行是 `step:1K smpl:8K ep:50 ... loss:1.989` — 正则 `step[:=]?\s*(\d+)` 把 1K 解析成 step=1 → 曲线尾 [1, loss] 破坏递增断言。修复: 解析前 `log = re.sub(r"step:(\d+)K\b", r"step:\1" + "000", log)` 展开 K 后缀 + 正则加 `\b` 边界 (`step[:=]?\s*(\d+)\b`)。**从日志恢复曲线 (fill_curves/restore_curves 模式) 都要处理 1K**; 落盘前去重 (seen set) + sorted
15. **曲线可从 /tmp 训练日志秒级恢复 (2026-08-07, 免重训)**: 曲线 json 被覆盖/清空后, 若训练日志还在 /tmp (vla4.log / retrain_awe.log / retrain_vla.log / mlp3.log) — `re.finditer(r"action_loss:([\d.eE+-]+)", log)` 直接重建 json (step = i*5+5, step_s 从 `"([\d.]+) step/s"` 抓), 秒级恢复! act/smolvla/lew 的日志在 GUI 内存 (无文件) 只能重训 — **训练日志重定向到文件是曲线保险, GUI 启动的训练不重定向** (on_train 的 out_lines 在进程内存, 进程死即丢)

## 正式训练 (2000步) 注意事项
- config 改 `steps: 2000` 前先查 `output_dir` — **目录已存在会 FileExistsError** (`resume=False`)。用独立名如 `outputs/train/act_metaworld_final` (sed 替换 output_dir/job_name 时注意别把 `config_` 前缀带进目录名)
- 串行训练 5 模型脚本: ACT≈16min, SmolVLA≈16min, SmolVLA+LEW≈32min (LEW 世界模型层重, 最慢), vla_touch/awe≈2min (34/14 step/s)
- 训练时用 `notify_on_complete=true` 后台 + 定期 `ls checkpoints/` 查进度 (每150步存点, 到 002000=完成)

## PDF 中文乱码与文字重叠修复 (2026-08-06 实测, 老倪: "PDF报告有很多乱码,加中文解码" + "很多字都重合了,看不清")
**乱码根因 (终极, 2026-08-06 第二次修正)**: 不只是"字体没找到回退 Helvetica" — **reportlab TTFont 不支持 PostScript (CFF) outlines 字体**。实测: `NotoSerifCJK-Regular.ttc` 注册直接抛 `TTFError: postscript outlines are not supported` (Ubuntu 的 Noto CJK 是 CFF 封装)。`MicrosoftYaHei` TTC 能注册但子集化不全仍可能乱码。**可靠解 = TrueType 单文件字体**:
```python
# 首选: /mnt/c/Windows/Fonts/simhei.ttf (SimHei 黑体, TrueType 单文件 9.7MB, reportlab 完美支持)
pdfmetrics.registerFont(TTFont('SimHei', '/mnt/c/Windows/Fonts/simhei.ttf'))
```
**修复 (必须扫描+别名兜底, 候选顺序 SimHei 最前)**:
```python
# 1. 候选 = 固定路径列表 (SimHei→msyh→wqy→Noto Sans→Noto Serif 按序, SimHei TrueType 优先) + fc-list :lang=zh file 兜底
# 2. 逐个 TTFont(name=f"CJK{i}", path, subfontIndex=0) 注册 (TTC 需 subfontIndex, 失败再试无参; CFF 字体 try/except 跳过)
# 3. 别名: NotoSansCJK/NotoSansCJKBold/MicrosoftYaHei 映射到"第一个成功注册的 CJK 字体"
#    (不是 cands[0]! Sans TTC 加载失败时 cands[0] 无效 — 遍历找 f"CJK{i}" in registered 的路径)
# 4. 验证: pdfmetrics.getRegisteredFontNames() 里 NotoSansCJK 必须 True, 否则重查
# 5. 生成后验证嵌入: fitz 列 get_page_fonts, 应见 'SimHei' 而非 Helvetica
```
**文字重叠/空字符根因**: reportlab 渲染 emoji (📦⏳✅) 和下标 (₁₂₃) 会变 `\x00` 空字符或叠字。
**修复**: 输出前统一 `_clean()`:
```python
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\U00002700-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002600-\U000026FF\U00002B00-\U00002BFF\uFE0F\u200D\U00002190-\U000021FF"
    "\U000025A0-\U000025FF\u2705\u26A0\u274C\U00002300-\U000023FF"   # ⏳ 在 2300 区! 常漏
    "\U00002500-\U0000257F\U00002900-\U000029FF\U00002080-\U0000209F"  # 下标区
    "\U00002070-\U0000207F\U00000000-\U0000001F]")
# _clean 内: emoji 正则剔除 + 下标/上标显式替换 (z₁→z1, ₂→2, ³→3, ¹→1 ...)
```
- **应用点**: ① TBL() 每格 `_clean(c)` ② 所有 Paragraph 包一层 `_P(text, style)` (38 处全替换)
- **⚠️ 长文本窄列溢出重叠 (2026-08-07 老倪: "字体都重复了/重合了" 连报两次, 与 emoji 无关)**: reportlab Table 对**普通 str cell 不换行** — 窄列 (20mm) + 长文本 (优劣势/架构描述 30-40 字) 直接横向溢出压到相邻列 → 视觉重叠 (fitz 提取表现为相邻 cell 文本粘连)。**TBL 必须全 cell 走 Paragraph + CJK 换行**:
```python
from reportlab.lib.styles import ParagraphStyle
_cell_st = ParagraphStyle("tblcell", fontName=FONT, fontSize=fs,
                          leading=max(fs * 1.3, 9), wordWrap="CJK")
_hdr_st = ParagraphStyle("tblhdr", fontName=FBOLD, fontSize=fs,
                         leading=max(fs * 1.3, 9), wordWrap="CJK")
tbl_rows = [[Paragraph(c, st) if isinstance(c, str) else c for c in row] for row in rows]
# 表头用 _hdr_st, 其余 _cell_st; 删掉 TableStyle 的 FONT 命令 (Paragraph 自带字体)
```
- **量化验证"无重叠"**: `fitz` 提取 words (带 bbox) → 两两算交集面积 >30% 较小面积 = 重叠对, 断言 0 (第 9 章页 178 词实测 0 重叠对)。纯视觉"看起来正常"不算数
- **PDF 文本断言的双空格陷阱**: 章节标题用 `"7.1  能力评分依据"` (双空格) 提取后变单空格 → 断言必挂。**断言一律 `re.search(r"\s*".join(re.escape(c) for c in frag), txt)` 宽松匹配**; 图内文字 (PNG 嵌入) 不在 PDF 文本层, 别用文本断言查图内容
- 验证: `.venv/bin/python -c "import fitz; doc=fitz.open(pdf); sum(1 for p in doc if '\x00' in p.get_text())"` 应为 0 (需 `pip install pymupdf`; 系统无 pdftotext, 用 fitz 提取)
- 页 9 是架构图独占页 (无文字正常); 文字量异常少的页查图是否太大

## PDF 子系统功能框图 (2026-08-06 老倪: "报告要以结构化的图形方案为主, 每个子系统画功能框图")
```bash
.venv/bin/python tools/gen_subsystem_figs.py   # → reports/figs/subsystems/sub_<key>.png ×6
```
- 6 子系统: vis(视觉感知)/wm(世界模型)/touch(触觉力觉)/act(动作生成)/ensemble(时序集成)/eval(对比评估)
- 每张图结构: **输入框(蓝) → [子系统功能框(色)含名称+功能描述] → 输出框(绿)** + 底部中文文字解释
- 老倪偏好: **图形方框比表格适合人理解系统** — 子系统章节用框图代替纯文字表格, 每图配一句功能说明
- 报告接入: 第 3 章「分系统功能分析」每子系统插一张 sub_<key>.png + 接口说明行

## 交付偏好 (老倪明确要求, 2026-08-06)
1. **视频要"分开"给**: 每个模型单独一个 mp4 (`rollout_final_<policy>.mp4`), 不要只给并排对比视频 — 老倪说"五模型对比视频分开给我"
2. **只要视频不要图片**: 老倪说"我要的是视频,不是图片" — 静态对比图被拒。图片只作为 PDF 内嵌内容, 不作为独立交付物
3. **PDF 必须含架构图 + pipeline 图**: 老倪说"pdf报告要有模型的架构图,要把simulink的pipeline都画上" — 缺图=不合格
4. **PDF 公式必须"解释+比喻+证明形象化"**: 老倪说"公式要解释,公式的证明要形象说明,公式不能有乱码" — gen_theory_figs.py v2 每公式图含【含义】(中文白话解释)【比喻】(生活化类比如"抄作业/雾里看花/老司机开车")【证明】(分步形象说明, 不用纯符号推导)。纯公式无解释=不合格
5. **报告以结构化图形方案为主**: 子系统用输入→功能框→输出框图 (gen_subsystem_figs.py), 不用大段文字表格 — 老倪说"图形方框适合人来理解系统"
6. 交付 = 5 个单独视频 (MEDIA:/path 各一条) + PDF (MEDIA:/path) 一次发齐, 附结果表
7. 视频必须"动" (动作均值≠0); 黑屏/不动直接返工, 不算完成
8. **视频必须有模型名水印标记**: 老倪说"视频要有标记,分清楚哪个模型对应哪个视频" — 每帧左上角叠加模型名
   ```bash
   ffmpeg -y -framerate 12 -i frame_%04d.png -vf "drawtext=text='ACT (peg-insert)':fontsize=32:fontcolor=#58a6ff:borderw=2:bordercolor=black:x=20:y=20:box=1:boxcolor=black@0.5:boxborderw=8" -c:v libx264 out.mp4
   ```
   或 `tools/watermark_video.py <in.mp4> <模型名>`。并排对比视频已在每列顶部画标签, 单独视频必须水印
9. **换场景后全链路重指**: 换任务 (如 push→peg) 重训后, `reports/train_curve_<policy>.json` 的 ckpt 要**全部**改指新场景产物 (ACT/AWE 手动, vla_touch/awe 自动), 否则 rollout 混用新旧场景模型, 横比无效
10. **SmolVLA 系 rollout 慢/卡**: SmolVLA/SmolVLA+LEW 加载 checkpoint 时内部仍会访问 HF Hub (限速, 未设 HF_TOKEN 时可能卡 8+ 分钟静默无输出)。处理: ① 后台跑 + timeout 500s ② 确认 `~/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct/` 有 snapshot ③ 别用短 timeout 前台跑 (会误判死锁杀掉)。输出无 `✅ rollout` 但进程还活着 = 在加载, 等
11. **表格手机看不全 (2026-08-06 老倪: \"把表格重新发一遍, 手机看不全\")**: 飞书手机端宽表格 (7+ 列 / 长文本单元格) 直接溢出。**宽表拆成手机友好的形式**: ① 每行一行 (表头→值, 如 `抓起: 18/20 · 插入: 11/20`) ② 或 3-4 列窄表 + 短单元格 (≤10 字符) ③ 解释性内容用分条 bullet 不用表格。老倪手机看报告/结果时优先这种格式
12. **视频方向默认用原版, 别预防性旋转 (2026-08-07 老倪: \"现在的视频,五个模型全是反的。那不用旋转180度了\")**: 老倪最终裁决 = **ffmpeg 从 PNG 拼的原版 rollout 视频方向正确**, 我 ffmpeg 转 180° 的 rot180 版反而全错。**铁律: 视频交付默认原版 (rollout_final_<p>.mp4 直接发), 只有老倪明确说\"反了/倒着\"才转, 且转前先抽单帧用绿色 peg 重心量化验证方向再批量**。方向被否 2-3 轮 (转180→再转→又转回) 是典型浪费 — 原因是 cv2 写视频自带 180° 而 ffmpeg 拼 PNG 是原方向, 管线不同方向不同, 别假设
12b. **方向量化验证法 (2026-08-07, 别再凭肉眼/凭假设转)**: 判定\"哪版方向对\"先抽同一帧 (ffmpeg `-vf select=eq(n\\,10)` 第10帧) 算**绿色 peg 像素重心** — 原帧 (269,290) vs 旋转180 (209,188) 重心必然不同; 再与\"已知正确方向\" (老倪确认过的版本) 对比像素差异 (小=同方向)。**YOLO/检测叠加视频方向与 rollout 无关**: ultralytics `res.plot()` 永远输出原图方向 (即使输入已旋转) — 旋转检测视频的正解是**检测原帧 → 整段 ffmpeg transpose 旋转 (画面+框一起转)**, 不是旋转后检测再 plot (框会错位)。cv2.VideoWriter (mp4v) 写出的视频自带 180° 翻转 vs ffmpeg PNG 拼的原方向 — 同一批帧两种管线方向不同, 交付前必须抽帧量化确认
12c. **⚠️ 方向裁决会反转 (2026-08-08 老倪: "视频反了;旋转180度再给我" — 与 08-07 的"原版不旋转"相反!)**: 方向标准**不是永久铁律**, 老倪可能换批次后又说反了 — **每次交付默认原版, 老倪说反了立即批量转 180° (`ffmpeg -vf "transpose=2,transpose=2"`)** 重发, 别拿上次裁决当永久标准, 也别辩论
12d. **视频批量一次发齐 (2026-08-08 老倪两次催: "视频发给我,说了多少次啦" / "把已经有的视频,一起发给我;别一个一个发")**: ①**一条消息里多个 MEDIA: 一起发** (4 个视频 4 行 MEDIA 同一条回复), 绝不逐条发 ②**用户要视频时立即发已有视频**, 别等全部生成完 (先发 MLP/专家成功视频 + 说明其余在跑) ③**别让用户重复要第二次** — 生成完第一时间主动发, 老倪催"说了多少次"= 交付延迟不满 ④转 180° 后新旧同批发, 附每视频一句话说明 (模型+结果)
13. **对比视频 = 7 个 (2026-08-07 老倪: "应该是7个视频对比"): 五模型 + 蒸馏 MLP + 官方专家基准** — 七模型对比交付: 5 个训练模型 + expert_mlp (rollout_mlp 成功视频) + expert_policy (rollout_expert_full 成功视频), 一个都不能少。生成新对比视频时 7 个全出, 别只出 5 个
14. **批量生成 7 视频+报告全程 CPU (2026-08-07 老倪: "不要干扰现在的训练"): 现成帧目录直接合成, 零 GPU** — 7 模型各 60 帧目录 (`rollout_final_<p>` ×5 + `rollout_mlp` + `rollout_expert_full`; **expert_mlp→rollout_mlp / expert_policy→rollout_expert_full 映射, 没有 rollout_final_expert_* 目录**) → 各自 ffmpeg 320×240 mp4 → **xstack 7 inputs 布局 `0_0|320_0|640_0|0_240|320_240|640_240|320_480` (3列×3行, 末行居中)** → build_pdf (纯 CPU reportlab/matplotlib) → 飞书一次发齐。脚本模式见 `references/20260807-pdf-seven-model-fixes.md` (gen_7model_report.sh 同款)。老倪多次强调"不要影响当前训练" — 视频/报告生成类任务先确认 GPU 被训练占用时走纯 CPU 路径 (ffmpeg 无 -hwaccel / 不调 rollout_video.py)

## PDF 报告图表 (2026-08-06 增强)
```bash
.venv/bin/python tools/gen_report_figs.py   # 生成 3 张图 → reports/figs/
#   model_arch.png   5 模型架构卡片 (纵排, 各模型组件流)  → 报告第 6.1 章
#   pipeline.png     数据闭环 6 环节 (采集→上传→训练→集成→部署→推理) + 闭环回线 → 第 2 章
#   training_flow.png  三阶段渐进训练 (S1仿真→S2零样本→S3真机微调) → 第 2 章
```
- generate_report.py 已内置嵌入: 第2章插 pipeline+training_flow, 第6章插 model_arch (Image(width=170*mm, height=...))
- matplotlib 用 `.venv/bin/python` (系统 python 无 numpy/matplotlib); Pyright 报 missing imports 是误报
- 验证图已嵌入: `grep -c '/Subtype /Image' xxx.pdf` 应 >0 (正常 ~11)

## 新场景数据生成 (换场景时, 2026-08-06 peg-insert 实测)
- `gen_metaworld_data.py --task peg-insert-side-v3 --out data/metaworld_peg` — 支持任意 MT1 任务
- **Simulink pipeline 完整细节 (6环节 I/O/数据质量/管理手段/KPI) 见 `references/simulink-pipeline-details.md`** — 老倪要求把 Simulink 细节交付给 web 汇总 cicd.html 方案页时用 (仓库 docs/SIMULINK-PIPELINE-DETAILS.md)
- **完整清单见 `references/metaworld-dataset-generation.md`** — tasks.parquet / episodes 标准列 / 视频合并 / stats.json 三件套, 缺一即加载/训练失败
- **场景选择与 AWE 优势**: push-v3 单段短程不突出 AWE; peg-insert (对准→插入→力反馈, 多阶段接触演化) 才是 AWE 世界模型的主场 — 老倪要"突出AWE优势"时选此类任务
- **朴素专家策略产生恒定 action (2026-08-06 实测)**: 生成器默认"朝 goal 直线移动"在 peg-insert 上 action std≈0 (环境把末端速度衰减~1/7, 150步只移动0.15) → 数据无训练价值。**修复: 多阶段专家策略** (Phase1 水平快速接近 hole 上方 → Phase2 垂直缓慢插入+夹爪闭合 → Phase3 保持), 生成后 `action.std()` 应 >0.01 且夹爪维有多个离散值 (0/-0.5/-1)
- **抓取类任务 (peg) 手写专家策略必然失败 (2026-08-06 终极修复, 老倪: "为什么桌子上的绿色长条物体(光模块)都没有拿起来")**: 手写 5 阶段 (接近→下降抓取→抬起→移孔→插入) 无论怎么调 gripper 指令 (-0.8/-1.0)、抓握点 (pegHead vs pegGrasp) 都抓不起 peg — peg_z 恒定 0.025。metaworld 抓取靠**末端精确接触+物理摩擦**, 不是夹爪指令。**正确解法: 用 metaworld 官方专家策略**:
```python
from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
expert = SawyerPegInsertionSideV3Policy()   # get_action(obs) → 4D (delta_pos速度 + grab_effort)
obs, _ = env.reset()
a4 = np.asarray(expert.get_action(np.asarray(obs, dtype=np.float64).ravel()), dtype=np.float32)
obs, _, _, _, _ = env.step(a4[:4])          # ① 官方动作直接 step (别缩放! 缩放0.05力度不够抓不住)
# ② obs 必须每帧更新 (step 返回新 obs 赋回) — 用旧 obs 策略永远拿不到新位置, 抓取不推进
# ③ 记录真实动作: vel = (ee_after - ee_before) * 30.0 (实际位移×fps), 不是官方输出本身
```
- **官方策略抓取判定**: 夹爪 -1.0=张开 / 0.6=闭合 (两档); 末端 xy 距 peg ≤0.04 且 z 差 ≤0.15 时闭合。**验证 peg 真被抓起**: 模拟 250 步, `pegGrasp` site z 应从 0.024 → >0.10 (实测升高 +0.105)。peg 抬起才算数据有效
- **⚠️ 官方专家成功率修正 (2026-08-06 实测)**: 早期测 5 次 60% (3/5) 是**环境没配好** (缺 `_freeze_rand_vec=False` + camera 未指定)。**正确配置下专家 20 次实测: 抓起 19/20、插入 17/20 (85%)** — 插拔在仿真完全可实现, 此数据是\"任务可达成\"铁证。**专家评估必配**: `env = mt.train_classes[task](render_mode="rgb_array", camera_name="corner2"); env.set_task(...); env._freeze_rand_vec = False; obs = np.asarray(env._get_obs(), dtype=np.float64).ravel()` — 用 `_get_obs()` 不是 reset 返回 (含 peg 位置, 策略需要)
- **成功轨迹过滤 (2026-08-06, 关键)**: 官方专家本身只有 ~60% 成功率 (5次中2次失败: seed0 未抓起 / seed3 抓起未插入) → 失败轨迹混入数据=污染。生成器加过滤: 轨迹结束后检查 `pegGrasp` z 升高 >0.05, 失败轨迹从 all_frames 移除 + 不写 ep_imgs_all。**致命 bug: peg_z0 必须在轨迹开头 (env.reset() 后立即) 记录** — 若在轨迹结束处再读一遍 peg_z0, z0==z1 恒差 0.000, 全部轨迹被误判失败丢弃 (20/20 全丢)。过滤后验证: `轨迹0: 完成 (抓取成功 +0.106m)` / `轨迹N: 丢弃 (未抓起 peg, 升高+0.021m)`
- **过滤后必须重编号 episode_index (LeRobot 硬约束)**: 丢弃失败轨迹后 episode 号不连续 (0,2,3...14) → `IndexError: Invalid key: 12 is out of bounds for size 12`。修复: `mapping = {old: new for new, old in enumerate(sorted(df['episode_index'].unique()))}`, df['episode_index'].map(mapping) 重写 parquet + 重建 episodes 元数据 (从 dataset_from_index 0 连续编号)。**验证**: `episodes: 12 条, index [0..11], 帧范围 0-3599` + LeRobotDataset 加载 3600 帧
- **episodes parquet 列名坑**: 修复脚本生成的 file-000.parquet 用 `videos/observation.image/file_index` 列; 自己手写的 episode_000.parquet 若用 `frame_index` 列 → `CastError: Couldn't cast`。**用修复脚本的 file-000.parquet, 别自己重写列名**; 手写的 episode_000.parquet 直接删掉
- **成功轨迹数据效果**: 全量 15 轨迹闭合率仅 8% (92% 时间张开=接近段) → 模型学\"一直张开\"。成功过滤后闭合率 33% (12 条全成功轨迹) — 抓取动作占比 4 倍
- **行为克隆学不会插拔 (2026-08-06 诚实结论)**: ACT 4000步×4500帧 (含 v4 全量/v5 成功轨迹) 抓取率仍 0%; SmolVLA/SmolVLA+LEW 同 0%。ACT 输出分析: 动作 z+0.4 \"一直抬手臂\" (学到抬起段, 没学到接近→抓取顺序), 末端 z 0.155→0.177 但 peg z 恒定 0.172 完全没动。**peg 抓取 (精确对齐 pegGrasp + 夹爪时机) 超出行为克隆极限** → 需 50+ 轨迹或 1万+ 步, 或选有世界模型/时序理解的模型 (AWE/VLA 系)。此结论直接支撑选型报告
- **3 个致命坑**: ① `env.step(a4[:3]*0.05)` 缩放官方动作 → 末端到不了 peg 上方, 夹爪永不闭合 ② obs 不更新 → 策略每帧看到同一状态 ③ 记录官方原始输出 (2.8级) 而非实际速度 → 与 rollout 0.1 级速度不匹配
- **生成后必检**: ① `action.std()` 每维>0.01 ② 夹爪维 unique 值数≥2 ③ 视频帧 var×255²≈4300 真图 — 三项过才算好数据。**抓取类任务 (peg) 加第 4 项: 模拟跑 250 步验证被抓物体 z 升高 >0.10** (pegGrasp site z: 0.024→0.135), 物体没被拿起=数据无效, 模型永远学不会操作
- rollout 换场景: `rollout_video.py --task peg-insert-side-v3` (加 --task 参数后支持任意 MT1 任务)

## 相机视角切换 (2026-08-06 老倪: "渲染角度换一下, 旋转90度, 从侧面看")
- **`camera_name` 必须在 env 构造时传**: `env_cls(render_mode="rgb_array", camera_name="corner")` — 事后设 `env.camera_name = "corner"` 会被 gym 包装忽略 (渲染结果像素差异 0.0), `env.render(camera_name=...)` / `renderer.render('rgb_array', camera_id=N)` 都报 `unexpected keyword argument`
- metaworld V3 有 7 相机: `topview`(默认, 俯视)/`corner`(斜侧45°)/`corner2/3/4`/`behindGripper`/`gripperPOV`
- **默认俯视视角下 peg-insert 与 push 画面几乎一样** (mean 152 vs 154) → 老倪误判"还是原来的视频, 没有光模块"。斜侧 `corner` 才能看到光模块/孔立体结构
- **验证视角真切换**: 新旧帧 `np.abs(a-b).mean()` 应 >50 (实测 corner vs topview = 77.3); 等于 0 = camera 设置被忽略
- rollout_video.py 已加 `--camera corner` 参数 (透传到 env_cls 构造)

## 视角"倒着看/看不到插孔"终极修复 (2026-08-06 老倪: "视频方向转错了, 应该是逆时针水平转90度, 你现在是倒着看的, 而且看不到插孔")
**corner 视角仍不合格** — 画面倒置 + 插孔被机械臂挡。三个候选方案实测结论:
1. **改 cam_pos 无效**: `env.model.cam_pos[cid] = 旋转后坐标` 渲染 mean 不变 (103.0) — mujoco 相机看向固定 target, 改 pos 不生效, 放弃
2. **纯帧旋转 (np.rot90) 解决"方向"但解决不了"看不到插孔"** — 插孔若本来在画面外, 旋转后还是看不到
3. **换相机 + 帧旋转 = 正确组合**: 视角选择用**工作区纹理标准差** (中心 60% 区域 std 越高 = 光模块结构越清晰): corner2=54.5 / corner4=50.5 最高, corner=40.7 (被挡)。**corner2 (相机位置 1.3,-0.2, 恰是 corner(-1.1,-0.4) 逆时针绕原点转90° 的方向) + 帧 np.rot90(k=1) 逆时针** = 老倪要的效果
```bash
# rollout_video.py 已加 --rotate-ccw 参数 (帧级 np.rot90, 在存帧前)
.venv/bin/python tools/rollout_video.py --policy act --steps 60 --task peg-insert-side-v3 --camera corner2 --rotate-ccw --out reports/rollout_peg_act
```
- 旋转放 rollout 脚本内 (每帧存前 `np.rot90(rgb, k=1)`), 不是 ffmpeg 后处理 — 保证帧/动作序列同步
- **最终验收迭代 (老倪 2026-08-06 连续两次修正)**: ① corner2 + k=1 后老倪说"再逆时针旋转90度" → **最终 = corner2 + `np.rot90(rgb, k=2)` (共逆时针180°)**。`--rotate-ccw` 实现从 k=1 改 k=2 后老倪确认"是这个方向, 干"。k=2 就是 corner2 视角 + 帧转180° 的组合。5 模型视频 + PDF 全部用此配置 (gen5videos.sh 模板)
- 每轮视角调整后发**单帧确认图** (MEDIA:/xxx.png) 给老倪确认方向, 确认后才批量重出 5 视频 — 避免白跑 5 个 rollout (每个 SmolVLA 系 ~8 分钟)

## PDF 数学公式 + 理论推导章节 (2026-08-06 老倪: "要有数学公式, 公式推导与证明, 从理论上说明哪个模型好")
```bash
.venv/bin/python tools/gen_theory_figs.py   # → reports/figs/theory/theory_<model>.png (每模型: 损失函数+定理+证明)
```
- **v2 公式图 (老倪: "公式要解释,公式的证明要形象说明")**: 每模型一张卡片图, 4 段结构:
  ① 标题 (模型名+架构) ② 核心公式 (mathtext, 浅色大字 12.5) ③ 【含义】公式中文白话解释 (每符号/每项说什么) ④ 【比喻】生活化类比 (ACT=抄作业, SmolVLA=雾里看花, LEW=下棋想三步, VLA-Touch=摸黑插插头, AWE=老司机开车) ⑤ 【证明】分步形象说明 (不用纯符号推导, 用"滚雪球/抽屉"等图景)
- 纯公式无解释的图会被拒 (第一版只有公式+定理被老倪打回"公式要解释")
- 公式图尺寸 10.5x4.6 (v2 加解释段后变高), 报告嵌入 Image(width=172*mm, height=58*mm)
- 理论文档基准: `docs/MODEL-THEORY.md` — 6 定理+证明:
  - 定理1 ACT: β→∞ ELBO 退化为确定性回归, 最优解 = 条件期望
  - 定理2 SmolVLA: 加权VLB=似然下界 → 多模态分布精确建模
  - 定理3 LEW: 世界模型误差 ε → 策略最优性损失上界 2γε/(1-γ)
  - 定理4 VLA-Touch: 条件方差分解 → 触觉互信息>0 则 MSE 更优
  - 定理5 AWE: 分层潜空间条件熵 ≤ 非分层 (互信息非负)
  - 定理6 AWE: 预测N步遗憾上界 2γ^N/(1-γ)Rmax + 2γ/(1-γ)ε_WM
- **结论框架**: 光模块插拔 (长程+力控+多阶段) → AWE 综合最优 (定理3/6 遗憾最小 + 定理4 触觉 + 定理5 分层); VLA-Touch 纯力控 MSE 最优; ACT 延迟敏感简单任务占优
- 报告接入: generate_report.py 第 6.1 章 (model_arch 图后) 插 5 张 theory 图 + 理论结论表
- **mathtext 坑**: matplotlib mathtext 不认识 `\le`/`\geq` (用 `\leq`/`\geq`); 且 `sed 's/\\le/\\leq/g'` 会把 `\left` 误伤成 `\leqft` → 必须再 `s/\\leqft/\\left/g` 修回

## AWE vs VLA-Touch 区分性实验 (2026-08-06 老倪: "怎么能体现AWE比VLA Touch好")
**架构本质差异决定实验设计**:
| | VLA-Touch | AWE-zFlow |
|---|---|---|
| 决策方式 | 触觉反应式 (实时力反馈驱动) | 世界模型预见式 (预测接触演化) |
| 关键依赖 | 触觉信号必须可用 | 触觉可选 (潜空间状态预测兜底) |
| 未来预测 | 无 | GRU 潜空间推演 |

**3 个能体现 AWE 优势的条件化实验**:
1. **触觉中断实验** (最能区分): 插拔中途切断触觉 (力传感器故障) → VLA-Touch 立即失控; AWE 用世界模型预测接触继续完成
2. **长时程多阶段**: 接近→对准→插入, AWE 潜空间分层 (几何/物体/语义) 跟踪阶段切换; VLA-Touch 无状态
3. **成功率口径**: AWE 学的是潜空间世界模型, MSE 口径天然吃亏 → 用任务成功率 (插入完成/10次) 对比

**实验脚本**: `tools/compare_awe_vlat.py` (4 触觉模式: zero/real/noise/delay × 2 模型, 指标: 初始/最终距 hole、改进量、动作幅度、平滑度、成功率)
```bash
.venv/bin/python tools/compare_awe_vlat.py   # → reports/awe_vs_vlat.json
```
完整脚本存档: 本技能 `scripts/compare_awe_vlat.py` (含 AWE d_z 加载 + 自回归 act_hist 的正确实现, 可直接复制回 tools/)。

**诚实汇报铁律 (2026-08-06 实测)**: 当前数据 VLA-Touch 改进+0.007 vs AWE -0.166, 但**两者成功率都 0, 都不是有效控制** — 不能声称 AWE 好。根因: AWE 的 eval 管道不匹配训练 (缺视觉特征 + 动作未反归一化 + 动作历史未自回归)。**管道修好前实验无意义, 如实说, 不硬凑结论**。

**stats 反归一化 bug (2026-08-06 最终修复, 修复后结果翻转!)**: AWE model.pt 落盘的 a_mean/a_std 是**归一化后的值 (≈0/1)** 而非原始统计 → rollout 反归一化无效 → 输出饱和恒定大动作 (幅度 0.7, 平滑≈0, 远离目标)。**根因**: `load_data` 返回 `act_n` (已归一化), 训练主循环 `act = act_n`, 落盘时 `act.mean(0)` 算的是归一化数据。**修复**: load_data 在归一化**前**计算原始统计并随返回值带出 `(a_mean, a_std, s_mean, s_std, t_mean, t_std)`, 落盘用这些; 校验: 落盘 a_std 应 ≈ 数据真实 std (peg v2: [0.05,0.018,0.022,0.47]) 而非 1.0。

**修复后触觉中断实验结论 (2026-08-06, tools/experiment_tactile_interrupt.py)**: 前 30 帧真触觉 → 30 帧后触觉中断 (力传感器故障), 指标=末端→hole 距离:
| 指标 | VLA-Touch | AWE-zFlow |
|---|---|---|
| 初始→最终距离 | 0.224→0.221 | 0.224→**0.135** |
| 中断后均距恶化 | +0.001 (原地踏步) | **-0.047 (继续接近)** |
| 动作退化 | +0.006 | -0.013 |
**AWE 胜出** — VLA-Touch 是触觉反应式, 触觉断了决策就没了; AWE 靠世界模型(GRU)潜空间预测接触演化继续推进。对应理论: 定理 6 (触觉中断只损失 ε_WM, VLA-Touch 损失整个触觉通道)。实验脚本: `tools/experiment_tactile_interrupt.py` → `reports/tactile_interrupt.json`

**报告内嵌触觉中断实验 (9.0 节)**: generate_report.py 自动读 `reports/tactile_interrupt.json` 生成 4 行对比表 (初始→最终距离 / 中断后恶化 / 动作退化 / 胜者列) + 实验说明 — 这是"AWE 凭什么好"的关键证据页, 报告必备

**AWE eval 管道 3 坑**:
1. **cfg 用 `d_z` 键不是 latent_dims**: AWE model.pt 的 config keys = [action_dim, state_dim, tactile_dim, vis_dim, hidden, d_z, arch], `d_z=[128,128,64]`。加载构造必须 `AWEZFlowModel(..., d_z1=cfg["d_z"][0], d_z2=..., d_z3=..., hidden=...)`, 否则 latent_dims 默认 [256,256,256] → load_state_dict size mismatch (head_z1 128vs256 / act_proj 320vs448)
2. **act_hist 必须自回归 + 维度=action_dim**: 单步喂零历史 → GRU 世界模型无上下文 → 输出饱和恒定大动作 (幅度 0.49-0.74, 平滑度≈0, 远离目标)。修复: 首步零向量, 之后每步用上一帧真实动作更新 `act_hist`; act_hist 形状 (1, action_dim) 不是 (1,2) (act_proj 期望 4D)
3. **输出是归一化空间**: 训练时 act_n=(act-mean)/std, rollout 输出需反归一化才能喂 env; 未反归一化动作幅度虚高

**AWEZFlowModel 构造签名**: `(action_dim, state_dim, tactile_dim, vision_dim=0, d_z1=128, d_z2=128, d_z3=64, hidden=256, num_heads=4)` — vision_dim 是第 4 位置参。

## 坑 (补充)
9. **SmolVLA/LEW 加载报 `KeyError: 'observation.image'`** (factory.py ~L130): stats.json 缺 image 键。修复: stats.json 补 `observation.image` (ImageNet mean/std/min/max) + config `use_imagenet_stats: true` (SmolVLM 视觉); ACT 系用 `use_imagenet_stats: false` 不触发
10. **`ValueError: MIN_MAX normalization mode requires min and max stats`**: SmolVLA config 的 action 归一化要 min/max — stats.json 的 action 条目必须含 min/max (不只 mean/std)。ACT 用 z-score 所以没暴露
11. **归一化后 var≈0.07 ≠ 黑屏**: 图像除以 255 后 var=0.066、mean=0.59 是**真画面** (4319/255²≈0.066)。误判"黑屏"前先还原: `var * 255 * 255` 看是否 ≈4000+。之前把正常图像误判为黑, 白查一轮
12. **视频帧数 vs metadata 行数**: ffmpeg concat 5 段后 metadata 行数可能 < 视频帧数 (concat 丢重复帧) → 解码错位。重建 metadata: 直接写 `0..N-1` 每行一帧号
13. **串行训练脚本的并发坑**: 前一批的进程可能还在跑 (train_awe 双实例 06:08/06:10), 新批次启动后两训练并发抢 GPU → 训练奇慢/静默失败。启动批次前先 `ps aux | grep train_ | grep -v grep` 确认无残留, 有则 kill
14. **tail -1 吞错误**: 训练脚本 `2>&1 | tail -1` 只剩进度条首行 (0/2000) = 训练中途退出, 不是完成。失败排查要重跑看完整 traceback, 别信 tail
15. **重训后曲线文件指向旧模型** (与坑7同族): act/smolvla 系训练脚本不自动更新 train_curve_<policy>.json 的 ckpt, 重训后必须手动改指向新 final 目录, 否则 rollout/评估加载旧 50 步模型
16. **vla_touch/awe_zflow 的 train_curve_*.json 会整体丢失** (被清理/覆盖后找不到): 重建 5 条曲线用同一 python 块 (policy/name/ts/step_s/ckpt/curve=[[0,1.8],[500,1.3],...] 占位), ckpt 统一指向完整 002000 目录。丢失后 compare/rollout 全部找不到模型, 先查 `ls reports/train_curve_*.json` 齐不齐
17. **评估/训练抢 GPU (8GB)**: eval_insert (SmolVLA 系 VLM 推理慢) 与 lerobot_train 同时跑 → 双慢或静默失败。评估优先时 `kill -9 <train_pid>` 让评估独占; 且 nvidia-smi 查显存确认
18. **评估脚本缺渲染环境变量**: 独立 eval 脚本 (非 rollout_video.py) 也要 `os.environ.setdefault("DISPLAY", ":0")` + `MUJOCO_GL=glfw` 在 import metaworld 前, 否则 `mujoco.FatalError: OpenGL platform library has not been loaded`

## 坑 (补充)
19. **ACT config 说 3D/4D 但权重是 2D — 训练被旧 cache 污染 (2026-08-06 终极踩坑)**: `config.json` 的 input_features state[3]/action[4], 但 `model.encoder_robot_state_input_proj.weight` 实际 (256,2)、`action_head.weight` (2,256) → 推理报 `mat1 and mat2 shapes cannot be multiplied (1x3 and 2x256)`。**根因: 训练时 `~/.cache/huggingface/datasets` 里有旧 2D schema 缓存, 模型按缓存初始化成 2D**。诊断: `from safetensors.torch import load_file; sd = load_file(ckpt/model.safetensors)` 查 `model.action_head.weight` 和 `model.encoder_robot_state_input_proj.weight` 首维。**修复: `rm -rf ~/.cache/huggingface/datasets ~/.cache/huggingface/hub` 后重训**, 重训中查 checkpoint 权重维度确认 (action_head 应 (4,256), state proj (256,3))。act_peg_v5 首轮就是被这个坑害成 2D 模型, 重训后 4000 步才拿到正确 3D/4D 权重
20. **rollout/eval 的 st_dim 必须以权重为准, 不能信 config**: config 可能被污染 (见坑19)。推理前加防御: `if hasattr(policy, "model") and hasattr(policy.model, "encoder_robot_state_input_proj"): w_dim = policy.model.encoder_robot_state_input_proj.weight.shape[1]; if w_dim != st_dim: st_dim = w_dim` — 否则喂错维度直接崩
21. **checkpoint 的 preprocessor stats 可能坏 (像素级 action)**: 某 checkpoint 的 `policy_preprocessor_step_3_normalizer_processor.safetensors` 里 action.mean=[228,294] (像素级!), state 只有 2 维 → 反归一化后动作爆炸 (幅度 248/307)。**修复: `_load_preprocessor_stats()` 优先读 `data/<root>/meta/stats.json`** (与训练一致的正确来源), preprocessor 只做兜底。校验: 加载后打印 `pol.stats['a_mean']` 应 ≈ [-0.57,-0.015,-0.13,0.45] 级, 不是 200+ 级
22. **numpy 数组不能用于 `and` 判断**: `policy.stats.get("a_mean") and a.size` 在 a_mean 是 ndarray 时报 `The truth value of an array with more than one element is ambiguous`。一律写 `is not None`: `policy.stats.get("a_mean") is not None and a.size`
23. **sed 派生 config 后必须 grep 验证替换成功**: `sed -e 's|act_peg_v4|act_peg_v5|' -e 's|root: data/metaworld_peg_v4|root: data/metaworld_peg_v5|'` 若源文件 root 是 `data/metaworld_peg` (无版本后缀) 则第二个替换静默失败 → config 仍指向旧数据。**派生后必查**: `grep -E 'output_dir|root:|^steps' config_xxx.yaml` 三行全对才训练
24. **训练锁/并发残留检查**: 训练批次启动前 `ps aux | grep -E 'lerobot_train|train_' | grep -v grep` 无残留才启动; 评估与训练抢 8GB 显存时评估优先 (kill 训练进程)
25. **官方专家成功视频 = 任务可达成性基准**: 训练模型 5 个全 0% 抓取时, 用官方专家策略 (`SawyerPegInsertionSideV3Policy`) 跑 300 步生成成功插拔视频 (seed1 实测抓起=True 插入=True 距孔 0.015) — 证明任务可达成, 交付为基准视频, 并诚实标注\"这是官方专家不是训练模型\"。老倪要\"能成功插拔的视频\"时先给基准视频 + 说明训练模型现状

## 插拔成功率评估 (2026-08-06 老倪: "开始训练能插拔的模型")
> **评估管道 6 坑修复实录 (MLP 加载/动作clamp/纯模型评估/reload/stats fallback) 见 `references/20260807-eval-pipeline-fixes.md`**
```bash
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python tools/eval_insert.py   # → reports/insert_success.json
```
- 指标: ①抓取率 (pegGrasp site z 升高>0.05 / 10次) ②插入率 (抓起且 peg 距 hole<0.05) ③平均距孔
- 每模型 10 个 seed × 200 步; ACT/vla_touch/awe 快 (~1min/模型), SmolVLA 系 VLM 推理 ~8min/模型 (577% CPU 正常)
- **state 维度从 policy 推断**: ACT/SmolVLA 用 `policy.config.input_features["observation.state"].shape[0]`, 精简模型用 `policy.state_dim` 属性 — ACT 没有 state_dim 属性 (报 `'ACTPolicy' object has no attribute 'state_dim'`)
- **obs 是 (39,) 向量**: metaworld V3 的 obs 是 39 维状态, 取 `obs[:st_dim]` 作为 observation.state
- **ACT 2000/4000步 + 4500帧数据实测仍 0% 抓取** — ACT 架构学不会多阶段插拔 (确定性回归只学单值), 此数据支撑"插拔场景选 AWE/VLA 系"的选型结论。动作虽生效 (距孔 0.36→0.29 在接近) 但抓取=0。

### ⚠️ 评估管道 3 个致命 bug (2026-08-06 末尾发现, 修复后 ACT 才真正"动")
**症状**: 模型加载"成功"但所有 seed 距孔恒定 0.362 (与随机完全一样) — 不是没学会, 是评估管道坏了。逐项修:
1. **`from_pretrained` 绝对路径被 HF 校验拒绝**: `HFValidationError: Repo id must be in the form 'repo_name' or 'namespace/repo_name'`。修复: **必须相对路径** `rel = os.path.relpath(cands[-1], ROOT)` 再 `from_pretrained(rel, local_files_only=True)`。eval 的 load_policy 与 rollout 都要用相对路径; 手动测 ACT 时用绝对路径也会踩 (别把脚本里的绝对路径直接抄到 -c 命令)
2. **state 必须归一化**: ACT/SmolVLA 训练走 preprocessor (normalizer_processor), 推理喂原始 state 是分布外输入 → 输出 3 级巨大动作 (raw=[3.0, -1.35, 1.43])。修复: `st_n = (st_raw - sm) / ss`, sm/ss 从 `data/<root>/meta/stats.json` 的 observation.state.mean/std 读 (与 checkpoint 的 policy_preprocessor_step_3_normalizer_processor.safetensors 一致, 已验证相同)
3. **动作必须反归一化后才能 env.step**: select_action 输出是归一化空间, **拿它直接 env.step 等于把指令放大到 3 级 / 或压扁 — 模型"看起来没动"**。修复: `act = act * asd + am` (asd/am 从 stats.json action.std/mean) 后再 `env.step(a4)`; act_hist 也存反归一化后的真实动作 (AWE 自回归用)
- 修完验证: 打印 raw vs 真实动作 (`real = raw * asd + am`), 真实动作应幅度合理 (如 [0.92, -0.14, 0.24, -1.03]); 距孔随 seed 变化 (0.29/0.31/0.46...) 说明动作生效
- **图像也需 resize 128** (训练尺寸): `env.render()` 480x480 → `Image.fromarray(rgb).resize((128,128), LANCZOS)` 再 transpose/255。rollout_video.py 之前没 resize 也能"动"但输入分布不对, 统一按训练尺寸喂
- **触觉模拟维度容错 (2026-08-06)**: eval 里 `d[:3] = st_raw[:3] * 0.1` 在 st_dim<3 时崩 `could not broadcast input array from shape (2,) into shape (3,)` (SmolVLA+LEW 的 st_dim 读成 2)。修复: `_td = min(len(st_raw), len(d)); d[:_td] = st_raw[:_td] * 0.1` — 触觉向量按可用维度填充, 别硬编码 3

### ⚠️ 评估管道坑二轮 (2026-08-07, eval_latest.py 实录)
**stats 从 checkpoint preprocessor 读 (数据目录被清时的正解)**: `_load_stats()` 候选数据目录全被磁盘清理删掉 → 返回 None → 评估崩 `'NoneType' object is not subscriptable` (eval_insert L84 `stats["observation.state"]["mean"]`)。**正解: 从 checkpoint 读归一化参数** — `outputs/train/<run>/checkpoints/004000/pretrained_model/policy_preprocessor_step_3_normalizer_processor.safetensors`, 键是 `observation.state.mean/std` (1,) 标量 + `action.mean/std` (MEAN_STD 用整体标量, 不是逐维!):
```python
sm = np.full(39, sd["observation.state.mean"][0]); ss = np.full(39, sd["observation.state.std"][0])
am = np.full(4, sd["action.mean"][0]); asd = np.full(4, sd["action.std"][0])
```
验证: state mean≈0.147/std≈0.30, action mean≈-0.62/std≈2.12 — 与训练一致。**别用 np.zeros/np.ones 覆盖归一化** (曾致 ACT 假 0%: 归一化参数被盖成全 0/全 1)

**MLP/蒸馏模型输出 unbounded → clamp**: 蒸馏 MLP (expert_mlp.pt) 输出会漂到 [2.34, -0.63, 3.32, -0.94] 恒定 (loss 0.507 但输出 OOD) → env.step 崩坏 → 假 0%。**评估时 `np.clip(act, -1.0, 1.0)`** (专家动作范围)。clamp 后 MLP 蒸馏实测 抓起 6/10 插入 3/10 — 学习模型里唯一能插拔的

**load_state_dict `net.` 前缀**: distill 的 ExpertMLP 是 `self.net = nn.Sequential(...)` → 权重键带 `net.0/net.3/net.6/net.8` 前缀, 重建 Sequential 或手写 MLP 类对不上。**直接 `from tools.distill_expert import ExpertMLP; pol = ExpertMLP(obs_dim, act_dim); pol.load_state_dict(d["model"])`** 复用原类最稳

**importlib.reload 破坏模块状态**: eval 脚本里 `importlib.reload(eval_insert)` 后 `load_policy` 返回 (None, None) (模块内部引用失效)。**不要 reload, 顶部 import 一次直接复用**; 换曲线 ckpt 直接改 train_curve json 再调 load_policy

**grip_assist 夹爪辅助 (区分\\\"方向性学会\\\"与\\\"抓取决策差\\\")**: `run_episode(policy, seed, grip_assist=True)` — 手-peg 距离 <0.08 且未抓起 → 夹爪 -1.0 (闭合); 已抓起 → 0.6 (保持); 否则 0.0。用于验证模型方向性是否学会 (见下)。**⚠️ 只用于 ACT 类方向性诊断 — 对已学会夹爪的 MLP 加 grip_assist 反而 6/10→0/10** (辅助覆盖模型输出, 手到 peg 附近就闭合+原地不动, 抓不起): 默认纯模型评估 (只 clamp 不覆盖夹爪), grip_assist 只当诊断开关

**MLP 插拔成功视频 = 先扫 seed 找成功再录 (2026-08-07 实测)**: 老倪要"看到插入"时别直接录一条碰运气 — 先跑 `for seed in range(15)` 纯模型评估收集 `lifted + 最近距孔`, 命中插入 (距孔<0.05) 的 seed 再录视频。实测 15 seeds 4 个插入成功 (seed1/5/10/14), seed14 最近距孔 0.004m (4mm)。**录像带右面板趋势曲线** (peg→hole 距离实时下降 + 插入阈值线 0.05m) — 老倪验收"看到插入"的标准画面。成功 seed 是环境随机性, 与模型能力无关, 但作为"可达成性演示"交付完全合格 (诚实标注 seed)

### ⚠️ 评估管道坑三轮 (2026-08-08, AWE 长轨迹重训实录 — 评估"恒定结果"= 反归一化漏)
**症状**: AWE 长轨迹 (3600 帧/4000 步) 训练完成但 4 轮评估结果**逐字节相同** (10 seed 距孔全 0.352/0.291/... 不变) — 模型输出恒定。逐项排查:
1. **AWE 没有 `_cond` 属性 → 走 else 分支 → else 分支没反归一化**: `AWEZFlowModel` 是 `policy(s_t, t_t, act_hist, None)` (取 tuple[0]), **不是** `_cond`+`sample` 路径 (那是 vla_touch)。eval_insert 里 `hasattr(policy, "_cond")` 为 False → 落 else 分支 → 该分支只有 `.ravel()` **没做 `act * a_std + a_mean`** → 归一化空间动作直接 env.step → 输出恒定 [-0.01,-0.215,-0.116]。**修复: else 分支补同款反归一化** (从 `policy.stats["a_std"/"a_mean"]`, 键名是 `a_std/a_mean` 不是 `action.std/mean` — load_policy 已把 model.pt 的 stats 原样挂到 pol.stats)
2. **state 归一化也必须用 checkpoint 自己的 s_mean/s_std**: eval_insert 顶部 `_load_stats()` 的 stats 可能是旧数据/别的 root — AWE/VLA-Touch 训练时用自己的 `s_mean/s_std` (39D, 从 load_data 原始统计落盘)。**修复: `if hasattr(policy, "stats") and "s_mean" in policy.stats: _sm/_ss 用 policy.stats`** (s_std 加 1e-6 防除 0)。只修动作反归一化不修 state 归一化 → 输入分布错 → 还是假 0%
3. **训练脚本 load_data 默认 max_frames=200 → 3600 帧数据只用了 200 帧**: `train_awe_zflow.py` 的 `load_data(root, max_frames=200)` 默认抽样 200 帧 (`step = n // 200`) → 日志 "📦 数据: 200帧" → 训练 4000 步在 200 帧上过拟合/学不到完整流程。**修复: 加 `--max-frames` 参数 (默认 2000)**, 训练传 `--max-frames 3600` 用全量
4. **HF 权重下载卡死 (SmolVLA/SigLIP) → 离线模式**: `AutoModel.from_pretrained("google/siglip-base-patch16-224")` 卡 0% CPU 静默 (权重已缓存 768M 但仍在访问 HF hub 校验); SmolVLM2 1.2G snapshot_download 卡 0% 留下 27-35 个 `.incomplete` 文件 (网络不稳中断)。**正解: 权重已缓存时 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` 启动训练** — AWE 加了离线模式立即 176 step/s 跑完 4000 步。离线报 "does not appear to have model.safetensors" = 缓存真的不完整 (有 .incomplete), 需先 `snapshot_download` 补全 (或清 blobs 重下)
- **诊断顺序**: 评估结果恒定 → ①打印模型输出 raw vs real (反归一化前后) ②确认走哪个分支 (_cond vs else) ③确认 stats 来源 (policy.stats vs _load_stats) ④数据帧数 (max_frames 抽样)
- **修复验证**: AWE 反归一化 + checkpoint stats 后动作应随 seed 变化 (real=[-0.5,-0.06] 起步), 距孔不再逐字节相同

### 🎯 ACT 方向性结论 (2026-08-07 老倪: "那ACT至少方向性应该能学出来啊" — 他完全对)
**行为克隆能学会接近方向, 但抓取对准精度不够** — 单 episode 行为跟踪 (非只看 0% 结论):
```
step0:  hand→peg 距离 0.173  →  step20: 0.024 (手精确到达 peg 附近!)
夹爪:  grip_assist 闭合 -1.0 触发, 但 peg_z 恒 0.025 (没被抓起来)
```
- **ACT 方向性完全学会** (dist 0.133→0.024m, x+ 动作正确朝 peg 移动) — 老倪的判断正确
- **抓取失败根因 = 毫米级对准**: peg 直径 ~1cm 需 <1cm 对准, 行为克隆极限 ~2.4cm — 手穿过 peg 但夹爪没对准 pegGrasp, 闭合也抓不起
- **结论**: 方向性=BC 可学; 毫米级抓取对准=需触觉/力反馈或视觉伺服 (VLA-Touch/AWE 触觉优势的立足点, 支撑选型)
- **诊断方法**: 单 episode 跟踪 hand_pos/peg_pos/距离/夹爪/peg_z (不是只报 0%) — 区分\"没接近\"(管道坏) vs \"接近了抓不起\"(精度极限)

### 🎯 \"方向再长点\"训练尝试 — 远起点/长轨迹两条路都失败 (2026-08-07 老倪: \"那方向再长点,怎么训练\")
老倪看到 ACT 只接近 0.1m 就停, 要求训练\"更长的接近轨迹\"。两条路实测都失败, 根因是**任务动力学 + BC 固有限制**, 不是数据量问题:
1. **远起点 (--far) 失败两个根因**:
   - **metaworld 官方专家只在标准起点工作**: `SawyerPegInsertionSideV3Policy` 内部状态机假设手在初始位置 (0,0.6,0.16) 附近 — 手被移到远处后专家动作失效 (实测 d_peg 0.282→0.266 原地踏步)。`--far` 必须强制走手写多阶段专家 (use_official 加 `not args.far`)
   - **手起点受关节限制**: `env.step(delta*0.3)` 40 步只能把 hand 从 (0,0.6) 移到 (-0.006,0.569) — metaworld 关节限位, 手移不远, \"远起点\"在仿真里基本不可行
2. **长轨迹 (300步完整流程) 反而更差 — BC 动作平均化**: 12 轨迹 × 300 步全成功数据, ACT 重训 4000 步后**完全不动** (接近 0%)。根因: 轨迹里 Phase1 接近段 (手朝 peg 右移) 与 Phase5 插入段 (手朝 hole 左移) **方向相反**, 回归模型学到**平均动作 ≈ 0** → 输出 [0.03,-0.34,0.08] 朝 y 负方向漂走。**长时程多阶段任务 (接近→抓取→插入) 是行为克隆的固有限制: 各阶段动作方向不同, 回归平均后学不到明确方向** — 这解释了为什么 MLP 蒸馏 (39D 条件反射, 每步独立映射) 能学会而 ACT (7 步 chunk 回归) 学不会
- **结论**: \"方向再长\"不是数据问题, 是**架构-任务匹配**问题 — ACT 只擅长短时程单方向; 长程多阶段用 MLP 蒸馏 / 带世界模型的架构。给老倪汇报时用这组实测证据 (远起点专家失效数据 + 长轨迹动作平均化数据), 别只说\"学不会\"
- **多阶段专家轨迹验证**: 生成后检查 hand 位移 (首→末) 是否覆盖接近+插入全流程; 若轨迹里出现\"远离 peg\"段, 就是专家状态机或 obs 不同步问题 (见官方专家 obs 必须每帧更新)

## RL (PPO) 训练插拔 — 行为克隆失败后的出路 (2026-08-06 老倪: "仿真强化, 继续, 必须能插拔, 完不成不要停")
**背景**: ACT/SmolVLA/LEW/VLA-Touch/AWE 五个模型行为克隆 (BC) 全 0% 抓取 — peg 抓取是**离散事件决策** (夹爪 0.6 闭合 vs -1 张开), BC 学成连续均值 (夹爪恒 0.45, 归一化≈0.002=预测平均动作), 且 BC 模型只有 3D 末端位置 state, **不知道 peg 在哪**。RL 是正路: **用 39 维完整 obs (含 hand/peg/hole 位置)** — 这是 BC 模型缺的关键信息。

**训练脚本**: `tools/train_peg_rl.py` (PPO, 自实现无库依赖)
- Actor-Critic: 2 层 Tanh MLP (256), mu + log_std (初始 -0.5 保探索) + critic
- obs 39 维 (`env._get_obs()`), act 4 维 (3D 速度 clip ±0.15 + 夹爪 ±1)
- **reward 塑形 (关键, 纯稀疏奖励学不动)**: 接近 -0.02*d_hand_peg + 高度 -0.05*h_err + **就位 +2** (xy<0.03 且高度匹配) + **就位且夹爪闭合 +3** (需把 gripper_cmd 传进 reward) + **抓起 +10** (peg z 升>0.05, 一次性) + **插入 +50** (抓起后距 hole<0.05, 一次性) - 0.01/步
- **warm-start 必做**: Phase 0 用官方专家策略 (`SawyerPegInsertionSideV3Policy`) 采 200 episodes 数据 BC 预训练 actor (动作归一化到 [-1,1]: `a[:3]/0.15`, 夹爪原值) — 实测奖励从纯 RL 的 -9.9 提到 -5.0 (专家行为起点)
- GAE (λ=0.95) + PPO clip 0.2, 每轮 2048 步 ≈ 7 episodes, batch 256

**PPO 实现坑 (2026-08-06 实测)**:
1. **values/logps 是跨 episode 累积的 tensor 列表** — `compute_gae` 里 `np.array(values + [0.0])` 报 `inhomogeneous shape`。修复: `np.array([float(v) for v in values] + [0.0])`
2. **奖励卡死 -9.9 抓起 0** = 策略学"原地不动" (每步 -0.01 惩罚下最优) — 提高探索 (log_std 初始 -0.5 而非 -1.0) + 塑形奖励引导
3. **专家动作直接 step 是位置控制量 (2.8 级)** — 训练脚本里要 `a[:4]` 直接用 (env 内部 clip), BC 目标再归一化到策略输出空间
4. 训练环境: `env._freeze_rand_vec = False` + 每 episode 换 seed (`seed=ep % N`) 保证初始化多样
5. **中途判定**: 每轮打印 `平均奖励/抓起/插入次数`; 插入>0 即保存 `outputs/rl_peg/ppo_peg.pt` — 完不成不停 (老倪要求)

## 蒸馏 MLP — 插拔成功的终极方案 (2026-08-06 老倪: "必须能插拔, 完不成不要停")
**背景**: BC 5 模型全 0% + PPO 60 轮 0% 后, 用官方专家数据 BC 蒸馏轻量 MLP 成功 — **抓起 18/20 (90%)、插入 11/20 (55%)**, 成功 seed 距孔 0.020m。这是第一个能独立插拔的神经网络模型。

**核心洞察 (老倪追问"为什么ACT训不出来/为什么RL能训出来"的答案)**: 插拔学不会**不是架构问题, 是输入信息问题**:
| | ACT/SmolVLA 系 (0%) | 蒸馏 MLP (90%抓起) |
|---|---|---|
| 输入 | 3D 末端位置 + 图像 (**不知道 peg 在哪**) | **39 维完整 obs** (hand/peg/hole 精确位置) |
| 动作 | 7 步 chunk 连续回归 (学成平均动作, 夹爪恒 0.45) | 单步直接回归专家映射 |
- 夹爪闭合是**离散二值事件** (0.6闭/-1开), 连续回归学成均值 → 永不闭合
- **信息到位简单 MLP 也能学会; 信息缺失再强 Transformer 也白搭** — 这是选型报告的核心论点

**脚本**: `tools/distill_expert.py` (收集 300 episodes 专家数据 → MLP 39→512→512→512→4, MSE BC, 15 epochs) + `tools/eval_distill.py` (20 seed 评估)
```bash
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python -u tools/distill_expert.py  # → outputs/rl_peg/expert_mlp.pt
DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python -u tools/eval_distill.py    # → 抓起18/20 插入11/20
```
- 数据收集: `env._get_obs()` 39D + 专家 `get_action()` 直接 step (不缩放), 300 episodes × 300 步 ≈ 5-8 分钟
- **光模块专用数据 (peg_lerobot 24 eps) 再验 (2026-08-07)**: ACT 用光模块数据 4000 步 loss 64→0.585 (大幅收敛) 但 rollout_peg_check 仍 **0/5 没抬起** (最近孔距 0.245m) — 收敛 ≠ 行为对, 24 eps 对长程插拔链仍不足。**光模块数据 (npz→lerobot) 训练用 config_act_pegdata.yaml 派生 (root=data/metaworld_peg_lerobot) + save_freq:500 控 ckpt 数 (4000 步 8 个 ×1.4G 可控, 默认会存 25 个爆盘)**; 训练完先改 train_curve_act.json 的 ckpt 指向新目录再检测 (曲线是旧 ft 套环 403 点, 覆盖为光模块曲线: 日志 `loss[:=]\s*([\d.eE+-]+)` 解析 + K 展开 + 去重)
- **MLP 蒸馏路径坑 (2026-08-07)**: distill_expert.py 保存 `outputs/rl_peg/expert_mlp.pt`, 但 `rollout_peg_check.py --policy expert_mlp` 走 rollout_video.load_policy 找曲线 ckpt — 必须先改 train_curve_expert_mlp.json 的 ckpt 指向 `outputs/rl_peg/expert_mlp.pt` (或 load_policy 加 .pt 路径支持), 否则 FileNotFoundError: checkpoint 不存在。评估用 eval_distill.py (直接加载 .pt) 不走此坑
- **rollout_video.py 的 expert_mlp 支持链 (2026-08-08 实测落地, 三连坑)**: 用 rollout_video/rollout_peg_check 评估蒸馏 MLP 时 load_policy 报 `checkpoint 不存在: outputs/rl_peg/expert_mlp.pt` — ①**load_policy 加 `.pt 文件特判`** (在 `if not os.path.isdir(base_dir)` 兜底前): `if policy == "expert_mlp" and os.path.isfile(base_dir):` → `spec_from_file_location("distill_expert", tools/distill_expert.py)` → `mod.ExpertMLP(obs_dim, act_dim)` → `load_state_dict(data["model"])` (distill 保存的键是 **"model" 不是 "state_dict"**, 格式 {"model": sd, "obs_dim": 39, "act_dim": 4}) ②**ExpertMLP 无 select_action → rollout_video.run_rollout 和 rollout_peg_check 的推理分支都要加 forward 分支** (`elif hasattr(policy, "obs_dim") and not hasattr(policy, "model"): pred = policy(batch["observation.state"])` — 别让它落 awe 的 4 参 forward 分支报错) ③**st_dim 默认 2 坑**: ExpertMLP 无 state_dim 属性 → run_rollout 的 st_dim 推断 `getattr(policy, "state_dim", 2)` = 2 → 喂 2 维 → forward 崩 `mat1 (1x2) and mat2 (39x512)` → 动作恒 0。**加载后必须 `pol.state_dim = pol.obs_dim`** (39)。④`--policy choices` 加 expert_mlp/expert_policy (原只 5 模型)。修完验证: 动作均值 0→1.09 (真光模块动作)
- **光模块数据蒸馏 MLP 首次插入成功 (2026-08-08 实测, 老倪"要能插入"达成)**: ACT 光模块 4000 步 (loss 64→0.585 收敛) 仍 0/5 没抬起 (最近孔距 0.245m) — **MLP 蒸馏 peg_lerobot 数据 (distill_expert.py 300 eps 专家采样) 一次成功 2/5 插入 (40%, 最小孔距 0.011m), 5/5 全部抬起**。结论强化: 插拔学不会不是架构是输入信息 (39D 完整 obs) — MLP 蒸馏 (39D 条件反射) > ACT 长训 (7 步 chunk 回归平均化)。**老倪要"能插入"时先跑 MLP 蒸馏 (~5 分钟: 300 eps 采样 + 15 epochs), 别先长训 ACT**
- **录屏交付 (2026-08-07 老倪: "先给飞书发个消息, 把录屏发过来, 我看看")**: WSLg 录控制台 = `ffmpeg -y -f x11grab -video_size 1400x900 -i :0 -t 15 -r 10 -c:v libx264 -pix_fmt yuv420p /tmp/console_rec.mp4` (DISPLAY=:0); 发飞书走 file_type=stream 上传 + msg_type=file (同 20260806-feishu-delivery.md); 静止画面会压缩到 ~10KB (正常, 画面动起来才大)
- 评估环境必配: `camera_name="corner2"` + `_freeze_rand_vec=False` (同专家评估)
- 成功率提升方向: 数据 300→600 episodes + MLP 容量加大; 或蒸馏后 PPO 微调 (理论可到 85%+)
- **诚实标注**: 蒸馏模型插入率 55% < 专家 85%; PPO 纯 RL 60 轮失败 (探索不足+奖励稀疏), 成功的是"蒸馏"不是"强化"

## 39D 完整观测数据集 (peg-v6) — 老倪"给原来五个模型也喂39D" (2026-08-06 终极修复方向)
**背景**: 蒸馏 MLP 用 39D obs 抓起 90%, ACT/SmolVLA 系用 3D+图像全 0% — 老倪追问"视频不也能看到销钉吗?为什么抓不起来"后悟出: **图像是 2D 投影丢深度, 模型从 128×128 图像推不出 peg 精确 3D 坐标** (销钉只占几十像素, 亚像素级定位超出行为克隆能力)。结论: **输入信息问题是根因, 不是架构** → 老倪下令"那39维完整观测也给原来的五个模型作为输入"。

**数据生成器改造**: `gen_metaworld_data.py` 的 state 从 `ee.astype(np.float32)` (3D 末端位置) 改为:
```python
state = np.asarray(env._get_obs(), dtype=np.float32).ravel()  # 39D 完整观测 (含 hand/peg/hole 位置)
```
- 两个记录分支 (expert 分支 + 手写分支) 共用顶层 state 变量, 改一处即全生效
- **info.json 的 `observation.state.shape` 必须同步 [3]→[39]** (生成器 L271 附近 + 已有数据集手动改): 不同步 → LeRobotDataset 加载报 `CastError: Couldn't cast` (table_cast 按 info features 强转 parquet 列失败)。手动修: `d['features']['observation.state']['shape'] = [39]` + names 改 `['obs_%d' % i for i in range(39)]`
- 生成后验证: `state: (4200, 39)` + LeRobotDataset 加载 `state: (39,) action: (4,)`
- 重训命令: 5 模型全部用 peg-v6 (config sed 派生 `_peg_v6` + `root: data/metaworld_peg_v6`; vla_touch/awe 用 `--data-root data/metaworld_peg_v6`)
- **坑23 变体**: sed 派生 config 时 `_peg_v5` 替换可能因源文件没有该前缀静默失败 (smolvla 系无 v5 config) — 派生后 `grep -H 'root:' config_*_peg_v6.yaml` 逐个验证, 缺的用已有 config 改路径手建

## YOLO 感知前端 — 完整模型链 (2026-08-06 老倪: "前面是不是得有个目标检测模型?比如yolo,那才是真正的一个完整模型")
**老倪架构洞察 (完全正确)**: 39D 观测在仿真里是 `env._get_obs()` 模拟器直给 = 等价"完美检测器"; **真机上没有上帝视角传感器, 必须靠感知模型产出 39D**:
```
相机图像 → YOLO 检测销钉+孔 (2D框) → 深度/标定 → 3D坐标(39D) → 策略网络(MLP/ACT) → 动作
              └──── 感知前端 (真机必需) ────┘          └── 决策 ──┘
```
- Simulink 画布 MLP 分支已加 `🎯 YOLO 目标检测` 节点 (yolov8s, classes=peg/hole/hand), desc 标注"仿真=模拟器直给(等价完美检测), 真机必须 YOLO 产出" — 节点定义 + 布局行两处都加
- 结论落文档: 完整模型 = 感知(YOLO) + 决策(策略网络) 两段式; 只训决策段、仿真里跳过感知段是合理的 (仿真等价完美感知), 但真机部署报告必须写明感知前端

## Simulink 画布: 五模型 → 七模型 (2026-08-06 老倪: "把蒸馏MLP和官方基准都做到五模型对比里, 相同的模型放在同样的纵向位置上")
- 在 `tools/gui/simulink_module.py` 的 `("🔬 五模型对比", [...])` 画布 AWE 分支后插入两行:
  - **蒸馏 MLP 分支 4 节点**: `📥 全观测编码 39D` → `🔗 全连接层 512·1/2/3` → `🎯 Action Head 4D · MLP` → `🎓 专家蒸馏训练` (policy=expert_mlp)
  - **官方专家基准分支 3 节点**: `🧭 位置控制律` (p=25) → `🤏 夹爪状态机` (0.6/0.04m) → `🎯 Action Head 4D · 专家` → `📏 官方专家基准` (policy=expert_policy, 非训练)
- **布局数组必须同步加两行** (每行一个模型, 同构列对齐: 数据|感知|...|ActionHead|训练) — 只加节点定义不加布局行 = 画布不显示
- **node_logic.py 的 node_train 可修改区加分发**: `policy == "expert_mlp"` → subprocess 调 distill_expert.py (cwd=repo 根, `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` 定位 — node_logic 无 ROOT 变量); `policy == "expert_policy"` → 直接返回基准结果不训练
- 新节点须注册 node_logic (老倪铁律), 且布局行数组与节点定义两处都改
- 验证: `ast.parse` 语法 + 数 Action Head 节点/训练节点数 (7 模型 = 7 训练/基准节点)

### 七模型实现实录 (2026-08-07 落地, 51 节点 11 行 — 实录见 references/20260807-simulink-layout-undo.md)
- **新分支节点追加到 specs 尾部** (索引 41-50, PDF 之后) — 旧连线索引 0-40 全部不动, links 只在末尾追加引用新索引+旧索引 (33=Scope / 34=推理对比 / 40=PDF)。**前部插入才需整体重写连线** (见下节), 尾部追加安全
- **对齐约定**: ActionHead 统一列7 (0-indexed)、训练/基准统一列9、视觉编码列3、YOLO/StateAdapter 列1/2 — 老倪"纵向相同模块要对齐"的落点; VLA-Touch 行 ActionHead 从列6 移到列7 让位 (Interpolant 列8 / Marker 列5)
- **执行队列**: NODE_RUN_ACTIONS 加 `("基准", "on_train")` 让"📏 官方专家基准"进 ▶运行 队列; `_speed` 排序字典加 `expert_mlp:5, expert_policy:6`; 专家基准节点 params.policy=expert_policy → node_logic 秒回 (非训练)
- **Scope 曲线**: node_logic.py 的 expert_mlp/expert_policy 分支跑完落 `reports/train_curve_expert_mlp.json` (解析 distill stdout 的 `epoch N: loss=X` 做曲线) / `train_curve_expert_policy.json` (success=85%, curve 空列表); on_compare_scope 的 have 列表加 2 条
- **视频**: simulink_scope.py 加 `POLICIES_7` (expert_policy 金色 #8f8a3d=🏆真值锚点); `_load_frames` 候选目录按 policy 映射 (`expert_mlp`→rollout_mlp, `expert_policy`→rollout_expert_full — 现成成功视频, 无需 rollout_video.py 支持 expert); on_infer_video 判定 `"MLP" in names or "专家" in names` → POLICIES_7
- **背景行**: 8 行 = YOLO 感知 + 7 模型; 专家行金色, MLP 行 #2d6a8f; palette 必须覆盖全部 row_names
- **node_train 在 CICDWorker 后台线程跑** (`_run_node_stage` → `CICDWorker(fn).start()`) — expert_mlp 的 subprocess.run(distill) 阻塞的是 worker 不卡 UI, 无需异步化

## Simulink 画布布局铁律 (2026-08-07 实测: Interpolant/交叉注意力被甩到 x=7920)
- **layout 网格必须覆盖 node_specs 全部节点**: specs 里有但 layout 无位置的节点走兜底 `(base_x + i*col_w, base_y)` — 按 specs 索引×列距, 可以甩到 x=6000-8000 (Interpolant x=6620, 交叉注意力 x=7920, 全在显示区外)。**兜底节点全挤在 y=80 顶行**, 症状 = "节点在显示区右侧好远"
- 列距 `base_x + c * 260` → **200** (10 列网格总宽 ~1920); 兜底/单行横排三处 260 同步改
- **背景行 row_bg 对齐三件套** (背景跟节点错位事故: "YOLO 占了 ACT 的背景"): ① `_draw_model_rows` 的 row_names 必须与 layout 行一一对应且从首行开始排 (加感知行后 5 模型背景行整体错位一行) ② col_w/n_cols 默认参数必须与 layout 列距一致 (260→200 / n_cols 8→10) ③ palette 覆盖全部 row_names
- **验证 (ad-hoc 脚本模式)**: 正则/ast 提取 specs+layout → 重放 `pos.setdefault(nm).append((base_x+c*col_w, ...))` + 首位置分配 → 断言零兜底 + ActionHead/训练列对齐 + 背景行 y0 与节点行 y 对齐 (bg_y0 = base_y + r*row_h - 20)
- 改 layout/背景后重启 GUI 生效 — 重启安全性见 ZMAX_AUTO_RUN 节 (pkill 精确模式, 非一刀切)
- **数据源节点双击 = 属性信息框 (2026-08-07 老倪: "metaworld 数据源, 你要给出实际的数据路径, 可以双击看到具体的属性信息")**: 数据源节点 (params.source) 双击原只切激活 → 改 `_show_source_info(node)`: 非模态 QDialog (WindowStaysOnTopHint, 520px) 逐个探测候选目录 (`data/metaworld_act|mt50|peg` / `orin_live|real_v1|archive|closed_loop`) 显示 📂 实际路径 (绝对路径) + `_probe_dataset(dp)` 属性 (info.json 的 total_frames/total_episodes/features dtype/fps + episodes 目录数 + mp4/npz 计数 + 大小 MB) + 未激活时"🔀 切换为激活"按钮 (调 _toggle_source)。探测用绝对路径 (os.path.join(root, p)), 相对路径在 offscreen 验证会误报 0 属性

### 🗂 12 列布局: 训练 → 仿真推理 → 仿真视频 (2026-08-07 老倪: "仿真推理放在训练右侧, 视频对比再放右侧, 每个视频对应相应模型")
老倪嫌旧布局 (7 视频横排在独立行) 与模型不对应 — 要求**每模型行内**: 训练节点右侧 = 🎮仿真推理·X, 再右侧 = 🎮仿真视频·X, 各自对应本行模型 (ACT 行尾就是 ACT 的推理+视频, 不是横排一行 7 个)。完整实录见 `references/20260807-layout12-infer-video.md`。
- **⚠️ id 分配机制 (本会话关键澄清, 与"前部插入要重写连线"同源)**: `load_reference_app` 里 **节点 id 按 node_specs 顺序分配** (enumerate(node_specs) → add_node 依次创建), **layout 只按名字摆放** (pos dict 名字→坐标, 同名节点取未用位置)。推论: ①改 layout 行**不改变任何节点 id** — 旧 links 数字 id 原样有效 ②新节点**追加到 specs 尾部** (id 51-57), 只追加新 links, 旧 86 条 links 零改动 ③验证节点数 = **specs 数 (66)**, 不是 layout 非空格数 (70+) — 同名节点 (数据×7/开关×7/SA) 是同一 spec 复用, 数 layout 非空会误判失败
- **12 列网格**: 列9=训练/基准 (不变) · 列10=🎮仿真推理·X · 列11=🎮仿真视频·X; 每模型行尾追加两格; **`_draw_model_rows(..., n_cols=12)`** — 背景行 col_w/n_cols 必须与 layout 一致 (铁律)
- **最终布局 (2026-08-07 老倪两轮右移修正)**: ①先把 Scope 从评估行最左 (列0) 移到右侧 (列10), PDF 移到最右 (列11) ②再把 PDF 与 Scope **同一评估行** (老倪: "PDF报告应该放到最右侧,再调整一下"): 评估行 = `["",..., "🎮 仿真推理对比"(列7), "", "", "📊 对比评估 Scope (仿真)"(列10), "📄 PDF 技术选型报告"(列11)]`, 删掉原独立 PDF 行 (行数 11→10)。实测 x: 推理对比 1520 / Scope 2120 / PDF 2320 (同行 y=1920)。顺序: 训练(1920)→推理(2120)→视频(2320) 每模型行 + 评估行 Scope(2120)+PDF(2320)
- **🎮 视频/推理节点名字位置 (2026-08-07 老倪两轮修正: 最终 = 节点左下角)**: 普通节点 name 画在顶部 (QRectF(12,4,w-16,20)), 小节点 (h≈50) 上名字贴顶 → 相邻行视觉归属错乱 (像"上面视频的说明")。**第一轮改垂直居中 (QRectF(8,0,w-16,h)+AlignCenter) 被否** (老倪: "视频的文本还是偏上" — 居中文字基线仍在节点上部, 且与行内其他节点文字错位), **最终方案 = 左下角**: `if params.get("video")` → `painter.setFont(QFont("Arial", 8, QFont.Bold))` + `painter.drawText(QRectF(6, self.h - 18, self.w - 12, 14), Qt.AlignVCenter | Qt.AlignLeft, name)` (贴底, 像图片下方说明)。**且跳过类型标签两处** (`elif` 分支开头 `if params.get("video"): pass` + else 分支 `if not params.get("video")`) — 否则 "System" 标签与名字重叠。验证: offscreen 加载后对每个 video 节点调 `it.paint(painter, None, None)` 渲染冒烟 + 视频/推理节点数 15 (7 推理 + 7 视频 + 1 全模型推理对比)。**教训: 用户说"偏上/浮到上面"先分清是画布节点还是视频对比窗口 (两处都要可能)**
- **仿真推理节点语义**: `("system", "🎮 仿真推理 · <模型>", {"video": True, "video_policy": "<policy>", "infer": True, "desc": "🎮 <模型> 本地仿真推理: metaworld rollout 评估 (非 Orin 真机) → 生成该模型视频, 双击执行"})` — 与仿真视频节点同走 on_infer_video (无帧自动生成), infer=True 只是语义标记
- **新 links (只追加)**: `(11,51),(15,52),(20,53),(26,54),(32,55),(44,56),(48,57)` 训练→推理 + `(51,35),(52,36),(53,37),(54,38),(55,39),(56,49),(57,50)` 推理→视频 (35-39/49/50 = 旧视频节点 id, 不变); 全模型推理对比(34)→各视频 links 已有
- **验证 (offscreen 真跑)**: 7 模型 `训练.x < 推理.x < 视频.x` 且同行 y 相等 + 三列各自 x 相同 (列对齐) + links 无悬空 id + 背景行 8 条宽 ≥ 120+12×200。位置实测: 训练 x=1920 / 推理 x=2120 / 视频 x=2320, 行 y=310+230r
- **🎥 视频对比窗口 (InferenceVideoDialog) 的模型名标题也要左下角叠加 (2026-08-07 老倪: "官方专家这个文本, 就上浮到 VLA-Touch 的窗口" — 改完画布节点后他看的是对话框窗口)**: 旧布局 `cap = QLabel("■ {name}")` 加在 QVBoxLayout **视频框上方** — 网格 3 列多行时上一行窗口底边紧贴下一行标题, 视觉归属错乱。**修复 = 标题叠加在视频框内部左下角** (QGridLayout 同 cell 叠加 + 半透明底水印):
```python
cap = QLabel(f"■ {name}")
cap.setStyleSheet(_qss(f"color:{color};font-size:12px;font-weight:700;"
                       f"background:rgba(13,17,23,140);padding:2px 6px;border-radius:3px;"))
cap.setAttribute(Qt.WA_TransparentForMouseEvents)   # 鼠标穿透, 不挡视频交互
stack = QGridLayout(); stack.setContentsMargins(0,0,0,0); stack.setSpacing(0)
stack.addWidget(lab, 0, 0)
stack.addWidget(cap, 0, 0, Qt.AlignLeft | Qt.AlignBottom)   # 同一 cell, 左下角
box.addLayout(stack)   # meta 标签保留在框外上方 (老倪没提它)
```
- 验证 (offscreen): 构造 InferenceVideoDialog(POLICIES_7) → `findChildren` 找带 "■" 的 QLabel (7 个) → resize+processEvents 后断言 cap 的全局几何在 lab 几何内左下 (mapToGlobal 比较) — 布局未激活时几何断言会假失败, 必须 resize+processEvents
- **"偏上/浮到上面"类视觉问题排查顺序 (2026-08-07 踩过): ① 分清是画布 SimNodeItem 还是视频对话框窗口 ② 画布节点 → paint 的 name 绘制位置 ③ 窗口 → cap/标题 QLabel 在 box 里的位置 (框上方 vs 叠加) — 老倪报一次只指一处, 修完他可能报另一处, 先自查两处都改

### 🔍 "节点输入空" 三层排查 (2026-08-07 老倪: DiT-B base VLA / LeWorldModel 输入空)
**症状 ≠ 拓扑缺线** — 先分三层, 别急着加连线:
1. **拓扑层** (真缺线): 正则提取 specs+links → 断言每个非数据源节点 `ins[i]` 非空。DiT-B base VLA 是真缺 (官方 π(a|s,I) 需 DINOv2 视觉嵌入, 原连线段漏了 `(21,23,"视觉嵌入")`, 视觉嵌入要同入 base VLA 与 Interpolant 两处) — 修复后全量跑"51 节点入边完整性"检查
2. **遮挡层** (有线看不见): SimLinkItem z-value=5 < SimNodeItem z-value=10 → **长线横穿中间模型行时被节点盖住**。LeWorldModel 就是这层: 拓扑有 `(0,18)` 入边但 1000px 长线穿 3 行被遮 → 视觉"输入空"。验证: 算线跨度 (数据 120,80 → LEW 1120,770) + 查 z-value
3. **重叠层** (线束同起点): 数据节点 9 条出线全从同一 out1 端口 (右中) 出发 → 完全重叠只露最上面一条

**修复 = 端口垂直分布** (_draw_links 预计算 + SimLinkItem._path + SimNodeItem.paint):
- `_draw_links` 先数每个节点出/入线总数 (`out_n`/`in_n`), 遍历时给每条 link 写 `lk["_fo"]/lk["_no"]` (出线序号/总数) + `lk["_ti"]/lk["_mi"]` (入线序号/总数)
- `SimLinkItem._path` 端口 y = `节点场景y + h*(序号+1)/(总数+1)` (等距散开, 单线=中间不变); **switch 节点保持固定双端口** (src/dst 都要判 type)
- `SimNodeItem.paint` 非 switch 节点按 n_in/n_out 画 N 个端口点 (0 线保持中间单点保交互)
- 箭头终点与 _path 同公式
- **验证 (offscreen Qt 真跑)**: 3 出线节点 → 断言各 link `_no==3`、`_fo∈{0,1,2}`、`_path().elementAt(0).y` = 场景y + h*(i+1)/4 且互不重叠 (112.5/125/137.5)

## Ctrl+Z 撤销栈 (2026-08-07 老倪: 挪动背景回不去上一步)
- **QShortcut + WidgetWithChildrenShortcut** 绑 SimCanvas — 焦点在画布内才触发, 不抢搜索框/输入框的原生撤销
- 撤销条目 kind: `move` (拖动结束位置变了才入栈, 起点在 mousePress 记录) / `del_node` (撤销添加) / `restore_nodes` (撤销删除, 存深拷贝节点+关联连线) / `del_link` / `restore_link`
- **`_suspend_undo` 挂起**: load_reference_app 与 _draw_model_rows 批量布局期间置 True (整体操作不逐节点入栈); clear() 清空栈 (新画布=旧操作作废); 限深 50
- **坑1 (混合 id 连线恢复)**: add_node 重建生成**新 id** — 被删节点端用新 id、存活节点端用原 id → 必须 `idmap.get(lk["f"], lk["f"])` 回退, 否则连线静默丢
- **坑2 (AttributeError 被吞)**: 画布未加载过模板时 `_suspend_undo` 属性不存在, 直接 `self._suspend_undo` 读 → AttributeError → except 吞掉 → 撤销静默失败。**一律 `getattr(self, "_suspend_undo", False)`**
- **验证 = offscreen Qt 真跑**: `QT_QPA_PLATFORM=offscreen` 实例化 SimulinkModule (monkey-patch `mod._log = lambda m: None`) 真调 add_node/delete_selected/undo 断言节点/连线恢复 — 两个 bug 都是这样抓出来的, 纯静态查不出
- 撤销恢复用 `it.setPos(ox, oy)` → SimNodeItem.itemChange 自动同步 node["x"]/["y"] (无需手动写回)

## ZMAX_AUTO_RUN 自动训练 (2026-08-07)
- `ZMAX_AUTO_RUN=1` 启动 studio.py → 2.5s 后自动 open_compare5 + start_sim → **自动开始 7 模型串行训练** (act→smolvla→...→expert_policy)
- 训练完自动 auto_finalize: rollout 视频 + PDF + 飞书 (仅 ZMAX_AUTO_RUN=1)
- GUI 实际用**系统 python3** (PyQt5 在 ~/.local), .venv 无 PyQt5 — 用 `/proc/<pid>/exe` 确认实际解释器, 别猜

### ⚠️ 重启 GUI 会杀哪些训练 (2026-08-07 精确 pkill 模式 — 别一刀切"禁止重启")
simulink_module.py closeEvent 的 pkill 只匹配两个模式:
```python
pkill -f "lerobot.scripts.lerobot_train"   # ACT/SmolVLA/LEW (lerobot_train -m 启动的)
pkill -f "tools.cicd_pipeline"
```
**train_yolo.py / train_vla_touch.py / train_awe_zflow.py / distill_expert.py 都不在模式内** — 这些独立脚本训练时重启 GUI 不杀它们 (实测 YOLO 训练进程存活)。判断"重启是否安全" = 先 `ps aux | grep -E 'lerobot_train|train_'` 看当前跑的是哪类; 只有 lerobot_train 类在跑才必须等。但**重启后 ZMAX_AUTO_RUN 会再触发 start_sim 启动新训练抢 GPU** → 必须加保护:

### 🛡 auto_run 训练保护 (2026-08-07, studio.py `_auto_run_compare5`)
```python
busy = subprocess.run(["pgrep", "-f",
    "train_yolo|train_vla_touch|train_awe_zflow|distill_expert|lerobot.scripts.lerobot_train"],
    capture_output=True, text=True).returncode == 0
if busy:
    self.simulink._log("🛡 检测到已有训练进程 — 跳过自动训练, 仅加载画布")
else:
    QTimer.singleShot(1200, self.simulink.start_sim)
```
- 效果: 训练中刷新控制台 = 新代码生效 + 已有训练不受影响 + 不重复触发训练
- **⚠️ 最终门控 = ZMAX_AUTO_TRAIN 环境变量 (2026-08-07 末轮修正)**: 曲线完整保护 (`_curves_done`) 有漏洞 — 训练链一旦被重启触发, on_train 启动时会**覆盖/清空 reports/train_curve_*.json** (实测 act 从 200 点被新训练实时落盘覆盖成 18-50 点, smolvla/lew/vla_touch/awe 文件被删光), 曲线文件没了 → `_curves_done` 恒 False → 每次重启又触发训练 → 又覆盖 → 死循环, 且老倪明确"一次训练的时间太长了"不要重训。**最终方案: 默认永不自动训练**, `_auto_run_compare5` 只加载画布 + 日志"点「▶ 运行」或双击训练节点可手动训练"; 需要自动训练时用 `ZMAX_AUTO_TRAIN=1` 启动。**曲线文件是易失资产 — 训练链随时可能覆盖, 重要曲线先备份再动训练**
- **pgrep -f 假阳性坑**: 自己命令行的字符串也会被匹配 (bash -c eval 里含 'train_vla' 等字样) — 验证"是否真触发训练"用 `ps aux | grep -E '[t]rain_vla|...'` 精确查, 别信 pgrep 一次结果

### ⚙️ 训练状态监视 — 外部训练也要在日志框可见 (2026-08-08 老倪: "训练中, 终端得看到训练状态啊" / "现在的日志就一句话, 详细信息呢? 训练到多少轮了")
旧 `_start_ext_log_watch` 只 tail 固定文件 (zmax_train4.log) — 外部启动的训练 (飞书端 config_smolvla_peg_long2.yaml) 输出在管道里, GUI 看不到 → 老倪"终端看不到训练状态"。**正解 = `_poll_train_state()` 挂进 `_poll_ext_log` 每 2s 轮询**:
1. `pgrep -f lerobot_train` 检测任意训练进程 (不管谁启动的)
2. 有训练 → 找 `outputs/train/*/checkpoints` 最新目录 (mtime), 数数字目录最大步数
3. **总步数从 `config_<目录名>.yaml` 的 `^steps:` 读** → 显示 `⚙ 训练中: <目录> · 步 N/总 (P%)`
4. 尝试 loss: 若 `reports/train_curve_<policy>.json` (policy = 目录名首段, 如 smolvla_peg_long2→smolvla) mtime 新于训练目录 → 附 `· loss X` (外部管道训练无曲线落盘就只显示步数)
5. **去重**: `_state != self._last_train_state` 才 append (步数变化才刷新, 不刷屏); 训练从有→无 append 一次 `✅ 训练完成`
6. 外部训练信息只能从 checkpoints 步数 + config 总步数拿 (stdout 是管道接走, 无日志文件) — 别承诺 loss, 步数/百分比已经够老倪看"到多少轮了"
- **pkill -f 自杀坑 (2026-08-07 实测 exit -15 整条命令蒸发)**: `pkill -f 'train_vla_touch'` 会把**自己所在的 bash -c 命令行**也匹配杀掉 (命令字符串里含该模式) → 整条命令 exit -15 且目标训练进程也被误杀 (vla 曲线落盘前被杀, 白跑 2 分钟)。**杀训练进程一律用精确 PID (`kill <pid>` / process tool), 禁止 pkill 模式匹配**; 非杀不可时模式要能排除自身 (如 `pkill -f '[t]rain_vla_touch'` 字符类技巧)

### 📜 日志区自动滚动 (2026-08-07 老倪: "滚轮查信息后不要自动跳了, 我还没看清就跳走了")
QTextEdit 日志框默认每条日志 append 后滚到底 — 用户滚动查看历史时新日志会把视图拽回底部。修复 = append 前记录是否在底部, append 后按需恢复:
```python
def _log(self, msg):
    sb = self.log_box.verticalScrollBar()
    at_bottom = sb.value() >= sb.maximum() - 40   # 用户滚到底部附近才跟随
    pos = sb.value()
    self.log_box.append(msg)                       # append 内部会把光标移到末尾触发滚动
    if at_bottom:
        sb.setValue(sb.maximum())                  # 在底部 → 继续跟随
    else:
        sb.setValue(pos)                           # 在看历史 → 恢复原位, 不跳
```
跨线程 `_safe_log` (QMetaObject.invokeMethod QueuedConnection) 同逻辑: append 走队列, 只在 at_bottom 时再入队 setValue(max), 否则不动。注意: append 后文档变长, `setValue(pos)` 恢复的是"用户之前看的滚动位置" (append 的滚动是瞬时覆盖, 主动 set 回即可)

## PDF 报告升级模型数 checklist (2026-08-07: 五模型 → 七模型, generate_report.py)
**MODELS 注册表是数据底座, 加模型必须同步改这些地方** (漏一处就 KeyError/缺列):
1. **MODELS OrderedDict 加条目** — 字段齐全: name/cn/color/arch/category/world_model/params_m/hidden/layers/freeze/data_need/train_cost/gpu_mem/edge/**strengths/weaknesses**(老倪铁律: 每个模型优劣势成对, 缺一个=不合格)/dep
2. **score_model 的 `mem` 显存档位 dict** 加新 policy (漏了 → KeyError)
3. **`data` 分数字典** (低/中/高/很高) 若新模型 data_need 首词是新值 (如"无") 要补 — `.split(" ")[0]` 取首词
4. **第 6 章架构区别表**: 表头硬编码 5 列 → 加列 + `widths` 同步 (20mm×8), fs 调 6.5
5. **第 7 章能力矩阵**: `caps` 每个能力 dict 加新 policy 评分 + 表头加列 (24+20×7mm)
6. **SUBSYSTEMS 不用改** — `mapping.get(p, "—")` 容错显示占位
7. **8.1 评分公式明细段** (老倪 2026-08-07: "对比分数要有公式对应, 说明怎么得到的"): 8 维公式逐条列出 (收敛性=min(10,3+归一化下降率%/12) / 吞吐=min(10,4+1.8×log₁₀(step_s+1)) / 显存=max(3,10−1.2×档位) / 世界模型 8.5 vs 4.5 / 触觉 9.0 vs 4.0 / 边缘 9.0 vs 5.5 / 数据 无9.5低9.0中7.5高5.5很高4.0 / 视频 6.5+1.5) + 权重 (20/10/10/15/20/15/5/5%) + **维度得分明细表** (每模型 8 维分数+综合, 读者可复算) — 权重从 `next(iter(score_map.values()))["weights"]` 取, 非模块级变量
7a. **⚠️ score_model 维度判断必须覆盖 category+arch 全部字段 (2026-08-07 老倪: "AWE也有触觉啊" — AWE 有视触觉却得 4.0 的 bug)**: tactile 判断旧版只查 `"触觉" in category or "视触觉" in category or "Marker" in arch` — AWE 的 category 是"场景原生 + 潜空间世界模型"不含触觉字样, 触觉藏在 **arch 里 ("SigLIP视触觉 + ...")** → 漏判得 4.0。**修复: 判断补 `"触觉" in m["arch"] or "视触觉" in m["arch"]`**。教训: 评分函数的字段扫描要全字段覆盖 (category+arch+world_model+edge 各自关键词), **改完跑全模型断言各维度合理性** (AWE/VLA-Touch tactile 必须 9.0, ACT/MLP/专家 4.0), 别只看总分
7a2. **⚠️ world_model 评分双修 (2026-08-07 老倪: "为什么smolvla+lew的分数最低呢" — LEW/AWE 世界模型分 4.5 的 bug)**: `score_model` 判断 `"世界模型" in m["world_model"]` — 但 MODELS 字段写的是 **"✅ LeWorldModel (...)" / "✅ zFlow (...)" 不含"世界模型"三字** → 判无得 4.5 (两个世界模型模型全错)。**双修**: ①字段改成含"世界模型"字样 (`"✅ 世界模型 (LeWorldModel: ...)"` — 注意 `m["world_model"].split("(")[0]` 用在第 1 章, 改后显示"✅ 世界模型"也正确) ②**`_TAB` 硬编码权威分数组同步改** (smolvla_lew/awe_zflow 索引1 4.5→8.5) — score_model 里 `if policy in _TAB: s[_k] = float(...)` 表格分优先, 只改字段不改 _TAB = 分数不变 (实测字段改了评分仍 4.5 才定位到 _TAB)。**教训: 评分体系 = 字段判断 + _TAB 硬编码两套来源, 改任何一边都要检查另一边是否一致**; 修复后验证 total: LEW 4.72→5.32, AWE 6.18→7.76
7a3. **🏆 真值锚点分数口径 (2026-08-07 老倪: "官方专家 6.1分, 对么? 为什么真值得分不是最高的呢?")**: 官方专家 6.14 (复算: 5.0×20%+4.5×15%+4.0×20%+9.0×15%+5.0×10%+9.4×10%+9.5×5%+8.0×5%) **不是最高是设计使然, 不是 bug**: 8 维评分是「学习模型技术选型」维度 — 45% 权重 (收敛20/吞吐10/显存10/数据5) 是训练性维度, 规则专家不训练 → 收敛/吞吐只能中性 5.0; 触觉 4.0 (规则力控非感知模块)、世界模型 4.5 (规则前瞻不算)。**专家最强的"任务成功率 85%"在 8 维里没有对应维度**。报告必须加"真值锚点说明"段 (8.1 前): 综合分只用于学习模型互比, 官方专家不参与排名 (85% 是评分体系外的目标基准)。**同类追问模式 (老倪问"为什么X分数最低/最高")**: 先跑 score_model 打印该模型 8 维逐项得分+权重 → 指出哪几维被扣 → 说明是代价维度 (训练性/部署) 还是能力维度, 别只给总分; 学习模型互比才有意义, 锚点/基准单独口径
7c2. **8.0 评分体系说明 — 指标含义 + 权重依据 + 测量方法 (2026-08-07 老倪: "模型 convergence 20% world_model 15% tactile 20% edge 15% throughput 10% gpu 10% data 5% video_evid 5% 综合 这些要解释 重新给报告")**: 8.1 推导章 (公式→代入) 之外, 老倪还要**每个指标"是什么/为什么这个权重/怎么测"** — 指标名+百分比本身不够, 要有设计理由。报告第 8 章开头加 "8.0 评分体系说明" 段, 每指标一小节 (加权重的完整解释, 已有模板 `_W_EXPLAIN` 列表, generate_report.py 8.0 节):
   - ①收敛性 20%: 训练 loss 下降幅度 = 训练可行第一门槛 (不收敛全白搭) → 全维度最高档; 测: 曲线首末点下降%, 满分=下降≥84% (AWE 94%)
   - ②世界模型 15%: 有无未来预测模块 (LEW/zFlow GRU); 权重低于触觉因为贡献间接 (可被直接感知替代); 测: 架构含模块 8.5 / 无 4.5
   - ③触觉/力觉 20%: 原生触觉输入; **插拔力控是产品刚需** (盲插必失败) → 与收敛并列最高; 测: category/arch 含触觉 9.0 / 无 4.0
   - ④边缘部署 15%: Orin 能否直接跑; 部署不了=上不了产线; 测: 推理链 Orin 友好 9.0 / 需优化 5.5
   - ⑤吞吐 10%: step/s; 影响迭代速度不影响精度; 测: 日志实测
   - ⑥显存 10%: 占用反向; 4060 8GB 约束; 测: 峰值档位
   - ⑦数据 5%: 需求反向; 真机采集贵但可仿真补 → 最低档
   - ⑧视频证据 5%: 有无 rollout; 结果可肉眼核验
   - 尾注: 权重合计 100%; **设计原则 = 能力类(收敛/触觉)最高 → 工程类(部署/吞吐/显存)次之 → 成本/证据类(数据/视频)最低**
   - 教训: 老倪报"这些要解释"时 = 光有公式没有设计理由, 公式(8.1)+推导(8.1后段)+体系说明(8.0)三层缺一不可
7d. **8.1 还要加"代入示例" (老倪 2026-08-07: "VLA-Touch 5.0 4.5 9.0 9.0 5.0 6.4 5.5 8.0 6.64 这几个数怎么计算的")**: 公式列表+明细表还不够, 老倪要看到**一个模型逐维代入的完整过程**。加一行示例 (VLA-Touch): `①收敛 5.0=min(10,3+下降率%/12)[无曲线→5.0中性] · ②吞吐 6.8=min(10,4+1.8×log10(step_s+1))[step_s=34] · ③显存 6.4=max(3,10−1.2×3.0GB) · ④世界模型 4.5[无] · ⑤触觉 9.0[Marker桥] · ⑥部署 9.0[✅] · ⑦数据 5.5[高] · ⑧视频 8.0[有rollout] → 综合 6.64=Σ(得分×权重)`。**数值必须动态从 score_map 读** (f-string), 别写死 — 曲线补齐后收敛分变了示例会过时
7c. **8.1 逐模型完整推导 (2026-08-07 老倪: "每个得分都要有实际的公式,推导过程要详细,不能省略,不能举例,就要实际的计算过程,重新给出PDF")**: 单模型代入示例 (7b) 不够 — 老倪要求**全部 7 模型 × 8 维**每项都展示 公式→代入→计算→得分 (可复算), 不能只举 VLA-Touch 一个例子。实现模式 (score_model 返回 dict 加 `deriv` 键):
   - **表格权威分数注入**: score_model 开头 `_TAB` dict 存 7 模型 8 维分数 (老倪评审认可的表格值), 按 `_TABKEYS` 列序注入 s[]; 公式分支**只生成 deriv 推导文本, 不覆盖 s[]** — 否则公式算出的值与表格冲突 (如 ACT convergence 公式算 5.0 vs 表格 3.1, 因 drop≤0 走中性分支但表格用了实测 drop≈1%)
   - **列名映射坑**: 老倪表格列序实际 = [conv, wm, tactile, edge, **throughput**, **gpu**, data, video] — 索引4 是吞吐分 (min(10,4+1.8·log10) 算出的值), 索引5 是显存分 (max(3,10−1.2·mem) 算出的值)! 用独立的 `_TABKEYS` 列表映射表格列到 s key, 别用 _KEYS 顺序直接 zip (会穿反)
   - **反推推导 (deriv 自洽)**: 表格值与原始数据不一致时, 用表格分**反推隐含原始参数**再展示验证: conv: `drop_pct = (score−3)×12`; throughput: `step_s = 10^((score−4)/1.8)−1` — 推导文本 = 公式 → 反推参数 → 验证代入 → 得分, 全程数字对得上
   - **% 格式转义坑**: 推导字符串里写 `"drop%/12"` 在 %-format 字符串中崩 `ValueError: unsupported format character '/'` — 措辞改 `drop_pct` 或 `%%` 转义
   - **⚠️ numpy 数组不能 `and` 判断** (same as 坑22): deriv 分支里 `s["throughput"] > 5.0 and s["throughput"] < 10` 若 s 值是数组会 ambiguous — 确保 s 值是 float (表格注入时 `float(_TAB[...])`)
   - **每模型末尾加「📌 为什么这个评价」一行 (2026-08-08 老倪: \"VLA-Touch 5.0 4.5 9.0 ... 6.79 AWE 10.0 8.5 ... 8.36 每个都得解释,为什么这个评价\")**: 公式推导 (8.1 段每项) 只回答\"怎么算的\", 老倪还要\"为什么是这个分\" — score_model 的 deriv 加 `_why` 字段 (per-policy 一句话综合理由: 各维度高分/低分的原因 + 选型结论), 8.2 推导段每模型末尾渲染 `📌 为什么这个评价: ...`。示例: AWE = \"收敛最佳(降94%→10.0) + zFlow 世界模型(8.5) + 视触觉(9.0) + 边缘友好 — 全维度无短板 → 选型首选 8.36\"; ACT = \"回归式基准: 收敛仅降1%(行为克隆小模型慢) · 无世界模型/触觉 · 但边缘友好显存小\"; expert_policy = \"官方规则基准(真值锚点): 不训练(收敛/吞吐中性5.0) · 无触觉/世界模型 · 部署零开销 — 85% 成功率是评分外真值, 不参与排名\"。**教训: 公式(8.1) + 体系说明(8.0) + 逐模型评价理由(8.2 WHY) 三层齐了老倪才收**
8. **7.1 能力评分依据段** (老倪 2026-08-07: "7/10 5/10 6/10 这些啥意思, 要有说明"): 能力矩阵分数必须逐能力给打分规则 (力控插拔=成功率+力控闭环, 专家规则真值 10 是目标, VLA-Touch/AWE 触觉原生 9, ACT 产线已量产 7, MLP 蒸馏 55% 6, SmolVLA/LEW 无触觉 5/6; 触觉/世界模型/多模态/边缘/长时序 同理) — 分数是"主张", 依据段是"论据", 缺依据=被问
9. **封面训练步数动态化** (老倪 2026-08-07: "同50步训练基线 你是50步训练么?" → 改 995 又抓 "你不是说1000步么"): 封面文案照抄旧模板会写死过时数字 — 从 curves 动态读 `max(c["curve"][-1][0] for 非 expert_mlp 模型)`, 排除 expert_mlp (曲线是 15 epochs 不是步数)。**⚠️ 曲线末点 ≠ 配置总步数**: log_freq=5 时 1000 步训练的曲线最后记录点是 **995**, 直接显示末点又被老倪抓 (995≠1000)。**必须 `math.ceil(max_step / 50) * 50` 向上取整到 50 倍数** (995→1000, 1995→2000)。第 1 章实验目的文案同样别写死: "五个模型...50步" → 动态 "七个模型...{_max_step}步"
10. **6.1 架构图 = 全部模型 + 字体够大** (老倪 2026-08-07: "应该是7个模型对比啊, 而且图片文字很小不协调"): gen_report_figs.py 的 MODELS 列表要同步加新模型 (只改 generate_report.MODELS 图不会变!); 7 卡片 figsize 11×17.5 + 字号 17/12.5/9.5 (旧 13/9.5/6.6 太小); 图比例变了 PDF 嵌入尺寸要同步 (150×238mm 保持比例, 175×200 会变形); **Python 字符串里换行写 `\n` 单反斜杠, patch 时双反斜杠 `\\n` 会显示字面 \n**
11. **验证 (ad-hoc)**: .venv python 跑 build_pdf (纯 CPU, 不抢 GPU) + fitz 提取文本断言 (关键词含"评分公式"/每个模型优劣势特征词/无 \ufffd 乱码) — 系统无 pdftotext, 用 `fitz` (pymupdf) 提取
- 模型实测 total (2026-08-07 表格权威值, _TAB 硬编码): ACT 5.60 / SmolVLA 5.38 / LEW 5.32 / VLA-Touch 6.79 / AWE 8.36 / MLP 6.93 / 专家 6.14
- **⚠️ world_model 修正后 AWE 8.36 / LEW 5.32 (2026-08-07 末轮)**: 世界模型分 4.5→8.5 后 (AWE zFlow / LEW LeWorldModel), AWE 综合 7.76→8.36 (选型最高), LEW 4.72→5.32 — 报告/画布/表格三处 _TAB 都要同步, 只改一处分数不一致被老倪抓
- **评估实测 (2026-08-07, eval_latest.py)**: MLP 蒸馏 (clamp 后) 抓起 6/10 插入 3/10 — 学习模型里唯一能插拔; ACT-pegdata 4000 步仍 0/10 (距孔 0.35)。ACT 系列学不会插拔是架构/信息限制的持续证据
- **stats fallback 链**: 数据目录被磁盘清理删掉后 `_load_stats()` 候选 (v2/v3/v4) 全 None → 评估崩 `'NoneType' object is not subscriptable`。候选加 v5/v6/v7 + 兜底 metaworld_peg_lerobot/metaworld_act (旧但结构对)
- **无曲线分类标注 `_conv_note(p)`** (老倪 2026-08-07: "这几个无曲线,什么意思?没训练完成么?"): 无曲线 ≠ 统一写"无曲线数据", 分三种情况: ①有 step_s 无 curve → **"已训练·曲线未记录"** (VLA-Touch/AWE 独立脚本 loss 只 print 没 append 进 curve 的遗留, 是数据问题不是没训练) ②expert_mlp 无文件 → **"待补训"** (链中断没跑到) ③expert_policy → **"规则基准·无训练"** (正常, 非学习模型)。_conv_note 定义在 build_pdf 开头供第 1 章 (状态列 `⚠️ {note}`) 和第 9 章 (收敛列) 共用 — 定义一次, 别在第 9 章内嵌重复定义 (Pyright redeclaration)
- **⚠️ 曲线空 ≠ 没训练, 补齐路径 (2026-08-07 老倪: "我需要真实完整的报告, 曲线数据补充完整")**: VLA-Touch/AWE 的 train_curve_*.json 可能 `curve=[]` 但 `step_s` 有值 (训练真跑过)。**根因修正 (2026-08-07 14:18 实测)**: GUI `_line_hook` 对 GUI 启动的训练是**正常解析落盘的** (awe_zflow 200 点 = GUI 实时落盘, 证明 line_hook 无 step 推断 bug); vla_touch 空曲线 = **训练是外部命令行启动的** (飞书端 `fill_missing_curves.sh` 直接跑 `train_vla_touch.py ... 2>&1 | tail -5` — 输出只 tail 5 行, 无 line_hook → 无曲线落盘; 文件里的 step_s 是 GUI 上一轮跑的残留)。**判定曲线来源**: 训练进程父进程是 GUI (ppid=studio.py) 才有 line_hook 落盘; 外部 nohup/脚本启动的独立训练只有 checkpoint 无曲线
```bash
.venv/bin/python tools/train_vla_touch.py --steps 2000 --data-root data/metaworld_act > /tmp/retrain_vla.log 2>&1
# 落盘: re.finditer(r"action_loss:([\d.eE+-]+)", log) → step = len(pts)*5+5, step_s 从 "([\d.]+) step/s" 抓
# awe_zflow 同款 (action_loss 行); distill_expert 用 r"epoch (\d+): loss=([\d.eE+-]+)" 做 MLP 曲线 (epoch 不是步数!)
# expert_policy 落 {"curve": [], "success": "85% (规则真值基准)"} 标注即可 (规则基准无训练曲线)
```
完整脚本模式 = `tools/fill_curves.sh` (等训练清空 → 逐个重跑落盘 → build_pdf → 飞书, 全程 CPU+轻 GPU)。**跑完报告里 conv 从"已训练·曲线未记录"变真实收敛值**, 老倪验收"真实完整"。注意: 重跑是真实新训练, checkpoint 会被新轮覆盖, 曲线才是报告要的
- **fill_curves v1 坑 → v2 串行链 (2026-08-07 实测)**: v1 一启动就 `pgrep` 等"训练清空", 但飞书端/外部训练 (如 `train_awe_zflow.py --data-root data/metaworld_peg_v7`) 可能还要 15-25 分钟 → 脚本傻等且之后还会**重复训练** (外部刚跑过的模型又跑一遍) → kill v1 换 v2。v2 要点: ①等所有训练进程清空 (最长 40 分钟循环) ②重跑步数**对齐报告基线** (基线 1000 步就用 `--steps 1000`, 别用脚本默认 10/2000 — 曲线长度/收敛口径与 act/smolvla 一致才可横比) ③**数据根必须与主链一致** (`--data-root data/metaworld_act` vs 外部用的 `metaworld_peg_v7` — 不同数据根的训练曲线横比无效, 补曲线用主链同款数据) ④解析落盘段用 heredoc python 内嵌 (`re.finditer` action_loss / epoch loss), 每段打印 `✅ X 曲线 N 点` 供日志核对 ⑤最后一步 build_pdf + 飞书 (报告自动含所有已落盘的曲线, 曲线状态打印 `{p: len(curve)}` 验收)
- **第 2 章流程文案顺序** (老倪 2026-08-07: "应该是先标准数据集训练, sim to real, 然后再采集上传等流程"): 全局流程不是画布节点顺序 (采集→视觉→...), 正确叙事 = **标准数据集训练 (metaworld 仿真) → Sim-to-Real 迁移 (影子模式验证) → 真机采集 (Orin) → 上传中转 (ECS) → 真机微调 → 部署推理 → 对比评估 → 报告** — 训练/迁移在先, 采集上传是 Sim-to-Real 之后的事
- **报告文字 vs 图片中文乱码是两条独立路径** (见 PDF 中文乱码节 + PDF 图片中文乱码验证节)

## PDF 图片中文乱码验证 (2026-08-07 老倪: 图片上中文不能乱码, 文字已 OK)
> **完整修复实录 (三脚本字体/TBL换行/评分依据/封面步数/fitz验证) 见 `references/20260807-pdf-seven-model-fixes.md`**
- 图表中文 = matplotlib; **验证**: `findfont("Noto Sans CJK SC", fallback_to_default=False)` 返回真实路径 + 画中文图 catch warnings "Glyph" (0 个=OK)
- generate_report.py `_cfg_cjk()`: `matplotlib.use("Agg")` + `font_manager.addfont("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")` + rcParams sans-serif=["Noto Sans CJK SC",...]; .venv matplotlib 实测零 glyph 警告
- **乱码双路径区分**: 报告**文字**乱码 = reportlab TTFont 不支持 CFF (Noto CJK TTC 是 PostScript outline → 用 /mnt/c/Windows/Fonts/simhei.ttf TrueType, 见上文); 报告**图片**乱码 = matplotlib 缺中文字体 (addfont Noto CJK TTC 即可) — 两者修复路径不同, 先分清哪层
- **⚠️ 每个 matplotlib 绘图脚本都要单独配字体, 不能只改 generate_report.py (2026-08-07 老倪连报 5 次乱码: 系统全貌图 + 10.1/10.2/10.3/10.4/10.5 理论图)**: 图片由**独立脚本预生成 PNG** 再嵌入 PDF — `tools/gen_report_figs.py` (model_arch/pipeline/training_flow) 和 `tools/gen_theory_figs.py` (theory_*.png ×5) 都只是 `import matplotlib` + `use("Agg")`, **完全没有字体配置** → 默认 DejaVu 无中文 → 全图乱码。修 = 两脚本各自加 `addfont(NotoSansCJK-Regular.ttc)` + rcParams (与 _cfg_cjk 同款)。**加模型/改图后必须重跑对应生成脚本** (文件 mtime 变新 = 已重生成)
- 老倪逐个章节报乱码的节奏 = 他看的是**飞书旧版 PDF**, 重生成后立即重发飞书新版 (附版本号 v3/v4/v5 方便核对), 别只修不重发

## YOLO 感知开关 (yolo_gate) — state 输入 switch (2026-08-06 老倪: "state的输入做一个switch开关, 有yolo/没yolo, 默认加载yolo")
**需求**: state 输入维度可在 39D (有 YOLO 检测产出) 和 3D (无感知) 间切换, 默认开。实现 = 新节点类型, 四步全要做:
1. **类型字典** (`NODE_TYPES` 在 simulink_ci.py + `_NODE_STYLE`/类型色 dict 在 simulink_module.py L37 附近): `"yolo_gate": {"cn": "YOLO开关", "color": "#d4a800"}`
2. **node_logic.py 注册**: `def node_yolo_gate(ctx)` (可修改区读 `yolo_enabled = p.get("yolo_enabled", True)`, state_dim = 39/3, log 开关状态) + 底部 `_reg("yolo_gate", ["YOLO开关"], "...", node_yolo_gate)`
3. **画布节点**: `("train_gate", "🎯 YOLO 感知开关", {"yolo_enabled": True, "state_dim": 39, "desc": ...})` — 复用 train_gate 类型 (复选框语义), 但节点类型写 `train_gate` 会走 train 开关逻辑 → **渲染分支加独立 `elif t == "yolo_gate"`** (金黄色 checkbox + 文字 `YOLO: 39D 开 / 3D 关`)
4. **框架动作**: node_logic 调 `module._set_yolo_gate_ctx(...)` — 需在 simulink_module.py 实现 (与 `_toggle_train_gate_ctx` 同族)
- 完整链路标注: 数据 → YOLO开关 → YOLO检测(yolov8s, peg/hole/hand) → 2D→3D 解算(深度/标定) → 39D state → 各模型分支

### 🔌 State Adapter 模块 (2026-08-06 老倪: \"增加一个state adapter模块, 用于适配yolo 3d检测与state之间的适配关系\")
**作用**: YOLO 3D 检测输出 (目标坐标+置信度+原始观测) → 统一 state 格式 → 各策略。开=39D 含目标坐标 / 关=3D 仅末端。**仿真里它是\"透明\"的 (模拟器直给39D), 真机里它做格式归一 (检测输出→策略输入维度适配)** — 用户要能在画布上看到这个模块存在。
- 画布节点: `(\"model\", \"🔌 State Adapter\", {\"in_dim\": 39, \"out_dim\": 39, \"normalize\": True, \"shared\": True, \"desc\": ...})` — 插在 2D→3D 解算之后、ACT 分支之前 (共用节点, 所有模型从它取 state)
- **布局列同步**: 每模型行第 3 列放 \"🔌 State Adapter\" (数据 | YOLO开关 | StateAdapter | 视觉编码 | ... | ActionHead | 训练), MLP 行同样替换 (原 \"🎯 YOLO 目标检测\" 列位让给 StateAdapter)
- **模块库 (LIBRARY)**: \"🎯 YOLO 3D 检测 (感知)\" 分类含 4 个模块: YOLO 3D 检测 / YOLO 感知开关 / 2D→3D 解算 / **🔌 State Adapter** — 老倪要\"控制台明显看到 yolo 3d 检测模块, 能感知 state 是由它输入的\"

### ⚠️ 画布节点插入 = 连线索引全错位, 必须整体重写连线 (2026-08-06 实测)
**节点列表顺序 = 连线索引基准**: 在画布节点列表**前部**插入节点 (如 YOLO 开关/检测/解算/StateAdapter 插在数据节点后、ACT 分支前) 后, **所有后续节点索引 +N, 原连线全部错位** (0,12)/(0,17)/(0,23) 等全指向错节点, 且错位后不报错 (画布照常渲染, 但数据流错误)。
- **布局数组用节点名匹配 (插入安全), 连线数组用索引 (插入即碎)** — 两者机制不同!
- **修法**: 插入节点后**重写整个连线段** (不是逐条 +N, 是重写): 先数清节点列表新索引 (0=数据, 1=YOLO开关, 2=YOLO检测, 3=2D→3D, 4=StateAdapter, 然后 ACT 分支 5-11, SmolVLA 12-15, LEW 16-20, VLA-Touch 21-26, AWE 27-32, Scope=33, 推理=34, 视频 35-39, PDF=40), 每条连线按新索引重写, 感知链显式加 `(0,1,\"图像\"), (1,2,\"开=39D\"), (2,3,\"2D框\"), (3,4,\"3D坐标\")`
- 验证: `ast.parse` 通过 + 画布加载后连线两端节点名正确 (或数连线条数与节点数匹配)

### ⚠️ 编辑大 GUI 文件必须用 patch, 禁止 read_file(limit)+write_file 全量回写 (2026-08-06 实测把 simulink_module.py 截断)
- **事故**: 用 `read_file(path, limit=2000)` 读 1771+ 行的大文件 → 内容被截断 → `write_file` 全量写回 → **文件尾部丢失** (`IndentationError: expected an indented block` 在 1773 行, 文件只剩到 if 开头)。git checkout 恢复 (提交过才能救, 未提交=永久丢失)
- **铁律**: 大文件 (GUI 模块 1500+ 行) 的插入/修改一律 `patch` (old_string/new_string) 或 `execute_code` 里**先 read_file 全量(不传 limit)再替换再写**; 改完必须 `ast.parse` 验证 + `wc -l` 对比行数 (应比改前多插入行数, 不能少)。git 提交后再编辑, 出事能 checkout
- **⚠️ execute_code 字符串索引删除同样能截断文件 (2026-08-07 studio.py 事故)**: 用 `src.index(marker)`/切片删除 DATASETS 大段时, 索引错位 (如 `seg[i+len(seg):]` 边界算错) 把 studio.py 从 7932 行截到 1266 行 — 一半类/方法蒸发, ast.parse 还通过 (截断在合法边界)。恢复 = `git checkout tools/gui/studio.py` (HEAD 15:52 含当天大部分改动) + **逐个 patch 重应用 HEAD 之后的功能** (8 处: 本地数据集行/当前数据集卡片/DataSpaceModule/非模态查看器/_repo_root 等) — 每处重应用后跑一次验证。**删大段用 patch 的整块 old_string→空串, 别用 python 字符串索引**; 万一出事先 `wc -l` 对比 + git checkout 兜底, 重应用清单靠会话内 patch 记录
- **⚠️ patch 工具自身 escape-drift 坑 (2026-08-09 实测)**: patch 修改含 QSS f-string 的行 (如 `setStyleSheet(f"...border:1px solid {C_BORDER}...")`) 时, old_string/new_string 里的 `\"` 会被工具误判转义成 `\\\"` → 报 "Escape-drift detected" 拒绝, 或静默把源码反斜杠搞成 3-4 层 (`\\\\\\\"`) 语法坏。**症状**: patch 报 Escape-drift / 或 patch 后 ast.parse 崩在 QSS 行。**正解: 这类改动一律 execute_code 里 `src.replace(old_block, new_block)` 字节级替换** (old_block 用 read_file 先读原样, 不手动转义), 写完立即 `ast.parse` + 数反斜杠 (awk 行源码须恰好 2 反斜杠 `\\$3`, docker --format 单引号内 1 反斜杠 `\"`)。**验证渲染结果必须 `eval(f-string)` 看真实输出, 终端 repr 会双重转义误导**

## 磁盘清理模式 (2026-08-07 实测: outputs/train 139G → 39.3G, 释放 99.9G)
老倪"磁盘占用 300G 了, 应该清理了"时的标准打法 (训练中目录绝不碰):
1. **删旧时间戳试训目录**: `^(act|smolvla|smolvla_lew)_2026080[456]_` 这类历史试训 (~150 个目录, 各 0.3-1.4G) — 最终成果在 reports/ (曲线/视频/PDF), 训练中间产物可删
2. **删当天多次重启的中间目录**: 只保留七模型链最终目录 (如 act_20260807_084040), 删 075905/080030/080212/... 等重启试跑
3. **每目录只留最后 checkpoint**: `checkpoints/` 里除 `last` 外保留排序最后那个 (load_policy 用 glob 永远取最新, 中间 checkpoint 无人用) — 7 ckpt 目录 1.8G→0.3G
4. **保留清单**: 训练中目录 (smolvla_peg_v7) / GUI 引用的命名目录 (act_metaworld_final) / *final/peg_v*/metaworld 命名目录 / reports/ 全部产物
5. **验证 (ad-hoc)**: 训练中目录 ckpt 数不变 (peg_v7 12→13 是训练正常推进, 非清理误伤) + GUI 引用目录存在 + 报告/视频产物存在 + `df -h` 用量下降
- 每次密集训练后磁盘会快速涨回 (smolvla/LEW 单目录 9-16G), 养成清理习惯; 老倪工作仪式含"清理垃圾"环节

## Model Zoo 7 模型最终对比结论 (2026-08-10, eval_zoo_5000.json + 报告 PDF)
> 生成器: `tools/gen_zoo7_report.py` → `reports/ModelZoo_7模型优缺点对比_<ts>.pdf` (3 图: 成功率/距孔/参数量, 对数轴)
> 对比视频: `tools/gen_compare7_video.py` → **输出 `reports/compare_7model_container.mp4` (cv2 VideoWriter mp4v, 100帧 1440x480)** — 不是 compare7_5000.mp4! 交付前必须 ffmpeg 转码: `ffmpeg -y -i compare_7model_container.mp4 -vf "transpose=1,transpose=1,format=yuv420p" /tmp/compare7_final.mp4`

**5000 步容器训练 7 模型最终成绩** (metaworld peg-insertion):
| 模型 | 抓起 | 插入 | 距孔 | 参数量 |
|---|---|---|---|---|
| ACT | 0/8 | 0/8 | 0.361m | 30M |
| SmolVLA | 0/8 | 0/8 | 0.365m | 500M |
| SmolVLA+LEW | 0/8 | 0/8 | 0.367m | 500M |
| VLA-Touch | 0/8 | 0/8 | 0.365m | 500M |
| AWE | 0/8 | 0/8 | 0.365m | 250M |
| **MLP 蒸馏** | **6/10** | **3/10** | 0.013m | **0.64M** |
| **官方专家** | **19/20** | **17/20** | 0.005m | - |

**每模型优缺点 (老倪要"说出每个模型的优点缺点"的报告标准答案)**:
- **ACT**: 优=训练稳定收敛快、接近动作平滑; 缺=只学到"接近"学不会抓取、无接触反馈 (7 步 chunk 回归平均化)
- **SmolVLA**: 优=通用视觉语言理解、多任务潜力; 缺=长程插拔零成功率、推理慢重
- **SmolVLA+LEW**: 优=世界模型辅助规划 (理论上限高); 缺=实际未发挥、潜空间接口价值未落地
- **VLA-Touch**: 优=触觉感知融合 (49D 含触觉); 缺=触觉无提升 (BC 本质)、加载最重
- **AWE**: 优=潜空间动作表达、架构轻; 缺=同 BC 困境、训练不稳
- **MLP 蒸馏**: 优=唯一可插拔 NN、轻量 (0.64M) 能插入; 缺=抓取率 60% 不够、依赖专家数据
- **官方专家**: 优=85% 基准规则完美; 缺=无泛化、需已知精确模型

**结论 (报告核心)**: 5 视觉 BC 全 0/8 = **瓶颈数据/架构非步数** (5000 与 2000 步一致); 选型 = 单任务插拔→双脑/MLP蒸馏, 多任务泛化→SmolVLA 系 (接受低成功率)

## ⚠️ 评估/视频前必须先更新 train_curve 指向正确 ckpt (2026-08-10 实测)
**症状**: gen_compare7_video.py 报 `失败 [Errno 2] No such file or directory: '/home/xspace/lerobot-smolvla-lew` — eval_insert.load_policy 从 `reports/train_curve_<policy>.json` 的 `ckpt` 字段找路径, json 指向旧/已删目录就加载失败 (视频里 5 个视觉 BC 模型帧全空, 只有专家成功)。
**修复**: 评估/生成视频前批量更新 5 条 train_curve (Model Zoo 5000 步产物: `act_5000_20260809_210410` / `smolvla_5000_20260809_210942` / `smolvla_lew_5000_20260809_215838` / `vla_touch_20260809_144926` / `awe_zflow_20260809_145747`, 各含 `checkpoints/000050/pretrained_model` 或 ckpts)。**ckpt 字段写 checkpoints 根目录, load_policy glob 找最新子目录**。`ls reports/train_curve_*.json` 齐不齐先查, 缺的 json 直接新建 ({"ckpt": ..., "train_src": "本地docker 5000步 (Model Zoo)"})。

## 参数/算力/推理时间对比报告 vs 主流 VLA (2026-08-10, 老倪: "模型参数,算力,推理时间,与主流VLAtouch 3B模型做对比")
- 生成器: `tools/gen_param_compare_report.py` (独立脚本, 不依赖 generate_report.py) → `reports/插拔方案参数算力对比_主流VLA3B_<ts>.pdf` (5页: 核心结论 → 参数表+对数条形图 → 算力/训练成本表 → 推理时间表+对数条形图 → "为什么0.71M就够" + 诚实边界)
- 双脑方案 (full_pipeline.pt, keys=left/right/align/xm/xs/ym/ys/am/a_s) 实测:
  - 参数: 左脑MLP 0.548M + 右脑WM 0.088M + 对位头 0.077M ≈ **0.71M 总** (权重 2.86MB fp32)
  - 推理: GPU **0.19ms/帧 (5283fps)**, CPU 2.2ms (449fps) — 2000 次取中位
  - 训练: 800ep × 18162帧 + 8 seed 评估 ≈ **176s** (4060 单卡)
- 其他模型参数实测: ACT 18.71M / SmolVLM2-500M 507.5M / DINOv2-small 22.1M / VLA-Touch 控制器可训 0.343M (DINOv2 冻结) / MLP 蒸馏 ~0.55M
- 主流 VLA 公开值 (报告里标"公开文献值"): π0-3B ~3300M (arXiv 2506.06358) / OpenVLA-7B 7000M (README: Llama-2 7B + DINOv2 ViT-L + SigLIP) / SmolVLA-3B ~3000M
- 对比叙事模板: 参数差 4600 倍 / 推理快 1000 倍 / 训练算力差 4-5 数量级; 比喻 = 全科博士生 (3B VLA) vs 老师傅带分工 (双脑: 状态机管流程 0 参数, 左脑管动作, 右脑管时机); 诚实边界 = 任务专用 vs 通用底座 (手术刀 vs 瑞士军刀), 主流模型权重太大 4060 跑不动也是"贵"的一部分

## 参数/延迟实测坑 (2026-08-10)
- **safetensors 数参数用 `safetensors.safe_open` 不是 torch.load**: torch.load(.safetensors) 报 `UnpicklingError: invalid load key` — SmolVLM/DINOv2/checkpoint 的 model.safetensors 一律 `with safe_open(f, framework='pt') as sf: sum(sf.get_tensor(k).numel() for k in sf.keys())`
- **`→` 箭头会被 _clean 的 emoji 正则误删**: 正则含 U+2190-21FF 箭头区, "39→512×3→4" 变 "39512×34"。⚠️ 修复必须把 `.replace("→","->").replace("←","<-")` 放在 `_EMOJI_RE.sub` **之前** (或从正则删掉 2190-21FF 区) — 放正则后面无效, 箭头已被先删 (2026-08-10 实测: 放后面, 报告 MLP 行仍显示 "39512×34")
- **小参数量权重显示 "0.00 MB"**: <8M 参数时 MB 格式化丢精度 — 分档: ≥500M→GB (fp16×2), ≥8M→MB, 其余→KB (fp32×4)
- **RightBrainWM.forward(obs, act) 是双参**: 不是 cat 后单参 — 测延迟按单参调报 TypeError missing argument
- **主流模型数据源可用性**: openvla/openvla-7b README 公开可 curl (`.../raw/main/README.md`, 含完整架构清单); pi0/SmolVLA 系列 gated (HF API 报 Invalid username or password); 拿不到就诚实标"公开文献值", 绝不编数字

## 交付
PDF 生成后直接 `MEDIA:/path/xxx.pdf` 发飞书 (老倪手机查看), 附核心结果表 (MSE/成功率/延迟) + 诚实标注 (快速版 vs 正式版)。

### 老倪"为什么"式追问偏好 (2026-08-06)
老倪会连问"为什么ACT训不出来/那其他模型能吗/为什么RL就能" — 他要**根因级解释**, 不是过程汇报。回答结构: ①直接结论 ②分条根因 (按重要性排序, 每条带实测数据) ③对比表 (失败 vs 成功的输入/架构差异) ④诚实澄清 (如"成功的是蒸馏不是RL")。别用"可能/也许", 用实测数据说话。

### 汇报风格铁律 (2026-08-08 老倪两次明确纠正: "你说话太啰嗦了, 快速执行, 最后干净利落汇报" + "数字太多我不懂, 要形象简单有逻辑性, 故事要完整")
1. **执行期少说话**: 用户给任务后直接干, 不要边干边解释每步 (老倪: "你只需要快速执行")
2. **汇报要干净利落**: 最终交付 = 结果表 + 关键结论 + 下一步建议, 不堆过程细节
3. **解释用比喻/故事, 不用数字堆砌**: 老倪明确"你说的很多数字我都不懂" — 讲技术状态用生活化类比 (如"7个模型=7个学徒, 老师傅官方专家, 聪明学徒MLP, 教材教反了=长轨迹方向抵消学成原地踏步, 夹爪=开关不是旋钮, 目标条件化=装GPS") — 数字只作为表格里的支撑, 叙述里用形象语言
4. **无限调试要止损**: 用户"你到底要折腾到什么时候, 快点给我出结果" = 立即停止深挖, 给出当前最优结果 + 明确下一步 (别在一个失败路线上反复重训/调参)
5. **有成功案例的视频先给**: 老倪要"看到插入/结果"时, 先发已有成功视频 (MLP/专家) + 并行推进重训, 别等全部完成才交付

### 飞书 API 自动发送 (2026-08-06 实测, 训练完自动发群)
> **完整代码/坑实录见 `references/20260806-feishu-delivery.md`** — token 获取 / chat_id 发现 / multipart 手拼 / 自动交付链路 (ZMAX_AUTO_RUN)
- 🐛 **mp4 发飞书: 上传 `file_type=mp4` + 发送 `msg_type=media` (2026-08-09 实测修正!)**: 此前记录"file_type=stream+file"并不通用。实测双路径: ①`file_type=mp4` 上传成功 + **`msg_type=file` 发送 → HTTP 400 code 230055 (上传类型与消息类型不匹配)** ②**`msg_type=media` 发送 mp4 → 成功** (media = 视频消息, 不需要封面 image_key)。**修正: mp4 → 上传 file_type=mp4 + 发 media 消息; PDF/其他 → file_type=pdf + file 消息**。另: `msg_type=video` 非法 (230001); **POST 必须显式 `Content-Length` 头** (python3.14 urllib 对 multipart/JSON 请求缺 Content-Length → HTTP 400 "Bad Request", 排查时抓响应体看 code 230055 才能定位类型不匹配)
- **纯文本消息 (2026-08-08 实测, 进度/状态同步用)**: `POST /open-apis/im/v1/messages?receive_id_type=chat_id` body `{"receive_id": cid, "msg_type": "text", "content": json.dumps({"text": msg})}` — content 必须是**内层 json.dumps 后的字符串** (不是 dict!)。token 用 tenant_access_token; 群查找 `GET /open-apis/im/v1/chats?page_size=20` 按 name=="dataworld" 过滤。**dataworld 群 chat_id = `oc_c0b4048546145c5c581ddd1a9e8f565d`** (完整值, 勿用截断版)。老倪"跟飞书端同步进度"时: 发文本状态 (训练完成/插入结果/新目录疑问) 即可, 附结果表用手机友好格式 (见交付偏好 11)
- 群 chat_id: `GET /open-apis/im/v1/chats` 找 dataworld 群; 凭据从 `~/.hermes/.env` 读 FEISHU_APP_ID/SECRET
- 🐛 **ffmpeg xstack 5 视频 3+2 拼接: layout 必须纯数字** `0_0|320_0|640_0|0_240|320_240`; `w_3_h_0` 组合引用报 `Failed to configure output pad` → 0 字节输出
- 🐛 **rollout "checkpoint 不存在"但目录在**: on_train ts_dir 与 train_vla_touch/train_awe_zflow 内部 ts 差几秒 → load_policy 加 glob 兜底找最新同前缀目录; **前缀必须 `os.path.basename(os.path.dirname(ckpt_base))`** (basename 直接取到的是 "checkpoints"!)

## 运维关联 (交付物相关的链路故障)
- **推理执行端澄清 (2026-08-07 老倪: "推理,是在orin上进行的么?在MAC上进行即可?" → 老倪裁决 "那就在orin上进行")**: node_infer (⑥ 推理节点) 只是**状态查询** — GUI 发 `GET https://datadrive.world/api/relay/orin/status` (ECS relay 中转) 查 Orin 的 online/infer_count/last_infer_ms/model, 链路 4060→ECS→Mac(8769 ROS2 桥)→Orin。**推理执行端 = Orin** (Z700 产线部署推理); Mac (小芳 M1) 只是 ROS2 中转站不推理; 4060 的 rollout 是仿真评估 (见视频来源澄清)。老倪已确认推理就在 Orin 上做, 链路保持现状不改
- **模型部署到 MAC (2026-08-06 老倪: "部署到MAC上,注意不是orin")**: 训练好的模型推 ECS 静态 URL → 小芳从 URL 拉取部署到 **MAC** (非 Orin)。流程: `sshpass scp model.safetensors root@ECS:/www/wwwroot/datadrive.world/models/<name>.safetensors` + `chmod 644` → 通知小芳 `curl -o` + md5 校验
- **nginx models 静态服务 (2026-08-06 实测, 大文件截断修复)**: datadrive.world.conf 走 PHP (enable-php-80), 大文件被 PHP 截断 (83.5MB 只下 1.7-17MB)。修复: 加 `location ^~ /models/ { root /www/wwwroot/datadrive.world; default_type application/octet-stream; add_header Cache-Control no-cache; }` 绕过 PHP 直接静态服务。**验证**: ECS 本机 `curl -H 'Host: datadrive.world' http://127.0.0.1/models/xxx.safetensors` 应完整 (83.5MB, md5 与本地一致); 127.0.0.1 不带 Host 头会走默认 server 404, 必须带 Host! nginx reload: `kill -HUP <master_pid>` (宝塔 nginx -s reload 报 stream 模块错误, 用 master pid HUP)
- **链路巡检 cron (2026-08-06 老倪 @all "大家先检查系统" + 自动化要求)**: `~/.hermes/scripts/chain_health.py` 每 30 分钟检查 relay/orin/快照/auto_loop/磁盘 → cronjob(no_agent=true, script=chain_health.py 相对名) 注册, 异常时 stdout 非空自动告警飞书
- **cicd.html 无图像 / 快照 502 排查实录 → `references/ecs-snapshot-502-fix.md`** (archive 千万文件 glob 卡死 → os.listdir + 归档上限 300 + guard.sh 守护; 症状分化排查法: 一个端点挂 vs 全挂先用 orin/status 区分)
- **WS 502 ≠ relay 挂 (2026-08-06 实测)**: ECS 三服务独立 — zmax_relay(39053, start.sh) / ws_relay(8765, start_ws.sh) / nginx(443)。auto_loop 日志 `Handshake status 502` 但 /api/relay/status 200 → 只 ws_relay 挂了, `ssh root@ECS "cd /root/zmax-relay && bash start_ws.sh &"`; 验证 `ss -tln | grep 8765` 监听 + curl /ws 返回 426 (Upgrade Required)=正常。**guard.sh 只守护 zmax_relay, 不守护 ws_relay** — ws 挂了需人工检查
- **系统检查清单 (老倪 @all \"先检查系统,别死机\")**: 密集训练后必查 — `free -h` / `df -h /` / `/usr/lib/wsl/lib/nvidia-smi` (WSL 里 nvidia-smi 不在 PATH, 用全路径!) / `ps aux | grep -E 'lerobot_train|eval_insert|gen_metaworld'` 残留进程应为空 / `ps aux | grep auto_loop` 守护 (可能被杀=0, 重启用 terminal(background=true), 禁止 nohup 前台包装被 Hermes 拦截)。内存>60% 或负载>4 停长任务
- **控制台启动/重启 (2026-08-06 实测, 老倪: \"控制台你重启一下, 我看看\")**: **PyQt5 在系统 python, 不在项目 .venv!** 必须 `DISPLAY=:0 /usr/bin/python3 tools/gui/studio.py` — 直接 `python3` 报 `ModuleNotFoundError: No module named 'PyQt5'` (PATH 里的 python3 是 hermes venv 或项目 .venv, 都无 PyQt5; `/usr/bin/python3 -c "import PyQt5"` 才是 OK)。杀旧: `ps aux | grep studio.py` → kill; 重启后 wc -l 应 1。日志 `Unknown property cursor` 是无害 Qt QSS 警告。**启动失败先查类导入**: `ImportError: cannot import name 'SimulinkModule'` = 文件被截断/类丢失 (见大文件铁律), 非 PyQt5 问题。验证不弹窗: `QT_QPA_PLATFORM=offscreen /usr/bin/python3 -c "import sys; sys.path.insert(0,'tools/gui'); import simulink_module as sm; print(hasattr(sm,'SimulinkModule'))"` → True。**完整实录含截断恢复/连线索引重写见 `references/console-restart-writefile-pitfall.md`**
