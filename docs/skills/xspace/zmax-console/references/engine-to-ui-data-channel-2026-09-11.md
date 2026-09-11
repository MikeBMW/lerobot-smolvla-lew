# 引擎设置 ≠ UI 可见 / L4 档看得到干扰 (2026-09-11 当日终态)

> 补充并**更正** `references/model-exec-toggle-and-animation-source-2026-09-11.md`
> (那份写于当日中途, 有两处已被后续实测推翻 —— 见文末"更正清单")。
> 起因: 老倪**连问三轮**同一件事 —— "3D 视图打开的窗口动画一直是老样子, 你说模型更新了怎么没区别?"
> → "L4 档怎么没有拔出光模块?" → "没看到 L4 的光模块旋转角度, 问题到底在哪里?"
> 连修六处才成立。**每轮我都以为改完了, 每轮都还差一层** —— 这个"差一层"的形态本身就是最该记的。

---

## 🔴 一、最核心的一条: 引擎设置 ≠ UI 可见 (三层数据链)

**症状**: 引擎里明明设了 `shell_yaw = π/2`, 运行日志也确认了, **3D 画面就是不动**。

三层依次叠加, 少一层都白改:

```
第1层  引擎把视觉表达**显式关掉**了
       _inject_peg_jitter(): _shell90 = False   ← 物理干扰照做(±3.5cm/±15°), 但"看得见的转台"被关
第2层  引擎设了, 但**没写进 tr**
       self._shell_yaw / self._jitter_meta 只是引擎内部状态; GUI 拿到的是 tr, 内部状态它看不到
第3层  UI 只认它自己消费的**具体字段**
       ss_dreamview 画转台只读 meta.demo_geom["turntable"] + tr["tt_yaw"],
       而这两个字段原先**只有 L4Demo 那条控制器路径**提供 → 引擎路径根本没有 → 不画
```

**通用铁律(任何"改引擎但界面没变化"都适用)**:
```
正确顺序: ①先 grep UI 到底消费哪些字段 (ss_dreamview / data_world / 画布节点)
          ②把数据补齐到那几个字段 (tr 列 + tr["_meta"])
          ③验证字段真的非空 + 界面真的画出来
错误顺序: 改引擎内部状态 → 宣布修好 → 等用户说"还是没变"
```

本次补的两样 (**3D 侧零改动, 只补数据**):
```python
# 引擎 _inject_peg_jitter 内
self._l4_tt = {"turntable": {"pos": [光模块xy], "r": 0.075}}
self._l4_tt_yaw = 90.0 if _shell90 else degrees(_yaw)
# 每帧
tr["tt_yaw"].append(float(getattr(self, "_l4_tt_yaw", 0.0)))
# 收尾 meta
tr["_meta"]["demo_geom"] = getattr(self, "_l4_tt", None) or {}
tr["_meta"]["jitter"]    = dict(self._jitter_meta) if self._jitter_meta else None
```
**实测验收**: `tr["tt_yaw"]` 862 帧 · 首值 90.0° + `meta.demo_geom` 有 turntable + 862 步完成。

**关于开 `_shell90=True` 的安全性**: `shell_yaw` 是**纯视觉装饰关节**(注释明确: 不影响抓取动力学;
peg 物理本体仍只转 ±15° 可成功域) → 开启 = 看得见干扰 + 任务照样能成。
但**必须实测确认任务仍完成**, 别只信注释。

---

## 🔴 二、更正: L4 档当日终态 (推翻前一份 reference)

前一份写 "L4 档 → demo_l4=True → 完全委托 L4Demo" 和 "开关默认开 (`setChecked(True)`)"。**两条都已推翻**:

**为什么推翻**:
- `L4Demo` = 独立控制器, 轨迹写死 → **每次跑必然一样** (这就是"动画老样子"的根因);
- 它还**没有引擎的拔出/AOI 全链能力** → 用户问"L4 怎么没有拔出光模块"。

**终态配置** (`simulink_module.py` 运行线程 / `ss_dreamview.py` 开关):
```python
_demo_cap   = False                                   # L4 不再默认委托 L4Demo (代码保留可显式启用)
_model_exec = bool(getattr(self, "_model_exec", False))   # 默认**不勾**
if _model_exec:
    os.environ["SS_L3"] = "1"; _demo_cap = False
else:
    os.environ.pop("SS_L3", None)
sim = RealStateSpaceSim(seed=104,
        # L3 档保持 R1 视觉(老倪明确: "L3 档是正常的, 不用改");
        # L4 改走引擎链路后用 R0 真值 — R1 每帧 YOLO 要 5-9 分钟/轮, 太慢看不清完整全链
        vision=(str(_cap or "").upper() == "L3") and (not _model_exec),
        mode=getattr(self, "_l3_mode", None),         # L4 档 → "full" (13 段, 含拔出/AOI)
        demo_l4=_demo_cap, ...)
sim.run(cap=_cap)      # cap 触发 _jitter_on / 预算×2 / 自主恢复
```
⇒ **L4 档 = 引擎真链路 + 干扰注入 + mode=full(插→拔→AOI检测→放回) + R0 真值**;
干扰每轮不同 → 动画不再"老样子"; 且能看到完整拔出/AOI。
**「🧠 模型执行」= 可选开关, 默认不勾。**

