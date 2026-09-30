# 画布新增节点完整配方 + 通用万能节点 A/B/C (2026-09-10 实测)

老倪需求原话: 「在 L2 层的原子动作, 增加 A B C 三个通用操作节点, 用于 L4 的动态参数更新,
这三个万能节点在画布上位于其它原子动作的左侧, 表示通用万能节点」。

一次做对的顺序 = ① 备份 JSON → ② 加节点 → ③ 加连线 → ④ node_logic 函数 → ⑤ 路由 →
⑥ 注册 (必须在文件末尾) → ⑦ 重启 GUI 验证加载行。任何一步漏掉都是**静默失败**。

## 1. flows/*.json 结构 (state_space_obs.json)

```json
{ "format":..., "version":..., "name":..., "sim":..., "nodes":[ ... ], "links":[ ... ] }
```

节点 (实测字段, 少一个就可能不显示/不连):
```json
{"type":"model","icon":"🅰️","color":"#f0a020","inputs":["in1"],"outputs":["out1"],
 "actions":[],"w":170,"h":68,"x":905,"y":665,"id":"ssa","name":"🅰️ 通用算子 A · 参数写入",
 "params":{"state_space":true,"universal_op":true,"op_tag":"A","desc":"...","source":"tools/gui/node_logic.py · node_ss_abc"}}
```
- `type` 必须已在 NODE_TYPES 三处同步 (simulink_module / tools/ci/validate_flow.py /
  tools/gui/simulink_ci.py); 复用 `"model"` 则免改。
- `id` 取名 `ss<x>` 与既有 ss* 家族一致 (右键源码映射/断点靠 _EXTERNAL_LOC 按 id 查)。
- `row_bg` 型是**行标题背景** (含 `w/h/color/params.bg`), 别把功能节点做成 row_bg。
- 位置: 同排既有节点 y 对齐, x 按既有步距 (本仓 175) 递推; 「在某行左侧」= x 小于该排最小 x。

连线 (键是 `f`/`t`, 不是 from/to):
```json
{"id":"lk_l4_abc","f":"ssmani_exp","t":"ssa","f_port":"out1","t_port":"in1","label":"L4 动态参数"}
```
加完必查非法连线 (悬空 f/t 会让画布画不出线):
```python
ids = {n["id"] for n in d["nodes"]}
bad = [l for l in d["links"] if l["f"] not in ids or l["t"] not in ids]
```

备份: `shutil.copy(P, P + ".bak_before_<改动名>")` — 老倪对画布结构改动零容忍, 必须可回滚。

## 2. node_logic.py 三处改动 (缺一不可)

**① 节点函数** (放在同类节点函数旁, 如 node_ss_skill 后):
读引擎真实帧, 不伪造。参考模板:
```python
def node_ss_abc(ctx):
    log = ctx.get("log"); p = ctx.get("params", {}) or {}
    mod = ctx.get("module"); tr = getattr(mod, "_ss_tr", None) if mod else None
    if tr is None or not tr.get("t"):
        if log: log("… 无引擎轨迹 — 先点 ▶ 运行状态空间")
        return False
    idx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
    stage_now = str(tr["stage"][idx]).replace("阶段 ","").split("·")[0].strip()
    tgt = np.asarray(tr["target"][idx], float) if tr.get("target") else np.zeros(3)
    u   = np.asarray(tr["u_exec_vec"][idx], float) if tr.get("u_exec_vec") else np.zeros(4)
    ...
```
L4 预测列真源 = `tr["mani_pred"][idx]` (dict, 取 `.get("manifold")` 6 维; 引擎每帧真调
JEPA predictor, 见 references/state-space-exec-chain-*)。

