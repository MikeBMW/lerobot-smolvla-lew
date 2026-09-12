# INTACT 标准机器人 · 数据源层切换节点 + 实况窗 (2026-09-12 实测)

老倪原话: "**用原项目的权重，用原项目的机器人，在状态空间中，再增加一个符合INTACT标准的机器人；
在数据源层，增加机器人切换节点。你来设计切换UI**" → 追加 "**reacher 机器人，要在状态空间的画布实现，
即选择 reacher后，既可以运行INTACT项目**"。

## 1. "符合 INTACT 标准的机器人" = 论文权重原生可驱动的那 4 个

| 机器人 | 原生环境 | 类型 | 动作空间 | 权重 | 本机实测 |
|---|---|---|---|---|---|
| reacher | swm/ReacherDMControl-v0 | DMControl 两连杆臂 qpos_match | 关节 | recovery_delta_full_reacher_s3072 | 97.0% (论文 97.0) |
| pusht | swm/PushT-v1 | 2D 推块 | 2D+夹爪 | recovery_delta_full_pusht_s3072 | 79.3% (论文 79.67) |
| cube | OGBench cube-single | **3D 机械臂推方块** | 7 维关节 | recovery_delta_full_cube_s3072 | 83.3% (6 集实测) |
| tworoom | OGBench tworoom | 两房间导航 | 2D | recovery_delta_full_tworoom_s3072 | 100% (6 集实测) |

**⚠️ 命名撞车 (老倪问过 \"reacher不是已经由原项目训练完成了么? 你为什么还要训练呢?\")**:
原项目的 `reacher` = **DMControl 两连杆臂**, 与 metaworld 里那个 Sawyer 臂的 reacher 不是一回事;
我们的 Sawyer 光模块插拔 (metaworld peg-insert-side-v3, 动作 4D 笛卡尔) 原项目**从没训过** →
原生权重直接开我们的机器人 = zero-shot = 实测 0/2 失败 (动作头输出与本工程动作空间 |ρ|≤0.22)。
所以有两条独立工作: ① 原项目 4 任务 = 只跑评测出视频 (零训练成本) ② 我们 Sawyer = 域内微调 (另一条线)。
回答用户这类质疑时先把这层说清, 否则会被理解成\"重复劳动\"。

## 2. 三层落地 (新文件)

```
① 注册表 + 驱动器 (后端, INTACT venv 跑)   tools/intact_native_robot.py
   --list                → 4 个机器人元数据 + 数据集/权重/视频就位情况 (JSON)
   --set-current <robot> → 写 data/intact_robot_state.json (切换节点的输出)
   --run --robot X       → 调 paper_runtime 的 eval.py (solver=prior_only) 跑一轮 → 官方渲染视频
② 状态 (切换语义)                          data/intact_robot_state.json
   {"robot": "cube", "ts": "...", "meta": {...}}  ← 下游数据源节点读它
③ UI (切换面板 + 实况窗)                   tools/gui/intact_robot_panel.py
   IntactRobotPanel (切换/跑一轮/播放) + LiveViewWindow (10fps 帧流 + 状态条)
```

## 3. 画布接入 (simulink_module.py 三处, 全是小 patch)

1. `NODE_TYPES` 加两类: `intact_robot` ("INTACT机器人", #00b4d8) / `robot_switch` ("机器人切换", #f0a030)
   → 画布"添加节点"自动可见 (老倪铁律: 新节点类型还要同步 `tools/ci/validate_flow.py` + `simulink_ci.py` 的枚举)。
2. `on_node_activated` 早分支 (放在 `viz_kind` 之后、`state_space` 之前):
   `if node type in ("intact_robot","robot_switch") or 名字含关键字 → self._open_intact_robot_panel()`。
   ⚠️ 这类节点带 `source` 字段, 分支太靠后会先被"数据源切换"截走 (同 ssfeat/sstest 教训)。
3. `_open_viz_node` 加 `kind == "intact_robot_live"` → `_open_intact_robot_live()` → `LiveViewWindow(当前机器人)`。
   主工具栏加「🤖 INTACT机器人」按钮 (`mk_btn(..., self._open_intact_robot_panel, "#00b4d8")`, 别忘了 addWidget)。

**\"选择即运行\"**: 面板 `switch_to_current()` 写完 state 后**立即**开该机器人的实况窗 —
这是老倪要的\"选择 reacher 后即可以运行 INTACT 项目\"的最小兑现形态。

## 4. 实况窗帧来源 (诚实标注, 别把录制帧冒充实时帧)

```
① /tmp/intact_live_<robot>.jpg         常驻 worker 外推中的实时帧 (tools/intact_native_worker.py)
② reports/intact_native/<robot>_*.mp4  本面板刚产出的 rollout
③ reports/intact_official/<robot>/env_*.mp4  官方评测视频
状态条标 `(实时帧)` 或 `(播放录制)`; 无帧就写"先点 ▶️ 跑一轮", 不要空转假装在跑。
```

## 5. 逐帧真流还差什么 (别吹已完成)

`tools/intact_native_worker.py` 已写好骨架 (World + 论文权重 + 每步写帧/状态), 但未校准:
- **policy 的 `process` = 数据集拟合的 `StandardScaler` (action/goal)** → 没有数据集就没有正确归一化,
  离线 rollout 必是垃圾 → 必须等该任务数据集落位 `$STABLEWM_HOME/datasets/`;
- swm `World` 的真实 API 是 `set_policy(policy)` + `collect/evaluate(..., on_step=cb)` (`reset()` 原地, 无返回),
  帧从 `world.infos['pixels']` 或 `envs.envs[i].render()` 取 —— 按此校准, 不要凭猜写 step 循环。
先交付"跑一轮 → 视频 → 实况窗播放", 明确写清下一步, 比假装实时流强。

## 6. 顺带: 数据页只放数据 (同会话老倪口径)

老倪: "**数据集的页面，下面的终端为什么显示很多的训练结果？不要显示跟数据无关的东西，你要重新设计数据UI**"。
- 数据页的「🧠 训练结果 (outputs/train)」整段**搬到训练台 `TrainingModule`** (不是删: 老倪要求\"训练结果完全可控\"); 
  搬法 = 在 `content_widget.setLayout(layout)` 前插 section + `self._tr_box`, 方法挪到类体内, `_tr_log` 用
  getattr 兜底 log_signal。
- 数据页只留: 数据总表 (h5 台账 + `<repo>/data/` 本地集真实统计) + 选中行详情 + 数据操作日志。
- 铁律: **页面职责单一**, 老倪会逐页检查\"这个跟这页有关系么\"。

## 7. 验证清单 (offscreen, 全绿才算完)

```
· NODE_TYPES 注册 ✓ · 双击 robot_switch 节点 → 面板弹出 + 列出 4 行 ✓
· 面板选行 → switch_to_current → state json 写入 + 实况窗绑定该机器人 ✓
· 实况窗 reload → 载入真帧 + lbl_img.pixmap() 非空 (tworoom 26 帧) ✓
· 数据页: hasattr(module,"_tr_box") is False (训练结果已搬走) + 数据表 rowCount = h5 + data/ 目录数 ✓
· 训练台: hasattr(module,"_tr_box") is True + 条目数 > 0 ✓
```
⚠️ 面板里引用仓库路径要用 `ROOT = dirname(dirname(dirname(__file__)))` (tools/gui → tools → 根);
曾写成 `dirname(dirname())` 得到 tools/ → 后端路径错、表格静默 0 行 (subprocess rc=2, stdout 空 → 不抛异常)。
