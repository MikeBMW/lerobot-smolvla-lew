# 🤖 INTACT 标准机器人 · 数据源层切换节点 (设计 + 实现)

> 2026-09-12 老倪需求：「用原项目的权重、用原项目的机器人，在状态空间中再增加一个符合 INTACT
> 标准的机器人；在数据源层增加机器人切换节点。你来设计切换 UI。」

## 1. 什么是"符合 INTACT 标准的机器人"

= **原项目论文权重原生对应、能在其原生环境里被 zero-search direct 直接驱动**的机器人。
不含我们域内微调的 Sawyer 插拔（那条线走 INTACT 域内微调 v2）。

| 机器人 | 原生环境 | 类型 | 动作空间 | 权重 | 官方成绩 |
|---|---|---|---|---|---|
| reacher | swm/ReacherDMControl-v0 | DMControl 两连杆臂 · qpos_match | 关节 | recovery_delta_full_reacher_s3072 | 97.0% (论文 97.0) |
| pusht | swm/PushT-v1 | 2D 推块 | 2D + 夹爪 | recovery_delta_full_pusht_s3072 | 79.3% (论文 79.67) |
| cube | OGBench cube-single | **3D 机械臂推方块** | 7 维关节 | recovery_delta_full_cube_s3072 | 83.3% (本机 6 集实测) |
| tworoom | OGBench tworoom | 两房间导航 | 2D | recovery_delta_full_tworoom_s3072 | 100% (本机 6 集实测) |

## 2. 三层架构

```
① 注册表 + 驱动器 (后端)   tools/intact_native_robot.py      [INTACT venv 跑]
   --list                 → 4 个机器人的元数据 + 数据集/权重/视频就位情况 (JSON)
   --set-current <robot>  → 写 data/intact_robot_state.json  ← 「切换节点」的输出
   --run --robot X        → 原项目权重 + 原项目运行时跑一轮 → 官方渲染视频 + 成功率
   关键约束 (实测踩坑, 不许改):
     · 论文权重必须用 paper_runtime 跑 (根运行时报 module.InverseTransitionActor 找不到)
     · 论文运行时的零搜索求解器叫 prior_only (根仓库 direct_solver 命名不兼容)
     · 数据集须落 $STABLEWM_HOME/datasets/ (pusht_expert_train.h5 / dmc/reacher_random.h5 /
       cube_single_expert.h5 / tworoom.h5)

② 状态 (切换语义)         data/intact_robot_state.json
   {"robot": "cube", "ts": "...", "meta": {...}}
   = 数据源层的"当前机器人"。下游节点 (画布「🤖 INTACT机器人」/「🔀 机器人切换」) 读它决定用谁。

③ UI (切换面板)           tools/gui/intact_robot_panel.py     [控制台内嵌]
```

## 3. 切换 UI 设计

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 🤖 INTACT 标准机器人 · 切换 (数据源层)                                      │
├────────────────────────────────────────────────────────────────────────────┤
│ 当前机器人 (切换节点输出): cube · 3D 机械臂推方块 · OGBench cube-single      │  ← 绿色 banner
│                                    权重 recovery_delta_full_cube_s3072      │
├────────────────────────────────────────────────────────────────────────────┤
│ INTACT 原生机器人注册表        [🔄刷新] [✅切换为当前] [▶️跑一轮出视频]      │
│                               [🎬播放最近视频] [📂视频目录]                 │
│ ┌────────────────────────────────────────────────────────────────────────┐ │
│ │ 机器人 │ 原生环境 │ 类型 │ 动作空间 │ 官方成绩 │ 数据集 │ 权重 │ 视频  │ │  ← 表格 (双击=切换)
│ │ reacher│ …        │ 两连杆臂│ 关节   │ 97.0%    │ ❌缺  │ ✅   │ 0    │ │
│ │ cube   │ …        │ 3D臂  │ 7维    │ 83.3%    │ ✅    │ ✅   │ 6    │ │
│ │ tworoom│ …        │ 导航  │ 2D     │ 100%     │ ✅    │ ✅   │ 6    │ │
│ └────────────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────┤
│ 日志: [注册表] 4 个 · 可跑 2 个 / ✅ 已切换 cube / ▶️ 启动 … / ✅ 成功率 …   │
├────────────────────────────────────────────────────────────────────────────┤
│ 说明: 本表 = 原项目权重在原生环境零搜索直接驱动; 切换写 state json; 画布节点读它│
└────────────────────────────────────────────────────────────────────────────┘
```

交互:
- **切换**: 选行 →「✅ 切换为当前」(或双击行) → 写 state json，banner 立即刷新。
- **跑一轮**: 选行 →「▶️ 跑一轮出视频」→ 后台线程调后端 (不卡 UI) → 成功/失败写日志 → 视频落
  `reports/intact_native/<robot>_env_*.mp4`。
- **看效果**: 「🎬 播放最近视频」/「📂 视频目录」。

## 4. 画布接入

- 节点类型: `intact_robot` (🤖 INTACT机器人, #00b4d8) 与 `robot_switch` (🔀 机器人切换, #f0a030)
  已注册进 `NODE_TYPES` → 可在画布"添加节点"里直接加。
- **双击**这两类节点 → 打开切换面板 (统一走 `SimCanvas.on_node_activated` 分支)。
- 主工具栏新增按钮「🤖 INTACT机器人」→ 一键打开面板。
- **可视化节点** `viz_kind=intact_robot_live` → 打开「🖥 INTACT 机器人实况窗」(LiveViewWindow)：
  顶部状态条 (机器人/环境/权重/步数/成功率/动作/帧std) + 10fps 帧流 + 「▶️跑一轮」按钮。
- **选择机器人 = 可运行**: 面板里「✅ 切换为当前」后自动弹出该机器人的实况窗
  (满足"选择 reacher 后即可以运行 INTACT 项目")。

### 实况窗帧来源优先级 (诚实标注, 无帧就明说)

```
① /tmp/intact_live_<robot>.jpg       常驻 worker 外推中的**实时帧** (tools/intact_native_worker.py)
② reports/intact_native/<robot>_*.mp4  本面板「▶️跑一轮」刚产出的 rollout 视频
③ reports/intact_official/<robot>/env_*.mp4  官方评测视频 (历史证据)
```
状态条会标 `(实时帧)` 或 `(播放录制)`，绝不把录制帧冒充实时帧。

## 5. 已验证 (2026-09-12)

```
· 注册表: 4 个机器人 · 元数据/就位状态/视频数 全部真实读取 (非写死)
· 切换: 面板选 cube → data/intact_robot_state.json = {"robot":"cube", "ts":"2026-09-12 21:01:28", ...}
· 画布: NODE_TYPES 注册 ✓ · 双击 robot_switch 节点 → 面板弹出 ✓ 列出 4 行 ✓
· 实况窗: 载入官方视频真帧并显示 ✓ (tworoom 26 帧) · 面板切 reacher → state=reacher + 实况窗绑定 reacher ✓
· 官方驱动: tworoom 100% (6/6) · cube 83.3% (5/6) · get_cost_calls=0 (真零搜索) → 视频已落盘
```

## 6. 待办 (下一步)

- **逐帧真流**: `tools/intact_native_worker.py` 已写好 (论文权重 → World → 每步写帧+状态)，但需要
  ① reacher/pusht 数据集就位 (policy 的 action/goal StandardScaler 来自数据集) ② 按 swm World 实际
  API 校准 (World.set_policy + on_step 回调 / render)。校准后实况窗即由"播放录制"升级为"实时帧"。
- 下游数据源节点按 state json 自动切换数据接口 (读取契约已具备)。
