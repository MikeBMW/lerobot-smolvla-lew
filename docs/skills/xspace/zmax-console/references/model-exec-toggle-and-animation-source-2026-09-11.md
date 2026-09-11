# 3D 视图动画"改了却没区别" + 模型执行开关 (2026-09-11 实测)

> 本文补充 SKILL.md 的「陷阱 / 3D 视图↔程序执行状态映射 / 修改 GUI 代码后必须重启」几节。
> 起因: 老倪反复追问 **"simulink 画布 → 状态空间按钮右侧「3D视图」打开的窗口动画, 一直是老样子,
> 你说模型更新了, 怎么没有区别?"** —— 连修四处才让"动画不一样"成为可能。

---

## 一、三问定位法 (任何"改了但界面没变化"先用这三问)

1. **这段动画/数据是谁产生的?** (哪个控制器 · 哪个档位 · 哪条代码路径)
2. **我改的文件在不在那条路径上?** (调用点核查, 不是"模块存在")
3. **进程是否重启过?** (GUI 改码必须重启才加载; 也要确认启动起来的是新版)

三问任一答错, 就会出现"改了很多、用户看不出效果"。本会话正是**三问全踩**:
动画来自另一个控制器(问1) + 改的是引擎而非该控制器(问2) + 开关默认值没生效(问3)。

---

## 二、3D 视图窗口的动画从哪来 (关键事实)

```
simulink 画布 ▶运行  →  按当前档位切分:
  · L2/L3 档 → 引擎 RealStateSpaceSim 真跑 → 轨迹喂 3D 窗口 (逐帧 set_frame)
  · L4 档   → simulink_module 里 `_demo_cap = (cap == "L4")` → `demo_l4=True`
              → 引擎 run() **完全委托** `gen_l4_demo_video.L4Demo` 独立控制器
                (直接 import metaworld, 轨迹写死, 90° 转台演示)
```
**`L4Demo` 与引擎零共享** — 它不用六层控制器、不用 `gripper_cmd`、不用流形、不用模型
(grep 命中数 = 0)。所以 **L4 档下无论换什么模型、修什么引擎 bug, 动画都一模一样** ——
用户观感即"模型没更新 / 还是老样子"。

**排查判据**: 若用户报"3D 动画不变", 先看当前档位是不是 L4; 是 L4 → 动画不经过引擎,
改引擎永远看不到效果。

---

## 三、落地: 「🧠 模型执行」开关 (L4 档专用)

3D 视图左侧「🕹 3D 世界操作」面板 (`ss_dreamview.py`, `btn_top_w` 之后) 新增:

```python
self.btn_model_w = QPushButton("🧠 模型执行")
self.btn_model_w.setCheckable(True)
self.btn_model_w.setChecked(True)                 # 默认开 (老倪: 点开就要看出区别)
self.btn_model_w.toggled.connect(self._on_model_exec)
pl.addWidget(self.btn_model_w)
self._on_model_exec(True)                          # ⚠️ setChecked 在 connect 前不触发信号 → 主动同步
```

`_on_model_exec(on)` → `self.module._model_exec = bool(on)`;
`simulink_module` 运行线程消费:

```python
_model_exec = bool(getattr(self, "_model_exec", True))     # 默认与 UI 默认一致
if _model_exec:
    os.environ["SS_L3"] = "1"; _demo_cap = False           # 走引擎 + L3 模型接管
else:
    os.environ.pop("SS_L3", None)                          # 原 L4Demo 固定演示
sim = RealStateSpaceSim(seed=104,
        vision=(not _demo_cap) and (not _model_exec),      # ⚠️ 模型执行必须 R0 真值
        demo_l4=_demo_cap, ...)
```

- **勾上 = 引擎 + L3 模型接管 + 二态意图层**; **取消 = 原 L4Demo 演示** → 同档位当场对比。
- **L3 档一行不动** (老倪明确: "L3 档位是正常的, 不用改")。
- ⚠️ **勾选时必须 `vision=False` (R0)**: 否则 `not _demo_cap` 会把它带到 R1 视觉,
  多引入一层变量 → 与验证口径不一致, 成绩无法归因。
- 引擎启动会打印实际加载的 ckpt 路径 → 运行日志可核对"跑的到底是哪个模型"。

---

## 四、Qt 侧两个静默坑 (本会话各踩一次)

1. **`setChecked()` 写在 `connect()` 之前不触发信号** → 默认值传不到消费方。
   界面显示已勾选, 行为却按旧默认跑。修法 = 放 connect 之后, 或 connect 后**显式调一次**处理函数;
   消费方 `getattr(..., True)` 默认值也要对齐。**加/改开关 = 创建 + 连接 + addWidget + 默认同步 四件事**。
   验证必须覆盖"默认态直接运行", 不能只测"手动点击后"。
2. **`pkill -f "studio.py"` 会打死执行它的 shell 自己** (命令行含目标字符串 → 自匹配 → exit -15,
   后续命令全不执行)。正解 = 方括号技巧 `pkill -f "[s]tudio.py"` / `grep "[s]tudio\.py"`。
   (与 SKILL.md 既有条目同源, 本会话复踩一次。)

---

## 五、启动路径 (2026-09-11 实测)

`studio.py` 在 **`tools/gui/`** 下, **仓库根没有它**:
`cd <repo> && gui-venv311/bin/python studio.py` → `can't open file '<repo>/studio.py': [Errno 2]`, exit 2,
进程 ~30s 内退出 —— 症状像"GUI 崩了", 实为路径错。两种正确启动:

```bash
bash <repo>/tools/gui/launch_studio.sh            # 官方: 硬编码 venv/GUI_DIR + pgrep 防重入 + 日志 /tmp/studio_launch.log
# 或
cd <repo>/tools/gui && DISPLAY=:0 ../gui-venv311/bin/python studio.py
```

**启动成功必须给证据**: `ps -eo pid,lstart,args | grep "[s]tudio\.py"` 有进程 + 启动时间对得上,
再 `process(action='poll')` 确认没退。只报"已重启"不算证据。
