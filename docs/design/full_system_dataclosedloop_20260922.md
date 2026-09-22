# Z-MAX 全系统 采-训-推 数据闭环与 sim-to-real 参数架构 (2026-09-22)

> 老倪 (09-22 开机第一条): 「检查未完成任务…你现在已经连接真机了，你要同步所有仿真与真机数据，
> URDF，质量，惯性，自由度等，按照真实的机器人机械臂，全面更新状态空间的仿真数据，全面，全系统
> 联合训练，保证 大模型层，L4 INTACT, L3 Smolvla ,L2 YOLO 和 2D转3D 深度。包括标定参数接口；
> 联合整体训练，适配或增加 LoRA, 你来进行架构优化。总之，要有完备的 L4 L3 L2 的模型训练，推理，
> 配置，模块化，sim to real 的全系统数据闭环解决方案；注意，不要发出真机控制指令，但是你可以
> 采集真机的数据，适配仿真和真机器人接口；注意不要干扰生产程序」

本轮红线 (全程遵守, 可核验)
- **真机零运动指令**: 只读订阅 (ROS2 远程 tap) + 控制器只读回读; 未调 `/move*` · `/hmi/command` ·
  `/execute_external_task` · `/gripper_driver` · `/state_machine/*`。抓取/拔模块类动作仍等现场确认。
- **不干扰生产**: 训练只在空闲 GPU 上跑 (编排器跑前查显存); 未 kill 任何非本编排器进程;
  未改 Orin 上任何程序 (Orin 保持零自研零自启)。
- **不编造**: 未标定项一律 `null` + 原因 (见 §2/§3 缺口表), 不填默认值冒充已标。

---

## 1. 架构总览 (三横切 + 四层)

```
        ┌─────────────────── 单一真源 (横切, 只此一份, 禁硬编码) ───────────────────┐
        │  config/robot/zmax_robot_spec.json   ← URDF + 真机只读实测 (tools/robot_spec_sync.py)
        │  config/calib/zmax_calib.json        ← 各标定源合并   (tools/zmax_params.py --sync)
        │  config/robot/zmax_sim2real.json     ← 引擎口径↔真机量 (tools/sim2real_bridge.py)
        └─────────────────────────────────────────────────────────────────────────┘
                    ▲ 读                    ▲ 读                    ▲ 读
        ┌───────────┴──────────┬──────────────┴─────────┬────────────┴───────────┐
        │ 大模型层 (VLM 场景理解) │ L4 INTACT (安全+物理导航) │ L3 SmolVLA (长程序列) │ L2 YOLO+2D→3D │
        │ Qwen2.5-VL / SmolVLM2 │ goal-disp + skill_ctx=24 │ smolvla_lew + LEW WM  │ yolo_peg_live │
        └───────────────────────┴──────────────────────────┴───────────────────────┘
                    ▲ 训练/评测: tools/joint_train_all.py (LoRA 可选, 显存仲裁, 逐层取证)
                    ▲ 闭环:     tools/sim2real_loop.py  (采集→归档→数据→训练→评测→部署指针)
```

**为何要"单一真源"**: 历史上口径漂移全是从"各处各写一份常量"开始的 —— 布局写死几何 (09-07)、
gripper 语义两源相反 (09-07)、B 增益写错 (09-04)、归一化 stats 配错 (09-06)。本轮的架构优化
把它们统一成 3 个 JSON + 1 个读取器 (`tools/zmax_params.py`), 消费方一律 import 读。

## 2. 真机机器人模型同步 (URDF · 质量 · 惯量 · 自由度)

工具: `tools/robot_spec_sync.py` → 单一真源 `config/robot/zmax_robot_spec.json`

| 项 | 值 | 来源 |
|---|---|---|
| 机型 | XMS5-R800-W4G3B4C (珞石) | 现场 URDF (厂商导出, sha256:4e0288ac) |
| 自由度 | **6** (J1z J2y J3-y J4z J5-y J6z) + 2 固定 (tool0/tool1) | URDF joint 链 |
| 连杆质量 | link1 3.167 · link2 4.291 · link3 2.018 · link4 2.005 · link5 1.507 · link6 0.634 kg = **13.622 kg** | URDF `<inertial><mass>` |
| 惯量张量 | 6 连杆**全部**有 ixx..izz + 质心 (base/tool0/tool1 无惯性, 已列缺项) | URDF |
| 关节限位 | J1 ±6.2832 · J2 [-2.7925, 2.6180] · J3 [-2.9671, 2.4435] · J4/J5/J6 ±6.2832 rad; v≤3.1416 rad/s; τ≤113/113/70/25/25/19 Nm | URDF `<limit>` |
| 控制器负载 | mass **1.51 kg**, cog [0.01617, 0.01289, 0.03117] m | 控制器 `setToolset` 只读回读 |
| 产线 TCP 反解 | 法兰→`/robot/tcp_pose` = [-0.015875, +0.015293, +0.260422] m (**400 帧只读反解**) | FK(jpos) 对真机 tcp 真值 |
| **FK 与真机一致性** | FK(jpos)@tool1 对真机 tcp = **3.52 mm** | 实测 (真机帧龄 0.1s) |

