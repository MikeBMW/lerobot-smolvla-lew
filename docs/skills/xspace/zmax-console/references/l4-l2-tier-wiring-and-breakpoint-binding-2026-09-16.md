# L4 档 L2 兼容接线 + 引擎断点绑定 (2026-09-16 实测)

> 老倪原话: 「运行 L4 时 YOLO 未启动呢? L2 功能应该和 L4 功能兼容, 运行 L4 的时候 L2 也可以运行; 也要连线」
> 以及后续: 「YOLO 检测的模型接入 L4 怎么还没改好? 这段 forward 在 L4 运行还是进不了断点」

## 一、两个真根因 (都定位到行)

### ① 前馈 MLP 真身永不进入 (`SS_USE_MLP` 没设)
`tools/gui/state_space_sim_real.py:399` (装配期)
```python
if os.environ.get("SS_USE_MLP") == "1": print("🧠 SS_USE_MLP=1: 分层伺服 …")
else: self.accel.forward = self.accel.analytic_forward   # 实例属性遮蔽类方法
```
→ `src/lerobot/policies/left_right/state_space/parallel.py:143` 的 `def forward` **一次不进**。
实测 (32 步, 同 seed): `实例覆盖=True · 真身进入 0 次 · n_mlp=0 · **n_guard=0**`
⇒ **不是 D_GUARD(0.25)/DOMAIN_SIGMA(4.0) 域判定挡的** (域判定根本没被执行); 臂B (`SS_USE_MLP=1`):
`真身 32/32 · n_mlp=32 · n_guard=0`, 域判定真值 d_guard 0.131~0.178、max|xn| 1.583 **全在域内**。
另有两条旁路: 插入段硬调 `analytic_forward` (`:2584`, 分层伺服设计) · L4 直驱用模型动作 env.step, u_ff 只取阶段标签/gripper/skill_ctx。

### ② YOLO 从未启动 (`vision` 只给 L3 档)
`tools/gui/simulink_module.py:11471` (装配引擎时)
```python
vision=(str(_cap or "").upper() == "L3") and (not _model_exec)
```
→ L4 恒 `vision=False` → 引擎日志分支 `state_space_sim_real.py:3503`
`if _v.get("shot") ... else "YOLO 未启动"` 恒取后者 (shot 只在本帧真跑 detect_3d 时累加)。

### ③ 断点绑定 (最隐蔽, 与 ①② 独立)
引擎 `state_space_sim_real.py:136` 原来:
```python
spec = importlib.util.spec_from_file_location(f"ss_real.{name[:-3]}", path)
```
**debugpy 对 spec_from_file_location 加载的模块不绑定断点** → 函数真执行、日志有输出, VSCode 就是不停。
已改:
```python
_m = types.ModuleType(mod_name); _m.__file__ = os.path.abspath(path); _m.__name__ = mod_name
sys.modules[mod_name] = _m
exec(compile(src, _m.__file__, "exec"), _m.__dict__)      # 失败才退回 spec (不静默降级)
```

## 二、接线 (档位内生效, 全局默认不动)

`simulink_module.py` L4 装配分支 (在 `sim = RealStateSpaceSim(...)` 之前):
```python
_l4_cap = str(_cap or "").upper().startswith("L4")
_l2_compat = bool(_l4_cap and (not _demo_cap)
                  and os.environ.get("SS_L4_L2_COMPAT", "1") != "0")   # 默认开
if _l2_compat: os.environ["SS_USE_MLP"] = "1"      # + vision=True (见下)
else:          os.environ.pop("SS_USE_MLP", None)  # 非 L4/演示档: 原状 = 零回退

vision=((cap == "L3" and not _model_exec)
        or (cap.startswith("L4") and (not _model_exec) and _l2_compat)),  vision_every=1
```
为什么用 `not _demo_cap`: **L4 纯演示档走 L4Demo 独立链** (自己的 env/控制器,
`tools/gen_l4_demo_video.py`), 链上**没有 FeedforwardAccelerator** → 在演示档设什么都没用, 断点也永不命中。
只有勾「🤖 L4 用 INTACT 节点执行」或「🧠 模型执行」才走引擎路径。

