# 待修清单 · 2026-09-15（关机前留档，下次启动执行）

## 🔻 关机前状态 (2026-09-15 13:40 静静 — 保存数据 + 小版本迭代 已完成)

- **版本 `v5.6.6`**（tag 已推；CI 并行出 Windows .exe + macOS .zip，**含发版前冻结核验**）
  · `v5.6.5` = Windows 点「🎥 真实化运行」必崩 的根因修（mujoco 插件 DLL 依赖解析 → 运行时钩子）
  · `v5.6.6` = GUI 运行台账 + AOI 报告行（**行为零回退**，只加日志与证据文件）
- **已入库 (main)**: GUI `tools/gui/simulink_module.py`/`studio.py`/`pyi_rth_mujoco_dlls.py`(新) ·
  工具 `tools/intact_direct_rollout.py`(闸/AOI 落盘) · CI `.github/workflows/build-win-exe.yml`(冻结核验 + A/B job) ·
  本轮证据 `reports/intact_direct_20260915_131432.json` + 100 个历史小证据(json/txt 398KB) ·
  技能全量镜像 `docs/skills/hermes-all` + `docs/memory` 记忆备份
- **未入库（按"大文件不进代码库"纪律，仍在磁盘）**: `reports/evidence_l4_verify_20260915/`(6 段 L4 视频) ·
  `reports/evidence_*/` · `reports/intact_sw/video/` · `reports/mem_ladder/video/` ≈ 819MB
- **无训练在跑**、GPU 空闲（0 MiB）、磁盘 282G/300G、auto_loop 守护在跑（队列空）
- **开机守护已装**: user crontab `@reboot sleep 30 && ~/.hermes/scripts/hermes_cron_reclock.sh`
  —— 防"开机 RTC 偏 8h → cron next_run 全被推后 → 全天不触发"（今天真实发生过，见下节）

## ⏭ 下次启动第一步（照旧 + 新增）

1. `date` 对时间；`hermes cron status` / `hermes cron list` 确认 next_run 在未来（异常则跑 reclock 脚本）；
2. 打开 GUI 目检 **L4 档**：日志应出现 `🛡 L2 收口闸: 共 N 步 · …`、跑完出现 `🔍 AOI 报告: ok=…` +
   `📄 运行台账已存: reports/gui_real_run_*.json`，并跑完全链 **done=True + AOI ok**；
3. 或 headless 同口径：`tools/intact_direct_rollout.py --mode full --seeds 104,105,106 --max-steps 4000 --infer-every 1 --baseline 1 --video-dir reports/evidence_l4_verify_<日期>`；
4. 想让闸门按 cos 自动放权 → 继续 §6 三条口径（goal 前瞻口径 / 动作历史 raw-vs-normalized / 闭环 DAgger 再训）。

## 🔬 2026-09-15 13:30 本轮实跑 (L4 档目检 + Windows exe 崩溃根因修) — 全部有 CI/日志实证

### A. L4 档实跑目检（3 seeds，直驱 vs 解析链**同轮同口径**）
命令: `INTACT_RUNTIME=root INTACT_POLICY=intact_l4_current ./gui-venv311/bin/python tools/intact_direct_rollout.py --mode full --seeds 104,105,106 --max-steps 4000 --infer-every 1 --baseline 1 --video-dir reports/evidence_l4_verify_20260915`
报告: `reports/intact_direct_20260915_131432.json`（+ 6 段 mp4 在 `reports/evidence_l4_verify_20260915/`）

| seed | 解析链(对照) | 模型直驱 | 收口闸(白名单外/方向否决/采纳融合) | AOI |
|---|---|---|---|---|
| 104 | done=True 878 步 · 8.9mm | **done=True 949 步 · 8.1mm · 真推理 949 次** | 706 / 136 / **107 采纳** | **ok=True** (insert_depth_min 1.38mm, force_peak 0.991, 无 stall, 无回抓) |
| 105 | done=False 3000 步 · 12.8mm | done=False 3000 步 · 26.2mm | 1235 / 1696 / 69 | {} (未完成) |
| 106 | done=False 3000 步 · 32.3mm | done=False 3000 步 · 0.7mm | 1474 / 1142 / 377 | {} (未完成) |