**关键工程动作**: 新写的 FK (`fk_from_chain`) 与旧脚本 `tools/ss_fk_xms5.py::fk` 做了 **50 组随机
位形逐位对照, 最大偏差 0.000e+00**; 中途抓出并修掉一个真 bug —— 原实现**先用新乘上去的 origin.rpy
旋转、再去平移 origin.xyz** (顺序反了), 因 6 个运动关节 rpy 全 0 而只影响末段带 rpy 的工具关节,
表现为 **136mm 假偏差**。修正后 3.5mm, 并把这个坑写进代码注释与文档, 防止再犯。

⚠️ **诚实边界**: 反解用的 400 帧期间机械臂**静止**(关节极差 0.0 rad) ⇒ `std=0.0` 只证明"同一姿态
重复读数稳定", **不能**证明该 TCP 偏移在整个工作空间是刚体常量。要闭环该标定, 需现场**人工拖动**
机械臂到多个位姿后复采 (零运动指令, 人手拖动即可) —— 脚本已把这条写成 `static_warning` 落进真源。

## 3. 统一标定参数接口

工具: `tools/zmax_params.py` (`--sync/--check/--show/--fk/--json`) → `config/calib/zmax_calib.json`

| 项 | 状态 | 说明 |
|---|---|---|
| 相机内参 K / 畸变 | ✅ | fx 394.06 · fy 393.47 · cx 318.4 · cy 238.7 (ROS camera_info 只读订阅) |
| 产线 TCP 反解 | ✅ | 见 §2 (含静帧诚实警告) |
| 控制器负载 | ✅ | mass/cog (setToolset 回读) |
| 机器人 DOF / 几何 | ✅ | 见 §2 |
| 手眼外参 `T_base_cam` | ❌ **待标** | 需零运动人工拖动 10+ 位姿 (板: `tools/board_handeye_solve.py`) |
| 台面高度 `plane_z` | ❌ **待量** | 现场用夹爪/塞尺量一次 |
| 现场示教几何 (peg_head/goal/aoi) | ❌ **待示教** | `tools/ss_geom_calib.py --record …` (人工拖位后确认) |

就绪度检查: `python tools/zmax_params.py --check` → 有缺口返回码 1 (**未标定绝不用默认值顶替**)。

消费方已接入 (不再各自硬编码):
- `tools/gui/yolo_perception.py` — 台面高度改读注册表; 未标定时**显式标注**"回退**仿真**默认"。
- `tools/real_truth.py` — 示教几何与夹具偏移增加**注册表兜底**; `snapshot()` 回读正常 (tcp 帧龄 0.07s)。

## 4. 仿真↔真机参数桥 (口径对齐)

工具: `tools/sim2real_bridge.py` → `config/robot/zmax_sim2real.json`

| 引擎口径 (来源代码) | 真机物理量 | 桥接值 |
|---|---|---|
| `obs[0:3]` hand | TCP (FK(jpos)/编码器) | FK 残差 3.52 mm |
| `obs[4:7]` peg | YOLO 2D + 反投影 (K+T_base_cam+plane_z) 或 plane_z 光线回退 | 夹具偏移 = **null (待示教)** |
| `obs[36:39]` target | 示教孔位 (cell_geometry.goal) | 未就绪 |
| 动作 u (m/s), act1=0.5 | RT 伺服/点位 (Orin robot_driver) | 单步 10 mm, 限幅 0.6 m/s |
| 关节安全包络 | URDF 限位 6 轴 | → L2 收口闸逐轴夹紧 |

## 5. LoRA 适配 (自实现, 免依赖, 带 5 条物理断言)

工具: `tools/lora_inject.py` (库 + CLI)

**为什么不用 peft**: L4 INTACT 是自研 JEPA (非 HF 模型), peft 的 target_modules 约定不适配;
且 INTACT-JEPA venv **实测没有 peft**。自实现 ~120 行 → 两套环境同一份代码, 行为可审计。

断言 (selftest, 两个环境都全绿):