## 三、同口径 A/B (gui-venv311 · seed104 · 120 步 · cap=l4 · 每臂独立进程)

| 判据 | 臂A (现状) | 臂B (L2 兼容) |
|---|---|---|
| 装配期覆盖 forward | True | False |
| MLP 真身进入 | 0 | **120/120** |
| n_guard | 0 | 0 (域内无兜底) |
| YOLO 出帧/检出 | 0 / 0 ("YOLO 未启动") | **120 / 240 (100%)** |
| 最小距离 | 0.13mm | 2.77mm |
| 终点距离 | **0.42mm** | **6.82mm (16×)** |
| 墙钟 | 3.3s | 6.9s (2.1×) |

结论: **接线成功可验证, 但精度回退** (vision 后 YOLO 检测值替换 R0 真值 + MLP 在 seed104 分布边缘)。
复现: `./gui-venv311/bin/python tools/ab_l4_l2_compat.py A 120` / `SS_USE_MLP=1 … B 120`

⚠️ **解释器必须 gui-venv311**: `ultralytics` 只装在那里 (8.4.126); `~/lerobot-venv` 没有 →
臂B 会 `ModuleNotFoundError: No module named 'ultralytics'` (第一次 A/B 就是这样挂的)。
GUI 本身跑 gui-venv311, 所以 L3 档的 vision 一直没事。

## 四、画布连线 (flows/state_space_obs.json 文本级插入)

新增 2 条 (节点 77 不变 · 连线 95→97 · 旧连线逐字段 0 变化):
- `📡 传感器融合 → ssintact` `t_port=in2` ↩ L2 融合状态 39D (YOLO→2D→3D→融合)
- `⚡ 前馈加速器 → ssintact` `t_port=in3` ↩ L2 前馈 MLP u_ff
- `ssintact` 的 desc 补「三路入线口径」(in1 数据源 / in2 L2 感知 / in3 L2 执行) = 自解释

**零回退佐证**: `tools/verify_l4_zero_regression.py` → 档位归属无变化 · L2/L3/L4 执行集 55/60/77 逐项不变 · 旧连线 0 丢失。
**几何代价 (同工具改前/改后, 必须两边都跑)**: 反向 2→4 (新增 2 条 + 均标 ↩) · 方框重叠 0→0 ·
穿框 44→45 · 交叉 145→161 (+16)。根因: L2 行在画布右侧 (前馈 x≈3826), L4 行在左 (x=387) → 天生反向,
与既有 SK04-08→执行器 5 条同源; 结构性修法 = 重排 L2 行位置。

## 五、想看到断点命中, 三条必须同时满足
1. **L4 档 + 走引擎路径** (勾「🤖INTACT 节点执行」/「🧠模型执行」);
2. **VSCode F5 启动** —— 直接 `python studio.py` = 非调试模式 (标题带 ⚠️), 断点不生效;
3. **改码后重启 GUI**, 且 L4 开跑前日志须出现 `🧠 SS_USE_MLP=1: 分层伺服` + `🧩 L4 档 · L2 兼容已开`。
断点请设在 `def forward` 的**第一行可执行语句** (`obs = np.asarray(obs, dtype=float)`), 别设 def/docstring 行。

## 六、验证脚本 (可复跑)
- `tools/ab_l4_l2_compat.py <A|B> [steps]` — L2 兼容同口径 A/B (每臂独立进程)
- 断点绑定自检 (一次性): 加载后遍历模块内类的类方法, 断言 `__code__.co_filename` ∈ 六层目录;
  再跑 20 步断言 `n_mlp>0`。本次结果: 五文件 0 例外 · `forward 指向 FeedforwardAccelerator.forward @ parallel.py · n_mlp=20 · n_guard=0`

版本: 接线 v5.6.9 (commit 1dace217) · 默认开 + exec 加载修复 v5.6.10 (commit cd04634d)
设计文档: `docs/design/zmax_l4_l2_compat_wiring.md`