---

## 🔴 三、为什么"模型执行"默认只能是**不勾** (实测因果, 不是偏好)

同一个 L4 档, 三种模式各跑一次 (seed104 · full · cap=L4):

| 模式 | L3 调用 | 完成 | 结果 |
|---|---|---|---|
| L4Demo 固定演示 | — | — | 轨迹写死, 每次一样 ← "老样子"的根因 |
| 引擎 + **模型接管** | **1200 次**(模型真在跑) | **False** | **卡在插入之前 → 走不到拔出** |
| 引擎 + **解析链** | 0 | **True** | 862 步 · 拔出164 · AOI检测135 · **AOI PASS** |

**根因**: 模型是在**无干扰的固定布局**上训练的; L4 的干扰(光模块移位 ±3.5cm / 转向 ±15°)
让它面对**没见过的布局** → 动作失效 → 卡死。
⇒ **训练数据覆盖问题, 不是接入代码 bug**。要让模型在干扰下也可靠 → 得在**带干扰的数据**上做 DAgger 迭代。

**通用教训**: 模型"能跑通"的结论**必须带场景条件**。同一模型换一个被扰动过的初始布局就崩,
把它写成"模型不行"或"接入有 bug"都是错的 —— 先问"训练数据覆盖过这个场景吗"。

---

## 四、Qt 侧两个静默坑 (各踩一次)

1. **`setChecked()` 写在 `connect()` 之前不触发信号** → 默认值传不到消费方。
   界面显示已勾选, 行为却按旧默认跑。修法 = connect 后**显式调一次**处理函数;
   消费方 `getattr(..., <默认>)` 的默认值也要与 UI 对齐。
   **加/改开关 = 创建 + 连接 + addWidget + 默认同步 四件事**; 验证必须覆盖"默认态直接运行"。
2. **`pkill -f "studio.py"` 会打死执行它的 shell 自己** (命令行含目标字符串 → 自匹配 → exit -15,
   后续命令全不执行)。正解 = 方括号技巧 `grep "[s]tudio\.py"`;
   更稳: `ps -eo pid,args | grep "[s]tudio\.py" | awk '{print $1}' | xargs -r kill`。

---

## 五、启动路径 (实测)

`studio.py` 在 **`tools/gui/`** 下, **仓库根没有它**:
`cd <repo> && gui-venv311/bin/python studio.py` → `can't open file '<repo>/studio.py': [Errno 2]`, exit 2,
进程 ~30s 内退出 —— 症状像"GUI 崩了", 实为路径错。正确启动:

```bash
bash <repo>/tools/gui/launch_studio.sh     # 官方: 硬编码 venv/GUI_DIR + pgrep 防重入 + 日志 /tmp/studio_launch.log
# 或
cd <repo>/tools/gui && DISPLAY=:0 ../gui-venv311/bin/python studio.py
```
**启动成功必须给证据**: `ps -eo pid,lstart,args | grep "[s]tudio\.py"` 有进程 + 启动时间对得上,
再 `process(action='poll')` 确认没退。只报"已重启"不算证据。

---

## 六、元教训 (比任何单条坑都重要)

用户**连问三轮同一个问题**(怎么没区别), 因为前两轮我都在**只验证自己改的那一层**就宣布修好:
```
第1轮: 改 _shell90 → 验证"引擎里是 True" ✓ → 用户看不到 (数据没出路)
第2轮: 写进 tr    → 验证"tr 里有值"   ✓ → 用户看不到 (UI 不读那个字段)
第3轮: 才 grep UI 到底读什么字段, 补齐后才成立
```
⇒ **宣布"修好了"之前必须验证到用户实际看到的那一层**:
`引擎设置 → 写进 UI 消费的数据源 → UI 真的读它 → 界面真的画出来`, 四环全过才算修好。
层层"我这边验证通过"而用户看不到, 就是没修好 —— 这时候该做的是**往上追一层**, 不是换个参数再试。

---

## 更正清单 (相对 `model-exec-toggle-and-animation-source-2026-09-11.md`)

| 前一份的写法 | 当日终态 |
|---|---|
| `btn_model_w.setChecked(True)` / "默认开 (点开就要看出区别)" | **默认不勾** (`setChecked(False)` + `_on_model_exec(False)`) |
| `_model_exec = bool(getattr(self, "_model_exec", True))` | **默认 False** |
| `_demo_cap = (cap == "L4")` → L4 委托 L4Demo | **`_demo_cap = False`** → L4 走引擎真链路 |
| `vision=(not _demo_cap) and (not _model_exec)` | **`vision=(cap == "L3") and (not _model_exec)`** |
| "连修四处才让动画不一样" | 实际**六处** (加: `_shell90` + tr 数据字段两组) |