| # | 断言 | 实测 |
|---|---|---|
| ① | 注入瞬间与原始模型**逐位等价** (B 零初始化) | max\|Δ\| = **0.000e+00** |
| ② | **只有** lora_A/B 可训 (基座全冻结) | 4/4 项全是 lora_* |
| ③ | 真在学 | loss 1.0399 → 0.0000 (−100%) |
| ④ | merge 折回后推理路径一致 (可部署) | max\|Δ\| = 2.4e-07 ≤ 容差 2.2e-06 |
| ⑤ | 适配器落盘/回读 | 4/4 张量, 0.004 MB |

**L4 接入** (`/home/ubuntu/INTACT-JEPA/train.py`, 环境变量 `ZMAX_LORA=1` 才开, **默认关 = 零回退**):
实跑 200 步 → **注入 112 层, 可训 967,616 / 总 21,944,408 = 4.41%**, 基座冻结;
训练完成 rc=0 / 133.8s / ckpt 88,027,492 B; 日志 `fit/local_mae 0.024 · fit/goal_mae 0.025 ·
skill_ctx_usage 1.000`。

**L3 接入**: lerobot 0.5.2 **原生支持 PEFT** (`cfg.peft` + `policy.wrap_with_peft`),
本机补装 `peft 0.21.0` 到 lerobot-venv; 编排器把 `peft:{method_type:LORA, r:8, lora_alpha:16,
target_modules:[q_proj,k_proj,v_proj,o_proj]}` **写进生成的 YAML** (不走 `--peft.xxx` 命令行:
draccus 对可空子配置的命令行覆盖不可靠), 日志确认 `Using PEFT! Wrapping model.`。

⚠️ **L3 LoRA 在 8GB 卡上尚未跑通 (三次尝试均 OOM, 如实报)**: 全参 batch8 能跑 (~6.2GB),
但开 LoRA 后 `torch.OutOfMemoryError`(需 816MiB/仅余 330MiB); 逐层收紧仍不够 ——
`all-linear`→`q/k/v/o` + batch 8→4→**2** 三档都 OOM。根因: **peft 对适配器输入做 fp32 转换**
(`tuners_utils._cast_input_dtype`), VLM 大激活多留一份 fp32 ⇒ 净增 ~1GB 以上, 8GB 卡装不下。
修法 (按代价排序, 留档待决): ① 换 12GB+ 卡跑 L3 LoRA; ② 只给动作专家头挂 LoRA
(`full_training_modules` + 缩小 targets); ③ 视觉塔整体冻结后 LoRA 语言层 (需 lerobot 侧支持
`exclude_modules`)。**当前 L3 交付 = 全参续训** (已验证路径, batch8/3.9s per step)。

**部署口径**: `tools/lora_merge_ckpt.py` 把 LoRA 训练产物折叠成普通权重
(`W_eff = W_base + (alpha/r)·B@A`), 并**校验输出键集合与起点权重完全一致**才允许落盘 ——
避免"看着训了其实结构不对"。实测: 112 层折叠 / scaling=2.0 / 最大单层增量 |Δ|=0.0064 /
键集合与 d9 完全一致 ✅。同时用同一份 ckpt 对照验证**基座确实冻结**: 99 个非 LoRA 张量与 d9
逐位相同, 只有 6 个 BatchNorm `running_mean/var/num_batches_tracked` 因前向统计而变
(属 buffer 正常更新, 非参数漂移)。

踩坑入档 (三条都是本轮实测抓出来的):
1. **LoRA 补丁写成 post 步骤 = 整轮没开 LoRA** (日志 `'peft': None, use_peft=False`) → 必须在
   mkcfg 之后、训练启动之前; 编排器已改 `pre` 顺序。
2. **8GB 卡 + `all-linear`/`q,k,v,o` 与 batch 8/4/2 三档都 OOM** (见上 ⚠️ 条; 根因 = peft fp32 输入转换)。
3. **`lora_inject` 顶层子模块名不含 `.`** (如 `nn.Sequential` 的 `"0"`) → `name.rsplit(".",1)[1]`
   取到 attr=None 被跳过 ⇒ **注入 0 层但自检 ①"逐位等价"仍然通过**(注入 0 层当然等价!) ——
   自检抓出: 断言 ②"只有 lora_* 可训"报 0 项才暴露。教训: 等价性断言必须与"确实注入了"联合断言。

### 5.1 L4 LoRA 同口径 A/B 结果 (实跑, 不是估算)

起点 v6d9 全参权重 vs 在它之上 **200 步 LoRA 续训**后合并的权重, 同一份 h5 · 同 60 clips ·
同 seed · 同 `--skill on`, 逐 slot 对照 (`reports/lora_eval_v6d9.json` / `lora_eval_v6lora.json`):