- seed104 阶段覆盖 14/14：接近→对位→下降→插入→插入·接触→抓取→抬起→转移→对位→拔出→拔出·接触→回程→放下→AOI转移→AOI检测。
- **关键结论**：直驱与解析链**逐 seed 结果一致**（1/3 成功）⇒ 105/106 的失败是**该 seed 干扰布局层面的困难案例**（连解析链真值控制器也跑不完），不是 L4 模型通道问题。GUI 的 L4 档本来就会换干扰布局重试 ≤5 次。
- 与 v5.6.3 那次「闸全否决(blend=0)」相比：现在模型提案**真被采纳**（104: 107 步融合，w 0.906~1.000）。
- 工具补强：`tools/intact_direct_rollout.py` 现在落盘/打印 GUI 同款哨兵行（收口闸计数 + AOI 报告），headless 也能自证「实际在跑什么」。
- ⚠️ 口径提醒：同 seed 两次运行 insert 深度会漂（4.2mm ↔ 8.1mm），**别拿单次 insert_mm 下结论**；硬判据用 done + AOI(+ 几何自检)。

### B. Windows exe 点「🎥 真实化运行」必崩 —— 根因已查清并修复（v5.6.5 已发双包）
- **现象**：`Failed to load dynlib/dll '...\_MEI...\mujoco\plugin\actuator.dll'. Most likely this dynlib/dll was not found when the application was frozen.`
- **根因**（archive_viewer + pefile + CI 实测，非推测）：打包后 `mujoco/mujoco.dll` 在 `mujoco/` 级、插件在 `mujoco/plugin/` 级；
  `actuator.dll` 的 PE 导入表依赖 `mujoco.dll`(+VC 运行时)，而 Windows 解析 DLL 依赖只看「DLL 自身目录 + 已注册搜索目录」→
  PyInstaller 的 ctypes 钩子把底层 OSError 包成上面那句；**底层真因实测 = WinError 1114（DLL 初始化例程失败），老倪机上同一句话**。
- **修**：新增 `tools/gui/pyi_rth_mujoco_dlls.py`（PyInstaller `--runtime-hook`，在 import mujoco 之前跑）：
  ①注册 `_MEIPASS`/`mujoco`/`mujoco/plugin` 到 DLL 搜索目录 → ②仍失败则把 mujoco.dll 复制进 plugin/ → ③再复制 VC 运行时 → ④仍失败则显式停用该插件并留证。
  CI 实测结论 = **阶段①就够**（`dll_fix=stage=dirs_only,n=4`，4 个插件全部加载成功）。
- **防复发（老倪「发版前先自证」）**：CI 新增**冻结核验** —— 打包后真跑 `Z-MAX_Console.exe --engine-selftest`
  （真 import mujoco/metaworld + 建 L4 场景模型 + 步进，结果写 json + 退出码；Windows/mac 都跑），不过不发版；
  另加 **A/B 基线 job**（`workflow_dispatch` 勾 `ab_baseline=true`）：不装钩子的基线**必须崩在 mujoco/actuator.dll** 上才算取证成立。
- **实证**：正式包 `plugin_handles=4, rc=0`；基线包 `rc=1, cause=WinError 1114 @ mujoco/__init__.py:183` —— 同一 commit、同 collect 参数，只差一个钩子。
- **产物**：v5.6.5 Release 双包已更新（exe 164,746,355 B / macOS.zip 129,100,144 B，13:24 上传），CI 三 job 全绿。
- 附：CI runner 无显卡 → 核验里 `render_ok=false (gladLoadGL error)` 属**环境**限制，故意只记录不判失败（真机渲染另走正常路径）。

## 🔎 2026-09-15 12:35 开机自检（静静 — 上一任务收尾）
- **时钟**: 开机时 RTC 偏 **+8h**（journal: `setting system clock to 2026-09-15T12:20:49 UTC`），
  NTP 在 12:21:27 拨正；现 `System clock synchronized: yes`，RTC 已写回正确 UTC（下次开机应正常）。
- **cron**: 8h 偏差导致 13 个任务 next_run 全被推到 20:3x（= 8 小时不触发，watchdog 静默死亡）。
  已全部 `hermes cron edit --schedule <原样>` 重算；**并已加开机守护**：user crontab
  `@reboot sleep 30 && ~/.hermes/scripts/hermes_cron_reclock.sh`（等 NTP 同步后自动重算，日志 `~/.hermes/logs/cron_reclock.log`）。
- **上一任务（发布最新控制台 win+mac）已闭环**: v5.6.4 的 macOS 构建昨次 failure（步骤 `Download MLP operation video` 拉 datadrive 超时/中断，
  41s 即挂），本次重跑 **attempt 2 success（3 分钟）**，Release `v5.6.4` 现有双包：
  `Z-MAX_Console.exe` 164,737,806 B + `Z-MAX_Console-macOS.zip` 129,091,533 B（12:29 上传）。
- **守护/进程**: auto_loop 已随 @reboot 重启（12:22 起，队列空，WS 已重连）；GPU 空闲 0 MiB；磁盘 282G/300G。

