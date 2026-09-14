# 触发器路径审计实测 (2026-09-14) — 行号会漂, 用前 re-grep

问题原文: 「状态空间中, 点击运行后, 怎么没进到这个断点?」 (断点在 `src/lerobot/policies/intact/service.py::run_once`)

结论: 断点没问题, 调试器也接上了 —— **画布「运行」这条路径根本不经过 `run_once`**。

## 一、两条路径 (实测行号, 2026-09-14)

| 触发方式 | 真实链路 | 断点能停哪 |
|---|---|---|
| 画布**「运行」**(引擎整链) | 引擎每帧 → `tools/gui/state_space_sim_real.py` 注入点 (`1619` SS_INTACT / `1633` SS_L4_INTACT 门槛) → `960 _intact_u_ff()` / `1012 _l4_intact_u_ff()` → **`981/1038 self._intact_node.step(...)`** → `src/lerobot/policies/intact/runtime/node.py::step` (`156`) → `204 runtime.get_action` (跨进程桥) | 引擎注入点 / `runtime/node.py`。**`service.run_once` 永不命中** |
| **双击** INTACT 节点 / 意图解码器 | `tools/gui/node_logic.py::node_intact` (`1328`) / `node_intact_dec` (`1351`) → `svc.run_once(decode=…, write_evidence=…)` | `service.py::run_once` + decoder + runtime/node |
| E2E (不经 GUI) | `tools/intact_service_e2e.py` → `get_service().run_once()` | 同上 |

引擎代码自己的标注 (同一文件的 channel 说明):
「真调路径 = 画布节点双击 (node_logic.node_intact); 引擎侧在 S3 适配前**诚实标未接入**, 不写假 chunk」
⇒ **先读代码的诚实标注, 再下结论**; 它和"点了运行没反应"是完全一致的说法。

## 二、引擎侧的三个门槛 (满足才调节点, 否则整段跳过)

1. 档位必须是 **L4**: `tools/gui/simulink_module.py` 切 L4 档时设 `SS_INTACT=1` 并清 SHADOW + 调
   `sim.attach_intact(_nd, None)` (~`11443`); 切到非 L4 档会 `os.environ.pop("SS_INTACT")` (~`11396`)。
2. 阶段白名单: 默认**排除"插入"**段 (插入段仍走解析伺服, 保既有 mm 级精插)。
3. 节拍: `SS_INTACT_EVERY=8` —— 每 8 步才真推理一次。

## 三、VSCode 调试这个控制台 (启动/连接/配置归属)

- **启动整个控制台** = 配置「🚀 全新调试进程 (studio.py)」(= `gui-venv311/bin/python tools/gui/studio.py`,
  cwd 仓库根, `justMyCode:false`)。它的 `env` 是**故意空的** (老坑: `ZMAX_DEBUG_BREAK` 会先停在
  `execute_node_logic`, 造成"没设断点却停了")。
- 判断"这个实例能不能断点": 窗口标题显示 `⚠️非调试模式` = `debugpy.is_client_connected()` 为假, 断点必不进;
  正常应显示 `XSpace Studio — Z-MAX vX.Y.Z [W-01]`。
- attach 路线: 被调试进程要**先监听** —— `ZMAX_DEBUG=1 ../gui-venv311/bin/python studio.py`
  (默认不 listen: 无 attach 时 `debugpy.listen` 可能阻塞 Qt 主线程 map → 桌面启动窗口不显示)。
- **studio 没有单实例锁** ⇒ 别让两个控制台同时开: 会互抢 `flows/state_space_obs.json`
  (`tools/gui/launch_studio.sh` 有 pgrep guard, 但 F5 直接起新实例没有)。
- **`.vscode/launch.json` 由 GUI 右键重写**: 模板在 `tools/gui/simulink_module.py` (~12785-12837)。
  手改 launch.json 会被下次右键抹掉 ⇒ 改配置必须**两处同步**(launch.json + 模板)。
  4 个 INTACT 配置里的 `INTACT_POLICY` 是写死的旧权重, 换权重时同样要两处同步。
  跨 venv: 只有「🔬 模型侧单步 (INTACT venv, 真输入重放)」能停进 `/home/ubuntu/INTACT-JEPA/**`
  (in-process 驱动器 `tools/intact_worker_debug.py`; 真输入靠 `INTACT_KEEP_INPUT=1` 留档后重放)。

## 四、待老倪拍口径的架构决策 (别默认改)

引擎注入点直连 `node.step()`, 因此「运行」不产生 service 层产物。合并入口的做法 =
attach 时把 service 交给引擎, 注入处调 `run_once(decode=…, write_evidence=…)` 取代 `node.step`;
影响面小 (attach + 两个注入点), 但**改变现有行为** ⇒ 属"先确认口径"的决策。