| 指标 | v6d9 (起点) | +LoRA 200 步 | 变化 |
|---|---|---|---|
| 16 槽平均 MAE | 0.03052 | **0.02750** | **−9.88%** |
| p_dy (横向) 均值 | ≈ −0.02 | **≈ +0.09** (范围 −0.05…+0.25) | **+0.106** |
| win_const | True | True | 保持 |
| p_dx / p_dz / p_grip | 0.46~0.84 / 0.57~0.89 / 0.79~1.00 | 0.51~0.87 / 0.57~0.89 / 0.91~1.00 | 略有改善 |

诚实解读: ① LoRA 用 **4.41% 的参数**拿到 −9.88% 的 MAE, 且横向 p_dy 从"几乎无关"抬到 +0.09~+0.25;
② **但仍远未达到 KPI-1 的逐轴 |corr|≥0.5**, 即 L4 收口闸的 dy 卡点**没有被 LoRA 解决** ——
这与 §既有归因一致 (dy 缺的是**数据里的横向纠偏行为**, 不是模型容量/训练量);
③ 60 clips × 1 repeat 的统计力有限, 要下最终结论应跑 200 clips × 3 repeats。

## 6. 全系统联合训练编排 (L4 / L3 / L2 / 大模型层)

工具: `tools/joint_train_all.py` (`--dry-run` / `--env-check` / `--only` / `--steps` / `--lora-r`)

| 层 | 训练入口 (复用既有验证过的链) | LoRA | 起点 (零回退) |
|---|---|---|---|
| L4 INTACT | INTACT-JEPA `train.py --config-name=intact_goal_optical_insert_v6 data=zmax_v6` | ✅ 自实现 (112 层, 4.41%) | v6d9 在役权重 → 新目录 |
| L3 SmolVLA | lerobot `lerobot_train` (policy=smolvla_lew, 含 LEW 世界模型) | ✅ lerobot 原生 PEFT | `outputs/train/smolvla_lew_sim/checkpoints/000300` |
| L2 YOLO | `tools/yolo_annot_train.py` (真机标注帧域适应) | 全参微调 | `models/yolo_peg_live.pt` (在役软链) |
| 大模型层 | 只读体检 (无训练; 上 3B VL 须显存协商) | — | — |

编排器特性: 显存仲裁 (跑前查空闲, 不够则等) · 逐阶段 rc/耗时/产物取证 (`reports/joint_train_<ts>/`) ·
旧产物不覆盖 (新目录名) · 不 kill 外部进程。

**L2 实测结果 (诚实)**: 微调后与在役同帧对照 → `peg 检出 1/1 · conf 0.904` vs 在役 `1/1 · 0.906`
→ **➖ 持平/回退 ⇒ 按纪律不上默认档** (工具自己给出 `ln -sfn` 命令但**未执行**; 老倪定的门槛是
"有提升非仅不回退")。诚实限制: 真机帧评测集当前只有 **1 帧**新鲜图 (产线空闲, 相机只有 1 张新帧),
统计力不足 → 待产线动起来后重评。

## 7. Sim-to-Real 六环闭环

工具: `tools/sim2real_loop.py`

```
① 采集体检 (真机只读 tap 新鲜度/发布者/帧龄)   → ② 归档 (硬链接快照 + MANIFEST/sha256/行数)
   → ③ 数据构建 (H5 episodes/帧数/skill_ctx 口径 + YOLO 标注集)  → ④ 训练 (调编排器)
   → ⑤ 评测 (INTACT 判闸逐轴 corr/MAE + YOLO 真机帧检出同帧对照) → ⑥ 部署指针 (默认 dry-run 只打印)
```

红线写在脚本常量里 (不是口号): 只读、不干扰生产、不编造 (缺项记 fail 并报原因, 不跳步糊过去)。

## 8. 模块化清单 (本轮新增/改动)