### ⚠️ 未修（新发现，非本任务范围）
- **Quality CI 在 main 长期红**：pre-commit 12 个 hook 挂（debug-statements / check-yaml / end-of-file / trailing-whitespace /
  ruff-format(632 文件) / ruff / typos / pyupgrade / prettier / zizmor / bandit / mypy）。
  主因 = **技能镜像入库**（`docs/skills/hermes-all`、`docs/skills/xspace`、`docs/memory` 千余文件未过 lint），
  少量真红：`experiments/train/trace_train.py:179,233 breakpoint()`、`train_smolvla_mini.py:38 pdb`、
  `config/state_machines/motion/尝试插入第一次.yaml:23` YAML 语法、`tools/disk_guard.py:20` typos(lew)。
  建议修法（下轮做）：给 `docs/skills|docs/memory` 加 pre-commit `exclude`（或 CI 只查 `src/ tools/ docker/`）+ 清实验脚本调试断点。
- **Docker 镜像 CI**: `Log in to Alibaba Cloud ACR` = "Username and password required" → ACR 凭据 secret 缺失/过期。
- **Z-MAX CI/CD**: `Simulink 工作流标准合规检查` failure。

## 🔻 关机前状态 (2026-09-15 09:15 静静 — 保存数据 + 小版本迭代 已完成)

- **版本**: `v5.6.4`（= 本文件所在 main 的 HEAD 96e0913b；tag 已推，CI 出 Windows .exe + macOS .zip）
  · `v5.6.2` = 老倪点的那次发布（exe sha256 已逐位实测 `9379b053…b7ca9b76`）
  · `v5.6.3` = L4 档 4000 步根因修（收口闸 + 异常不再静默零动作）
  · `v5.6.4` = 收口闸计数日志 + blend=0 显式标注 + 诊断证据/工具入库（**行为零回退**，只加日志与证据）
- **已入库 (main)**: 修代码 `tools/intact_direct_rollout.py` · GUI 收口 `tools/gui/simulink_module.py` ·
  诊断工具 `tools/diag_l4_stall.py` / `tools/diag_intact_zero_act.py` · 报告 `reports/L4_4000_STEPS_ROOTCAUSE_20260915.md` ·
  逐步轨迹 `reports/diag_l4_*` · 技能全量镜像 `docs/skills/hermes-all` (155 技能/1119 文件) + `docs/memory` 记忆备份
- **未入库（按"大文件不进代码库"纪律，仍在磁盘）**: `reports/evidence_*/` · `reports/intact_sw/video/` · `reports/mem_ladder/video/`
  = 717MB 的 mp4 证据（其中本次成功视频已上传 https://datadrive.world/models/l4_model_gated_v4_seed104.mp4）
- **无训练在跑**、GPU 空闲、INTACT 用 CPU；auto_loop 守护在跑（队列空）

## ⏭ 下次启动第一步（照旧 + 新增）

1. `date` 对时间；2. `hermes cron status` / `hermes cron list` 确认 next_run 在未来；
3. 打开 GUI 目检 **L4 档**：日志应出现 `🛡 L2 收口闸: 共 N 步 · …` +（若 blend=0）`⚠️ 本轮模型提案一次都没通过收口闸`，
   并跑完 13 段（接近→…→AOI→完成）**done=True + AOI ok**；
4. 继续 §6 三条口径验证（goal 前瞻口径 / 动作历史 raw-vs-normalized / 闭环 DAgger 再训）→ 让闸门按 cos 自动放权。

> ✅ **2026-09-15 08:55 更新（静静，已定位+已修+已验）**：本清单 ①（全链卡"接近"）的**完整根因**已查明并修复，
> 详见 `reports/L4_4000_STEPS_ROOTCAUSE_20260915.md`。要点：
> · ①的真实主因不是 L2 势场（势场只作用在 u_ff 解析通道），而是 **L4 档默认走的 INTACT 直驱**：模型动作与执行层参考
>   **反向**（step1 cos −0.14）、幅度塌到 17~42% ⇒ 手朝远离光模块方向漂 82mm ⇒ 600/4000 步停在"接近"、grasped=False；
> · 叠加**静默 bug**：直驱推理任何异常被吞成"零动作"（`_dact_cache = zeros`）⇒ 手完全不动但日志只有"接近/grasped=False"；
> · 修 = ①L2 收口闸扩展到直驱路径（阶段白名单 + 方向/幅度/一致度否决 + 收窄不放大 + 夹爪由执行层）②异常不再写零动作、
>   显式报错并交回执行层 ③GUI 直驱装配后关掉 u_ff 重复注入通道。**验证**：同 seed/同干扰 L4 档 4000 预算下
>   **879 步 done=True + AOI ok（13 段全过）+ 真推理 879 次**，视频 `reports/l4_model_gated_v4_seed104.mp4`。
> · ⚠️ 仍开放：闸门今天**全否决**（模型闭环一致度一次没到 0.9）⇒ "模型独立干完"还不成立；下一步按 §6 的三条口径
>   （goal 前瞻口径 / 动作历史口径 / 闭环 DAgger 再训）验证与推进。②INTACT 仍 CPU（≈0.11 s/步，879 步 ~100s）未动。

