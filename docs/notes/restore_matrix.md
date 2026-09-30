# zmax 基线核验：仓库能恢复到什么程度

> 结论先说：**状态空间的"功能面"全部在仓库里**（代码 + 技能 + 记忆 + 服务定义 + 画布），
> 模型/数据按 `docs/notes/model-paths.md` 的约定路径**下载或识别**，只有四类东西仓库搬不动：
> 现场标定真值、厂商 SDK、训练产物、密钥（见 §3 C 类）。
> 凭证：`git ls-files` 计数 —— 1952 个 `.py`（48.5 万行）、206 个 `SKILL.md`、82 份记忆快照、30 个 systemd 单元源、35 个画布 flow JSON。

## 1. 功能 → 代码 → 资产 对照表

| # | 功能面 | 代码（在库路径，可直接 `git ls-files` 核） | 需要的外部资产 | 仓库能否恢复 |
|---|---|---|---|---|
| 1 | 状态空间引擎 / 画布 | `src/lerobot/policies/left_right/state_space/`：`planner.py`(441) `execution.py`(103) `cognition.py`(252) `dynamics.py`(126) `safety.py` `su2.py`(706) `parallel.py`(222) `perception.py` `focus_quality.py`(371) `scene_vlm.py`(380) `hil_bridge.py`(335) `web_agent_bridge.py`(352) `skills/atomic_skills.py`(180)；画布 `flows/state_space_obs.json`（+34 个历史/归档 flow） | 无（用到 VLM 时见 #7） | ✅ 纯仓库 |
| 2 | 左右脑策略（左脑建模 + 右脑世界模型） | `modeling_left_right.py`(468) `configuration_left_right.py` `processor_left_right.py` `__init__.py`；配置 `configs/policies/config_left_right*.yaml`(5) | `lora_l3_init.pt`、`wm_checkpoints`（训练产物） | ⚠️ 代码✅ / 权重需备份或重训 |
| 3 | L2 检测收口 + AOI | `tools/aoi/`（47 个 AOI/相机工作脚本）、`tools/perception*`、`tools/cam_stream_guard.py` | `yolov8s.pt`(21M, 可下)；AOI 服务在工控机(10082/10083) | ✅ 代码+权重可下；AOI 服务在外部主机 |
| 4 | L5 规划（视觉决策） | `planner.py` + `tools/` 里的 VLM 调用封装（`G.call_vlm`） | DeepSeek API key（环境变量/secrets） | ⚠️ 代码✅ / key 现场填 |
| 5 | 分层记忆（肌肉/流程/工作/宏观） | `docs/design/memory-layers-v510.md`、`docs/design/zmax_memory_integration.md`、引擎内记忆节点代码 | 无 | ✅ 纯仓库 |
| 6 | 服务与开机自启 | `tools/systemd/*.service`（30 个：工位总览/推流/agent-hub/DDS/ECS桥/网关/数据挂载…） | 密钥（`EnvironmentFile`） | ✅ 仓库（`--systemd` 一步装） |
| 7 | 视觉感知（VLM） | `scene_vlm.py` `focus_quality.py` `tools/local_vlm*`、`src/lerobot/policies/sam3_seg/` | SmolVLM2-500M(1.9G)、Qwen2.5-VL-3B(7G)、SAM3(3.2G, gated) | ✅ 全部有确切下载命令 |
| 8 | 工位总览 / 3D 叠加 | `tools/web/station.html`（热读真源）、overlay 相关工具、`tools/station_cmd.py` | 无 | ✅ 纯仓库 |
| 9 | 网页/远程 agent 通道 | `tools/agent_hub.py`、`station_cmd.py`、`web_agent_bridge.py` | `ZMAX_AGENT_TOKEN`（secrets） | ✅ 仓库 + 现场密钥 |
| 10 | DDS 遥测中间件 | `dds/`（`ss_types.py` `zmax_node.py` `zmax_types.py`）、`config/dds_cycle.json`、`tools/dds*`、守护单元 | 无（`dds-venv`） | ✅ 纯仓库 |
| 11 | 训练 / 数据闭环 | `tools/joint_train_all.py`、`joint_train_full/real*.py`、`auto_loop.py`、`lora_inject.py`、`merge_lora_ckpt.py` | 数据集（cube 95G / optical_insert 11G）、GPU | ✅ 代码；数据可下/自采 |
| 12 | 世界模型 / 官方评测 | `src/lerobot/policies/intact/`、评测脚本、`INTACT-JEPA`（第三方仓库） | INTACT 权重(2.5G) | ✅ 代码 + 权重可下 |
| 13 | 真机链路（珞石臂 / 手眼 / HIL） | `tools/hil_bridge.py`、`hil_bridge.py`、`rokae_*` 工具链 | `rokae_sdk`(厂商 260M)、现场标定真值 | ❌ 不可在线恢复（§3 C） |
| 14 | 控制台 / GUI | `tools/studio_ctl.sh`、`studio_boot_start.sh`、`tools/gui/`、`Z-MAX Studio.desktop` | `gui-venv311`（3.11） | ✅ 仓库 + venv 重建 |
| 15 | 技能库（SOP/坑） | `docs/skills/hermes-all/**`：206 个 `SKILL.md` | 无 | ✅ 纯仓库 |
| 16 | 记忆（我的跨会话记忆） | `docs/memory/**`：82 份快照（含 `MEMORY_live_*`） | 无 | ✅ 纯仓库 |
| 17 | 旧 fork 期实验脚本 | `tools/fork_experiments/`（68 个：`eval_*` `debug_*` `analyze_*` `jepa_*` 等，2026-09-30 自 fork 收回） | 无 | ✅ 纯仓库 |