| 文件 | 作用 |
|---|---|
| `tools/robot_spec_sync.py` | URDF + 真机实测 → 机器人参数单一真源 (+ FK 校验/产线 TCP 反解) |
| `tools/zmax_params.py` | 全系统参数/标定**唯一读取接口** (robot_spec/fk/joint_limits/calib/plane_z/gaps) |
| `tools/sim2real_bridge.py` | 引擎口径 ↔ 真机物理量 对照表 (含就绪度与来源) |
| `tools/lora_inject.py` | LoRA 适配器 (注入/冻结/合并/存取 + selftest) |
| `tools/joint_train_all.py` | L4/L3/L2/LLM 联合训练编排 (LoRA 开关, 显存仲裁, 取证) |
| `tools/llm_layer_check.py` | 大模型层权重/接口/凭据体检 (按权重文件体积判"下全") |
| `tools/sim2real_loop.py` | 六环数据闭环 |
| `config/robot/zmax_robot_spec.json` | ★ 机器人真源 (DOF/质量/惯量/限位/工具/TCP 反解) |
| `config/robot/zmax_sim2real.json` | ★ 仿↔真参数桥 |
| `config/calib/zmax_calib.json` | ★ 标定注册表 (K/T_base_cam/plane_z/几何/负载/TCP) |
| `INTACT-JEPA/train.py` | +ZMAX_LORA 守卫钩子 (默认关) |
| `tools/gui/yolo_perception.py` · `tools/real_truth.py` | 改为读单一真源 (缺项显式标注, 不冒充已标) |

## 9. 命令速查

```bash
R=/home/ubuntu/lerobot-smolvla-lew; cd $R; P=gui-venv311/bin/python
$P tools/robot_spec_sync.py                 # 同步真机模型参数 → 单一真源 (含 FK 校验表)
$P tools/zmax_params.py --check             # 标定就绪度 (缺口非零退出)
$P tools/zmax_params.py --fk <q1..q6> --live  # 真源几何 FK 对照真机 tcp 真值
$P tools/sim2real_bridge.py                 # 仿↔真参数桥
$P tools/lora_inject.py --selftest          # LoRA 五条断言
$P tools/joint_train_all.py --env-check     # 各层前置体检
$P tools/joint_train_all.py --dry-run       # 联合训练计划 (不执行)
$P tools/joint_train_all.py --steps 200     # 实跑 (默认 L4+L3 开 LoRA)
$P tools/sim2real_loop.py --train --eval    # 六环闭环
```

## 10. 诚实缺口 (未完成 / 需现场)

1. **手眼外参 / plane_z / 示教几何** 三项未标 → 真机 3D (2D→3D 深度) 仍只能给 2D 框 + 相机系点;
   缺的是"现场几分钟的人工测量/示教", 不是算法 (脚本与接口已就位)。
2. **产线 TCP 反解** 只有静帧样本 → 需人工拖动多姿态复采才能闭环刚体性。
3. **L3 LoRA 本轮** 首跑因显存 OOM 失败 → 已降 batch 到 4 + expandable_segments 重跑 (见 §5 坑 2)。
4. **L2 微调** 未证明提升 (持平) → 未上默认档; 真机评测帧太少 (1 帧)。
5. **大模型层** Qwen2.5-VL-3B 权重本机未下全 (HF 缓存仅小文件) → 上大模型前需下载 + 显存错峰。
6. L4 LoRA 权重尚未过判闸 → 需在 v6 数据上跑 `intact_replay_check_v4` 逐轴 corr 对照在役 v6d9。

---

## 11. 发布记录 (v5.12.0) 与 CI 实况

| 项 | 状态 | 说明 |
|---|---|---|
| tag v5.12.0 + main | ✅ 已推 | 版本 6 处同步点 + VERSION.md 历史行; 后续修正 commit 7efd924c 已推 main |
| Windows `.exe` | ✅ 128.7MB / 164.3MB | Release 产物 `Z-MAX_Console.exe` (164.3 MB) |
| macOS `.zip` | ✅ | `Z-MAX_Console-macOS.zip` (128.7 MB) |
| 下载页 | — | https://github.com/MikeBMW/lerobot-smolvla-lew/releases/tag/v5.12.0 |
| Simulink 模型验证 CI | ✅ success | |
| Build & Push Console Docker Image | ❌ failure | **根因 = `Log in to Alibaba Cloud ACR` 步骤失败** (阿里云 ACR 凭据缺失/失效), 属既有基础设施问题, 与本轮代码无关; 补凭据后可重跑 |
| Create Release / PyPI | ⏭ skipped | 设计如此 |

**体检工具假警报修正 (commit 7efd924c)**: `tools/llm_layer_check.py` 原来只查 HF 缓存,
把**在役权重** (INTACT 在 `stable-wm-cache/checkpoints`, L3 在 `outputs/train`, L2 是 `models/yolo_peg_live.pt` 软链)
误报成"未下全" → 现 HF 缓存只判"要从网上下"的 (Qwen VL / SmolVLM), L4/L3/L2 判本机在役位置。
修正后: L4_INTACT_in_service ✅ (→ intact_l4_current) · L3_SmolVLA ✅ · L2_YOLO_live ✅ (→ best.pt);
**唯一真缺口 = Qwen2.5-VL-3B 权重未下全 (0MB)**。