> 背景：老倪在 GUI 里跑全链（mode=full + L4 档）时，日志 `[900~1075/4000] 阶段=接近 grasped=False 残差恒定 0.055~0.059`
> —— 不是慢，是**卡住空转**。已按指示：关掉 L2 记忆层 + 停掉该 run + 关机。**下次启动再修。**

## ① 主问题：L2 记忆层势场把动作抵消成 0（已临时处置，待真修）

**现状**：`data/memory_layers.json` 的 `L2` 已置 **0**（原状态备份在 `data/memory_layers.json.bak-20260915`）。

**证据（同配置桥运行的实测日志，2026-09-15 07:00 前后）**：
```
🧲 记忆层介入 step=1650 技能=SK07 w=0.381 conf=0.0
   模型=[-0.101, -0.019, 0.019]   场=[0.164, 0.031, -0.032]   → 合成=[-0.0001, 0.0001, -0.0002, 0.75]
```
模型往一边推、势场往另一边拉，**合成速度 ≈0.0001 m/s ⇒ 手不动 ⇒ 阶段永远停在"接近"**（正常"接近"约 40 步就进"对位"）。

**修复方向（与既有 L4 收口闸同一类问题，可直接复用思路）**：
1. `blend_action` 加**方向一致性约束**：当 `cos(u_model, −∇Φ) < 0`（场与模型反向）时，把 `w` 置 0（场不夺权）——等同 L4 闸的 `l2_veto_dir` 逻辑；
2. 场贡献按 `|u_model|` 归一/限幅，避免远场罚项压过模型幅度；
3. 检查 `conf ≡ 0` 时 `w_far` 增益调度是否误触发（`conf=0` 却 `w=0.381` 说明走了 far 分支）。

**验收判据（必须做，不许只凭现象）**：
- 关 L2 跑 full + L4 档（4000 预算）：正常应 **850~1000 步内 done**（引擎 `run()` 文档口径）；
- 开 L2 同 seed 同预算重跑：若又卡"接近" ⇒ 确认 L2 是元凶；
- 修完后：**L2 开局时不得让任何阶段的 `|u|` 小于"关 L2 时"的 10%**（防再次抵消），并出 A/B 对照表。

## ② 提速：INTACT 推理还在 CPU

现状 `intact_worker.py --device cpu`：单次前向 ≈**1.4 秒**、每 8 步一次 ⇒ 实测 **≈3.6 步/秒**，4000 步要 ~18 分钟；GPU 全程 **0%**。
- 动作：改 `INTACT_DEVICE=cuda`（或桥/节点的 device 参数），先验证：同权重同帧 CPU/GPU 输出逐位/数值一致 + 吞吐对比；
- 注意历史坑：ckpt 预处理器里 device 曾写死 cuda（已加 `SS_L3_DEV` 覆盖 + 熔断），反向切 GPU 时要一并复验。

## ③ 步数预算口径（备忘，不用改）

引擎 `run()`：insert 档 1000 步；**full 档 + L4 档 = 4000 步**（自主恢复预算 ×2，正常成功 850~1000 步的 4 倍）。
→ 看到 `[x/4000]` 就是 full + L4，不是"必须跑满"；跑满即代表一直恢复不了。

## ④ 开机后三步（每次开机都做）

1. `date` 对时间（本机曾出现开机 NTP 拨钟偏差 7.5h）；
2. `hermes cron status` → 应显示 Gateway running + 13 active；`hermes cron list` 确认 next_run 都在未来；
3. 需要小芳新数据时再起守护：`cd ~/lerobot-smolvla-lew && ~/lerobot-venv/bin/python tools/auto_loop.py >> outputs/auto_loop.log 2>&1`（后台）。

## 结转（本次关机时的状态）

- 版本 **v5.6.1**；远端 main = `85da4aa3`（记忆与全部技能已共享：`docs/memory/`、`docs/skills/hermes-all/`）
- L4 光模块插拔链桥已跑完：`reports/intact_sw/status.json` = done / step 1799 / 解析链 1/2 · 模型直驱 0/2
- 无训练在跑、GPU 空闲、磁盘 282G/300G