**② dispatch 路由** — 用自己写在 params 里的标志位, 不依赖 match_node 名称匹配 (最稳):
```python
    try:
        if (ctx.get("params") or {}).get("universal_op"):
            return node_ss_abc(ctx)
    except Exception:
        pass
```
放在 execute_node_logic 里 sssk 分支之后 (**分支顺序有讲究**: 带 `source` 字段的节点会被更早的
数据源分支拦截, 特殊节点路由要往前提 — 见 verification-dialog 教训)。

**③ _reg 注册 —— 必须在文件末尾 (函数定义之后)!**
`_reg(name, [关键词], desc, fn)` 里 fn 是**立即求值**的; 若把 _reg 写在函数定义之前 →
模块 import 时 `NameError: node_ss_abc is not defined` (pyright 也会报 reportUndefinedVariable)。
本仓前半段有一大段 _reg 区 (2496 行附近, 注册的是更早定义的函数) — **新函数一律注册到
文件末尾** (_EXTERNAL_LOC 同理)。

```python
_reg("ssa", ["通用算子 A", "参数写入"], "…", node_ss_abc)
_EXTERNAL_LOC["ssa"] = (os.path.abspath(__file__), 2760, "def node_ss_abc(ctx):")
```
`_EXTERNAL_LOC` 行号铁律: 指向**函数第一行实际代码**; 指 def 行/docstring 都会让断点不命中
(见 vscode-breakpoint 系列)。改完函数位置要回头校准行号。

## 3. 通用万能节点 A/B/C 语义 (老倪设计, 可复用为其它"万能算子")

| 节点 | 操作 | 语义 |
|---|---|---|
| 🅰️ A · 参数写入 (SET) | 写 | L4 动态参数 (速度/阈值/增益/目标点) → 目标原子技能 |
| 🅱️ B · 参数微调 (Δ-ADJUST) | 增量调 | 运行时按 L4 预测降速/增力/重对准幅度 |
| 🅾️ C · 参数校验 (VALIDATE) | 闸 | 🛡 安全限值 (力/速度/位姿) 越界拒绝回退 |

连线: `L4 预测器 → A → B → C → 技能行首 (SK01)`, label 走"L4 动态参数 / 写入后→微调 /
微调后→校验 / 校验通过→原子技能参数"。
- 视觉标识: 金色 `#f0a020` (= 通用/万能) 与技能紫色 `#b98cff` 区分。
- **万能接口语义**: 服务任何原子技能, 不是绑定某一个; params 里带 `universal_op: true` + `op_tag`。

## 4. 验证 (必须重启 + 看加载行, 别只看语法)

```bash
python -c "import ast;ast.parse(open('tools/gui/node_logic.py').read())"   # 语法
bash <restart_gui 脚本>                                                     # 重启 (完整路径启动)
sleep 10; grep -E '已加载工作流' /tmp/simulink_log.txt | tail -1
# 期望: 💾 已加载工作流: flows/state_space_obs.json (65节点 92连线)
```
- 加载行数字是唯一可信证据 (62→65 节点 / 88→92 连线)。
- offscreen 只验逻辑; 画布视觉 (节点是否画在预期位置/不重叠) 需真实 DISPLAY 截图。
- 老倪会问"你没重启吧" → 汇报必带: 新 pid + 启动时间 + 加载行 (节点/连线数)。

## 5. 踩过的坑

| 坑 | 现象 | 修 |
|---|---|---|
| _reg 写在函数定义前 | `NameError: node_ss_abc is not defined` (import 时炸) | 注册一律挪到文件末尾 |
| 节点尺寸/坐标与同排不一致 | 画布重排 ("N 个节点右移避让") 把布局打乱 | 对齐同排既有 w/h/y 与 x 步距 |
| links 用了 from/to | 连线静默不显示 | 键是 `f`/`t` (+`f_port`/`t_port`) |
| 只跑 ast.parse 就汇报 | 实际加载崩 (函数未定义等 import 期错误) | 必须重启 + grep 加载行 |
| 行号字段没校准 | 双击"打开源码"跳错行 | _EXTERNAL_LOC 指第一行实际代码 |