## 2. 仓库以外、但属于本系统的东西（要单独备份/交接）

| 东西 | 位置 | 为什么要单独管 |
|---|---|---|
| 工控机 Windows 侧 | 192.168.23.x（ZMAX_Agent / ZMAX_AOI_KeepAlive 任务） | 远程部署件在仓库 `docs/deliver/**`，但主机本身不在仓库 |
| Orin 侧 | 192.168.23.66 | ROS2 侧代码在仓库 `ros_*_ws/`，运行时/镜像在 Orin 上 |
| ECS 站点 | `/www/wwwroot/datadrive.world`（nginx + relay） | 站点配置与网页挂载；本机只维护推送 |
| Hermes 本体配置 | `~/.hermes/`（config.yaml、cron 任务） | 技能/记忆已镜像入库；config/cron 未入（含本机路径与密钥） |

## 3. 资产四分类（决定"能不能纯靠仓库恢复"）

- **A 类 · 纯仓库即可**：功能面 #1 #5 #6 #8 #9 #10 #14 #15 #16 #17（代码/技能/记忆/服务定义/画布）。
- **B 类 · 有确切下载命令（HF/URL，走 hf-mirror）**：yolov8s(21M) → SmolVLM2(1.9G) → INTACT(2.5G) → sam3(3.2G, gated) → Qwen2.5-VL-3B(7G) → cube 数据集(43G 压缩包，解压 95G)。合计约 155G 下载量。
- **C 类 · 不可在线恢复**：
  1. **现场标定真值**（`handeye_state.json`、`calib.json`、平面几何）——必须现场重标或从备份盘恢复；
  2. **厂商 SDK**（`rokae_sdk`）——向珞石/备份要；
  3. **训练产物**（`lora_l3_init.pt`、hJEPA 头、`stable-wm-cache/checkpoints` 的 26 个 run）——备份盘或重训；
  4. **密钥**（DeepSeek/Kimi key、`ZMAX_AGENT_TOKEN`、`ZMAX_ECS_PW`、`ZMAX_TUNNEL_TOKEN`、HF token）——现场填 `$ZMAX_DATA/secrets/zmax.env`。
- **D 类 · 外部主机/站点**：见 §2。

## 4. 新机器恢复步骤（含每步验收）

```bash
# 0) 系统层: python3.11/3.12、docker、nvidia 驱动、sudo 免密
git clone https://github.com/MikeBMW/zmax.git /home/ubuntu/zmax     # 期望: 4962 文件 / 54MB
cd /home/ubuntu/zmax
bash tools/zmax_bootstrap.sh          # 期望: 打印已有/可采纳/缺失清单, 退出码 0=必需齐
bash tools/zmax_bootstrap.sh --apply  # 期望: 目录骨架 + zmax_paths.env + 采纳软链
bash tools/zmax_bootstrap.sh --smoke  # 期望: 10 个核心模块全 ✅ + 关键文件 ✅
bash tools/zmax_bootstrap.sh --systemd   # 期望: 30 个单元装入 /etc
python3 tools/repo_guard.py ; python3 tools/secret_scan.py   # 期望: 两条都 ✅ 干净
```
判据：`--smoke` 全绿 = 状态空间的代码面恢复完成；`--systemd` + 密钥 = 服务面恢复；B 类下完 + C 类补上 = 与当前产线机等价。

## 5. 与产线机的差异（诚实口径）

- 产线机上的额外东西：E 盘数据盘挂载、现场标定真值、26 个训练 run、厂商 SDK、`~/.hermes` 的 cron。
- 因此："新机器 30 分钟"能恢复到**功能可用**（引擎/画布/总览/通道/训练脚本/仿真），要恢复到**与产线机逐位等价**，还需要 C 类四样。
