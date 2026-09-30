# 画布节点「右键 → 打开 VSCode」定位真源码 + INTACT action 输出地图
(2026-09-14 实战; 触发: 老倪「DiT 的右键怎么没有进入源代码呢?」+「INTACT 的 action 输出在哪里」)

## 一、右键定位的判定顺序 (GUI `simulink_module.py::open_in_vscode`)

```
① 节点 params.source (+ params.source_symbol 按符号**现搜**行号)
   └ 相对路径按**仓库根** join; 描述式写法要拆: "路径 · 符号" / "路径 符号" / "路径 --flag"
   └ 若解析结果只落到 GUI 自身 (tools/gui/node_logic.py) → 让位给 ②
② node_logic.match_node(节点名) → NODE_LOGIC[key] → _EXTERNAL_LOC[key] (真实外部实现)
   match_node = **最长关键字**匹配 (不是注册顺序!)
③ 都没命中 → 退回 node_logic.py 自身 co_filename → 用户观感"没进源码"
```

**两个必踩根因 (2026-09-14 修)**:
1. **只写文件不写符号** → `code -g <file>:1` 打开在**第 1 行** → 看着像"没跳进实现"。
   DiT 节点 (`ssdec`) 当时就是 `params.source=action_head.py` 无符号 → 打开第 1 行。
2. **source 指向 GUI 壳文件, 真实现其实在 src/** → 11 个节点: `sssk1-8` 写
   `tools/gui/node_logic.py node_ss_skill` (而 `atomic_skills.py` 自己的注释就写着"画布 SK01-08
   右键源码指向本文件"), `ssyolo/ss2d3d/sstactile` 写 `tools/gui/yolo_perception.py`
   (150 行里**没有** YoloStateAligner/detect_3d/synth_tactile)。
   **判据: 目标文件里 grep 不到那个符号 = 指向错了**, 不是"打不开"。

## 二、三件工具 (都在 `tools/`, 可复跑)

| 工具 | 作用 | 命令 |
|---|---|---|
| `check_node_source_map.py` | **全画布体检**: 逐节点报走哪条路/定位到哪个文件哪一行/符号是否存在, 并标出"落到 GUI 自身"的节点 | `python3 tools/check_node_source_map.py [--only 关键词] [--verbose]` (退出码 0=PASS) |
| `fill_node_source_symbols.py` | 给有真实文件但无符号的节点**补 `params.source_symbol`** (符号只用 registry 里人工核对过的, 且必须**同一文件**+符号真实存在) | 先 dry-run 看清单 → `--apply` |
| `repoint_node_sources.py` | 把指向 GUI 壳的节点**重指向真实现** (内置映射表, 同样先验文件+符号) | 先 dry-run → `--apply` |

纪律 (宁缺勿错): 两个 apply 工具都**只在"目标文件存在 + 符号在该文件里真实存在"时才写**,
否则打印跳过原因; 写入前自动备份 `flows/state_space_obs.json.bak_<ts>`, 用
`json.dump(..., ensure_ascii=False, indent=2)` (= GUI 自己的保存格式)。

**2026-09-14 结果**: 补 28 个 source_symbol (DiT → `action_head.py:205 :: class SmolVLALewActionHead`)
+ 重指向 11 个 (SK01-08 → `skills/atomic_skills.py:46/59/72/86/100/113/127/142`;
YOLO → `yolo_state_aligner.py:37`; 2D→3D → `:65`; 触觉 → `gen_tactile.py::synth_tactile`)。
体检终态: **可定位 60 · 不可定位 0 · 落到 GUI 自身 9** (剩 9 个是显示类节点: 仿真波形/操作视频/
3D 视图/能力档位/训练推理开关/通用算子 A·B·C — 它们的实现本来就在 node_logic.py, 属于正常)。

⚠️ 改 `simulink_module.py` 后要**重启控制台**才生效 (画布 JSON 是数据, 重新载入工作流即可)。
⚠️ 另有旧自查脚本 `tools/verify_vscode_source_loc.py` (打桩 Popen 断言 `code -g` 路径), 与新体检互补。

## 三、INTACT action 输出的三处代码位置 (老倪问"action 输出在哪里")

| 层 | 位置 | 说明 |
|---|---|---|
| 模型原始 chunk | `src/lerobot/policies/intact/runtime/node.py:204` `actions, diag = self.runtime.get_action(info, horizon=…)` | 动作历史滚动在 `:218`; 模型侧真正在 `/home/ubuntu/INTACT-JEPA/jepa.py:200 get_action()` (horizon 循环 `:275-277`) |
| **实际下发机器人的 env 动作** | `tools/intact_direct_rollout.py:237-239` (`raw = chunk[chunk_step, slot*4:(slot+1)*4]` → `act = raw*a_std + a_mean` → `clip(±1)`) → `:245 s._direct_act` | 引擎 `state_space_sim_real.py:1268` 取 `_direct_act` 当 **env 级动作** → `env.step`。L4「点运行」走的就是这条 |
| 给 L3 的 u 空间先验 | `src/lerobot/policies/intact/decoder.py:126-128` (`u[:3]=clip(a0×K_ACT)` · `u[3]=闭/开`) | 意图解码器产物, 进 `ssdec(DiT)` 的 **in2** |

**画布连线 (L4→L3)**: `ssintact → ssintact_dec →(in2) ssdec(DiT)`; DiT 另收 `ssvlm`(in1 潜空间 z)/
接触流形(in3)/性能流形; 输出到 `ssff`(前馈加速器) 与 `ssact`(执行器)。
**另有独立一条 L4 光模块链**: `swintact → swworld`(动作块直接 env.step), 与 L3 那支不同链。

## 四、运行路径必须真喂 skill_ctx (否则模型硬闸拒绝 → 看着像"跑不动")

`skill_dim>0` 的 ckpt 缺 `info["skill_ctx"]` 时模型侧**直接报错**:
`ValueError: checkpoint was trained with a skill channel (skill_dim>0) but info['skill_ctx'] was not
provided — refusing to silently degrade` ⇒ 真推理 **0 次** (被吞成"模型能力差")。
修法: 直驱每帧走 `service.run_once(..., node=引擎节点, obs_frame=真渲染帧, skill_ctx=build_skill_ctx(...))`,
x 用**夹爪真实位置 obs[0:3]**, grip 用引擎控制向量 u[3]; 验收判据 = 真推理次数>0 + `u_ff_src` 是解码器口径
+ skill_ctx 24 维非零 + 证据落在**工程内** `reports/`。

## 五、证据必须能溯源到权重文件

本路径桥的 `ckpt` 字段可能为空 (worker 报 `policy=direct`) ⇒ 证据看不出"这次用的是哪份权重"。
已在 `service.run_once` 把 `ckpt_env` / `ckpt_realpath` / `ckpt_mtime` / `ckpt_bytes` 写进 diagnostics。
配合调试配置的**稳定指针** `checkpoints/intact_l4_current/` (见 cross-venv-model-canvas-node §8.7):
换权重只动软链 `bash tools/l4_use_ckpt.sh [轮次关键字] [epoch]`。
⚠️ 同类 bug: 服务 root 解析写错层级 (往上跳两级) → 证据被写到 `/home/ubuntu/reports/` (工程外);
判据里要带路径, 别只看"文件生成了"。
