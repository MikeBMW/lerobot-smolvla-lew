---
name: zmax-console
title: "Z-MAX Console"
description: "Maintain PyQt5 GUI studio.py: version, Docker, backup, docs sync, PPT engine, auto-update."
trigger: "Use when the user mentions '控制台', 'Console', '远程GUI', '迭代控制台', or 'studio.py' — PyQt5 desktop, NOT web console.html."
---

# Z-MAX Console — 维护指南

> 📌 refs: veh-id-system,ssh-remote-gpu,config-center-excel,relay-middleware,simulink-id-and-skill-tokens,wsl-display-links,simulink-flow-json,gui-navigation,devflow-panel-pdf-2026-08-15
> ⚠️纪律: 只patch改; kill-9重启(pkill 用 "gui-venv311/bin/python studio" 别用 studio.py, 会打死 Hermes 自己的 shell); --gpus all本地/--runtime nvidia远程; -o Port; 主线程禁网络请求(摄像头坑); 启动/黑屏见 launch-guide.md; 训练入口/状态见 gui-navigation.md; 控件小/字挤/面板窄见 ui-sizing-hidpi.md; refs: gui-discipline, simulink-flow-and-buttons, simulink-flow-authoring, help-menu-doc-open

## 架构速查

```
tools/gui/
├── studio.py              # 主程序 (PyQt5) — 入口
├── docs_sync.py          # 文档同步系统 (GitHub API + 分类 + 版本追踪)
├── ppt_engine.py         # PPT 指令引擎 (PPT作为控制台指令源)
├── update_checker.py     # 自动更新检查 + 下载升级
├── Dockerfile             # 轻量 X11 挂载容器化
├── Dockerfile.win         # Wine 交叉编译 (备选)
├── docker-run*.sh
├── version_sync.py        # 版本信息面板
├── training_backend.py    # 训练后端
├── hardware_simulator.py  # 硬件仿真
├── inference_client/server.py
├── dataset_viewer.py
├── le_robot_studio.py     # 简化版
└── le_robot_home.py

.github/workflows/
├── docker-console.yml     # CI: tag v* → build → push 阿里云 ACR
└── build-win-exe.yml      # CI: tag v* → PyInstaller .exe → Release
```

**三层解耦架构**: Sys-0 ← Sys-11+12 ← System 2

**9 大模块**: 系统架构 / 数据集 / 训练 / 推理服务 / 硬件仿真 / 评估 / 配置中心 / 实时监控 / 插拔场景

## 常见操作

> 📄 全部常见操作 (训练/评估/视频/报告/飞书/配置表/画布节点/数据集 等) 见
> `references/common-operations.md` — 2026-08-25 从本文件拆出 (SKILL.md 曾撞 10 万字符上限)。
> UI 尺寸适配 (按钮太小/字挤/面板太窄/高分屏) 见 `references/ui-sizing-hidpi.md`
> (含实测探针 `tools/probe_ui_metrics.py`)。

## 陷阱
> 📌 三模型对比 2026-08-05 下半场完整细节 (LEW 旁路/性能扩展 P50·平滑度/连线标签/删双模型/CrossAttn K-V 注入/ARPredictor 拆解/子系统总系统/参考应用滚动条/验证脚本坑) 见 `references/three-model-compare-v2.md`。新增入口功能必须给第二行工具栏按钮 (老倪找不到 = 没做)。
- **reference 索引**: Simulink 架构演进 (三模型对比/子系统/CrossAttn/数据流标签/8指标/去重) 详见 `references/subsystem-crossattn-3model.md`; 旧双模型/MDI/浮动见 `references/act-smolvla-compare-mdi.md` (部分 deprecated)。
- **重新采集/要新真机数据 = 只能飞书 @小芳 (2026-08-03 实测, 老倪 "重新采集吧")**: Orin (192.168.23.10) 在 Mac 局域网内, **4060/WSL 侧 ping 不通、SSH 不可达** (zmax_auto_collector.py 是 MAC 端守护, collect_upload_npz.py 是旧占位脚本无真机能力) — 真机采集只能由小芳在 Mac/Orin 侧触发。触发方式 = 飞书 dataworld 群发消息 @小芳: ① `POST open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal` (json: app_id=cli_a87851ffe46b500d, app_secret 从 ~/.hermes/*.env 的 FEISHU_APP_SECRET 读) 拿 tenant_access_token; ② `POST open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id` (header Authorization: Bearer <tok>, json: receive_id=oc_c0b4048546145c5c581ddd1a9e8f565d, msg_type=text, content=json.dumps({"text": 消息}) 且 ensure_ascii=False)。消息里写清: 请用 Orin 采集 → Mac 中转 (192.168.23.1:8769) → ECS relay (datadrive.world/api/relay), 并报当前队列包数/最近落地时间让对方知道现状。发送后回执 200 + code=0 即成功。**别试 SSH/直连 Orin — 必失败; 也别假设 auto_loop 能自己拉新数据 — 队列空就是没新包**。
- **auto_loop 闭环守护 = 数据到自动全流程 (2026-08-03 实证)**: 本地 `tools/auto_loop.py` (60s 轮询 relay /status) 数据闭环已全自动: 小芳上传 → auto_loop 拉取 (存 data/orin_live/auto_<ts>.json, 含 meta.source/frames/n_joint/n_action) → frames≥50 自动训练 (act_loop, 2000步 ~2.5min) → 训练完自动推模型回 ECS (cicd_deploy.py push 等效) → 小芳拉取部署 Orin。实测 20:26 89帧 / 20:38 107帧 两轮全自动完成, 日志在 outputs/train/loop_train.log。**老倪问"拉了么"时先看 auto_loop 进程日志 + data/orin_live 最新文件** — 数据可能已被守护自动取走, 队列空 ≠ 没采集, 而是闭环已消费。relay 新加的 /command 端点可让 4060 主动触发 Mac 端采集 (见 §12)。**frames=0 空包 (2026-08-04 实测)**: relay 队列里的 0 帧包 (如 pkg_20260804_075806.json) 会一直被 /status 列为 latest, auto_loop 每轮轮询重复打 `📥 新数据: <包名> | frames=0` — 是数据侧问题不是守护故障 (0 帧不触发训练); 要清就调 /latest 弹掉。
- **多分身共享同一 git 仓库并行工作 (2026-08-02 实测)**: 飞书端 gateway agent (另一 Hermes 会话) 与 CLI 静静共用 `~/lerobot-smolvla-lew`, 它会 `git add -A` 提交整个工作区 — 你改到一半的文件可能被它一并提交 (git log 出现你没见过的 commit, 工作区突然 clean)。**改代码前先 `git status` + `git log --oneline -3` 确认**, 别假设工作区是上次会话留下的; 提交前 diff 确认自己的改动在里面。两方同时改同一文件会互相覆盖 — 关键文件 (simulink_module.py / cicd_pipeline.py) 改动后立即 commit, 别攒着。
- **工具栏按钮显示不全 (2026-08-02 用户两次反馈 "CICD 那个按钮，显示的不全" / "3阶段这几个按钮的文字显示，看不全")**: QHBoxLayout 空间不足时按钮被压缩 → 文字截断省略。**正确解法 = 双行工具栏** (仿真控制一行 + CI/CD 操作独立第二行, 按钮文字保持完整如 "🔗 CI/CD 全链路"、"🎯 三阶段管线"), **不要缩写按钮文字** (用户反馈的是"看不全", 缩写是错误方向)。配套: spinbox setMaximumWidth(70/62)、标签短名 (时间/dt)。验证: offscreen 断言 `btn_cicd.text()` 完整 + `btn_run.mapTo(w)` y 坐标在 btn_cicd 之上 (两行独立)。commit 8fb74424。
- **控制台歧义**: web console.html vs 桌面 studio.py。远程GUI=后者。
- **功能重复必须合并, 单一入口 (2026-08-02 用户两次纠正: "CICD全链路打开后, 和数据闭环CICD控制台, 感觉功能重复了" → "那后面的 验证 集成 训练 部署这几个按钮, 是不是也重复")**: 老倪对控制台的 UI 铁律 = **一个功能一个入口, 绝不重复**。本会话落地:
  1. 删「🔗 CI/CD 全链路」按钮 (btn_cicd) —— CICDPanel 与 PipelinePanel 功能重叠 (都是 CICD 主题 + 全流程 + 日志), 合并进数据闭环控制台。CICDPanel 类保留 (open_cicd_panel 兼容), 但入口移除。
  2. 删工具栏第二行「✅ 验证 / 🚀 训练 / 📦 集成 / 🚚 部署」4 按钮 —— 与控制台内 6 环节按钮重复。**删按钮必须同步清理引用**: `_start_worker` / `_run_node_stage` 里的 `for b in (self.btn_validate, ...): b.setEnabled(False/True)` 会 AttributeError 崩 (btn 没了)。防重入靠 `_worker.isRunning()` 已足够, 按钮禁用循环直接删。删除后 `grep -cn "btn_validate\|btn_integrate\|btn_deploy"` 应为 0。
  3. 最终形态: 工具栏第二行只剩「🎯 数据闭环控制台」一个 CICD 入口 + 提示文字; 控制台面板 = 闭环状态栏 (5项, 10s 轮询) + 6 环节流水线按钮 (带状态色 1青/2绿/3红, 点击执行) + ▶流水线全流程 + 三阶段卡 (steps 可配) + ▶三阶段全流程 + 日志。
- **环节/按钮数量变更的连锁检查 (2026-08-02 崩溃实测, commit fc25a45f 延伸)**: 加环节/删按钮后 grep 三类残留: ① 硬编码环节标题 dict (`dict(validate='① 验证', ...)[sid]` → KeyError 崩, 改从 `self._stages` 动态取); ② `for b in (self.btn_xxx, ...)` 按钮引用; ③ NODE_RUN_ACTIONS / REFERENCE_APPS 计数。改完 offscreen 逐个 `_on_stage_clicked(sid)` / `_pipe_btns[sid].click()` 断言不抛异常。
- **新增按钮必须 addWidget 挂布局 (2026-08-05 老倪: "没有三模型对比啊, 只有之前的两个模型的对比", commit 6a3ef710)**: btn_compare3 用 `mk_btn(...)` 创建后**忘记 `tl2.addWidget(self.btn_compare3)`** — 按钮对象存在 (offscreen 断言 `btn.text()` 都对) 但从未挂进任何布局 → **界面上完全不可见且无任何报错**。排查: `grep -n "btn_xxx =" 看创建行, 再看有没有对应的 addWidget 行`。**这是「删按钮必须清理引用」的镜像教训: 加按钮 = 创建 + 连接 + addWidget 三件事, 少一件都静默失败**; 验证必须 `assert btn.parent() is not None` (挂到布局) + `btn.click()` 后行为生效, 别只断言对象存在。**配套 (同一会话)**: 第一行工具栏按钮已 10+ 个会被 QHBoxLayout 挤压省略 → 新按钮放第二行工具栏 (🎯数据闭环控制台/🧠ACT-Meta引导/🔬三模型对比同排), 别堆第一行 (同"双行工具栏"教训 8fb74424)。
- **▶运行 = 画布真实全流程 (2026-08-04 v1.5.0 行为变更, commit 85f698b2, 老倪: "上边的运行按钮,不能启动整个流程么?" / "根据引导提示,我是刚刚建立了一个流程模型,应该由运行启动整个流程")**: `start_sim()` 开头检测 `_canvas_stage_nodes()` (画布上匹配 NODE_RUN_ACTIONS 的环节节点, 按 `_topo_sort()` 依赖序) — **有环节节点 → `_start_canvas_flow(stages)`**: 日志 "▶ 真实全流程启动 (N 环节): 「训练」→「验证」…" → 节点全部重置 idle → `_flow_queue = [lambda: self._run_node_stage(n, getattr(self,m,None), k) ...]` (闭包捕获 n/m/k!) → `_flow_next()` 启动 → worker `_done` 末尾自动 `_flow_next()` 流转下一个 → 走节点逻辑 (node_logic.py 可修改区参数生效)。**无环节节点 → 原拓扑仿真不变**。⚠️ 旧记录 "▶运行≠训练" 已作废 — 排查"我是在训练吗"改为看日志 "▶ 真实全流程启动" vs "▶ 仿真开始" + `ps aux | grep lerobot_train`。验证 (offscreen 8/8): ACT-Meta 画布(1环节) → start_sim 只跑训练节点且 fn=on_train; 无环节画布 → `_sim_running=True` 仿真; CICD 主控台 4 环节拓扑序 训练<验证<集成<部署。

**📊 Scope 示波器节点 (2026-08-04 v1.6.0, commit 76f91218, 老倪: "需要最后出一个结果报告,类似simulink的scope示波器,能看到效果" + "最后增加一个scope的节点,对不?")**: Simulink Scope 对标 = 流程末尾接观察节点, 训练完双击看波形, **不是全流程结束自动弹报告**。
- ACT-Meta 模板 8→9 节点 (训练→📊 Scope), 引导 ACT_BUILD_STEPS 8→9 步 (文案 第N/8步→第N/9步, _act_build_finish 的 8/8→9/9 且 len(nodes)>=9), LIBRARY ACT 分类加 Scope 条目, NODE_RUN_ACTIONS 加 ("Scope","on_scope"), node_logic 加 node_scope 注册。
- **loss 曲线收集**: `_run_cmd(cmd, collect=list)` 可选收集原始行 (逐行 append), on_train 传 collect → 训练完 `_parse_loss_curve(out_lines)` 宽松正则 (`step N ... loss: X` 或 `loss=X step=N` 两种都认, dedup by step) → `self._train_curve = [(step,loss)]`。
- `on_scope()` → `FlowScopeDialog` (simulink_scope.py 追加): ScopeWidget 画 loss 青色曲线 + 指标行 (loss 首→末/下降%/采样点/步长) + 💾导出PNG (固定存 reports/scope_loss_<ts>.png, **不用 QFileDialog — 深色黑字坑**, 直接 QMessageBox 深色提示路径)。无数据 → "⚠️ 暂无训练曲线" 提示 + 导出禁用。
- **⚠️ Scope 必须排除出自动流程**: `_canvas_stage_nodes` 里 `if "Scope" in name: continue` — 否则 ▶ 运行会执行 Scope 节点 (弹窗阻塞队列)。Scope 是观察节点, 永远手动双击。
- 验证 (offscreen 15/15): 模板 9 节点 9 连线 + Scope 在末尾 + links[-1]==(7,8); 引导 9 步; loss 解析 3 点含两格式; ▶ 运行环节=仅训练; Scope 双击弹窗; FlowScopeDialog 曲线/指标/导出/无数据提示; node_logic scope 路由。

- **⚠️ 交互模式/主题不擅自翻盘 (2026-08-05 老倪连续回滚两次: "取消打开独立窗口功能,不对" + "还是用暗色调风格;你改的不好看")**: 老倪对"窗口形态"(嵌入式 MDI vs 独立浮动)与"主题色"有强既有偏好 — ① ACT-Meta 独立浮动窗口 → 回滚嵌入式主画布; ② Simulink 浅色主题 → 回滚暗色调 (浅↔深切换机制保留, 默认 dark)。**通用教训: 强视觉/交互偏好的改动, 先按现状 (深色+嵌入式) 做增量或给切换开关让用户自选, 别一次性翻盘; 被回滚的方向记在技能里避免下次再犯**。
- **live_monitor/data_sync 训练入口冲突 (2026-08-02)**: `tools/live_monitor.py` 和 `tools/data_sync.py` 用**固定** config_act_mw_v111.yaml (output_dir=act_mw_v111) 触发训练 → 目录已存在必 FileExistsError (日志: outputs/train/live_train.log)。这两处也要时间戳 output_dir (同 on_train 的 re.sub 模式)。训练产物目录名不匹配 `act_<时间戳>` 规则 (如 act_finetune) = 不是 GUI on_train 触发的, 排查时先认目录名。
- **CICD 主控台 (2026-08-02)**: 老倪要求"控制台是主控点，node 上有所有链路主要 node 能运行；既有 metaworld 又有 Orin 又有 ACT，可随意切换训练"。落地 = REFERENCE_APPS[0] = "🎛 CICD 主控台" **7节点6连线** (Orin源+metaworld源 → 🔀Switch → ACT训练 → 验证 → 集成 → 部署)，节点双击即运行/切换。⚠️ **REFERENCE_APPS 首位已不是 "⚙️ CI/CD 默认流水线"** — 旧文档/旧测试若假设 `open_cicd_panel()` 加载 3 节点会 FAIL，现在是 7 节点。⚠️ **新节点类型必须三处同步 NODE_TYPES**: simulink_module.py + tools/ci/validate_flow.py + tools/gui/simulink_ci.py (两个验证器各有独立枚举, 漏改 → validate --strict 报 "类型非法" rc=1, 本会话实测踩过); 改完跑 `simulink_ci.py test` 内置回归。完整实现细节见 `references/master-console.md`。
- **修改 GUI 代码后必须重启控制台 (2026-08-02 用户催 "你修改完了，要重新打开控制台"; 2026-08-04 再催 "你没重启控制台")**: 改完 simulink_module.py / studio.py 后旧进程还在跑旧代码, 用户看到旧行为以为没改。流程: offscreen 验证 → `pkill -f "tools/gui/studio.py"` (确认 `ps aux | grep studio.py | grep -v grep | wc -l` == 0) → `cd ~/lerobot-smolvla-lew && python3 tools/gui/studio.py` (terminal background=true) → sleep 6 确认进程活着。**汇报必须带证据三连: 新 pid + 启动时间 + 窗口标题版本号 (`grep -n "v1.5.0" tools/gui/studio.py`)** — 用户会主动质疑 "你没重启控制台", 即使用户当时操作的进程已含新代码, 也别辩解, 直接干净重启一次 + 给 pid/时间/版本证据。操作顺序 = 修改 → 验证 → 重启 → 推送。⚠️ **pkill 自杀 (2026-08-02 实测 exit -15; 2026-08-04 复踩)**: `pkill -f "studio.py"` 所在命令行的 bash 进程本身也含 "studio.py" 字符串 → pkill 匹配到 shell 自己把自己杀了, 后续命令 (git commit/push) 全部没执行。**2026-08-04 复踩细节: 即使 pkill \"单独一条 terminal 调用\", 命令里带 `pkill -f "tools/gui/studio.py"; sleep 2; ps ...` — bash -c 的整条命令行含目标字符串, 一样自杀 (exit -15), pkill 杀完目标进程后 shell 也被杀, 后面 sleep/ps 全不执行**。**正解 = 方括号技巧 (同 §12 relay pkill)**: `pkill -f "[s]tudio.py"` — 命令行里没有明文 studio.py (是 [s]tudio.py), 不匹配自己; 目标进程命令行是明文 "python3 tools/gui/studio.py" 仍匹配。验证: `ps aux | grep "[s]tudio.py" | grep -v grep | wc -l` 归 0 后重启。原则: 命令行里绝不能出现目标进程的明文名字 (pkill/grep 都不行), 一律 [x] 技巧; 重启与 git 推送分两条命令。
- **offscreen 验证 CICDWorker 别造 FakeWorker (2026-08-03 实测)**: log/finished 是**真 pyqtSignal**, 自定义 FakeWorker 类给 `log = None` 会在 `worker.log.connect(...)` 处 AttributeError 崩 (`'NoneType' object has no attribute 'connect'`)。正确做法: monkeypatch `CICDWorker.start = lambda self: None` 防真线程启动, 其余走真实类 (信号对象齐全)。防重入验证用假 worker 对象: `class FakeRunning: def isRunning(self): return True` 赋给 `w._worker` → 调 on_xxx() → 断言引导 step 不变。
- **offscreen 验证 QThread 异步信号 (2026-08-02 实测 3 轮才过)**: CICDWorker(QThread) 的 finished_ok/finished 是 queued connection — worker 线程跑完 ≠ 主线程 slot 已执行。断言节点 status 变化必须:
  ```python
  deadline = time.time() + 4
  while time.time() < deadline and node.get("status") != "success":
      app.processEvents(); time.sleep(0.02)
  ```
  只等 `not worker.isRunning()` 会过早 break (worker 已结束但信号未处理), 误报 FAIL。验证脚本还要 monkeypatch 掉 on_train/on_validate 等真实执行器 (换成 `lambda: (True, "mock")`) — 否则 on_train 真会去拉 relay/起训练, 产生网络副作用。
- **git fetch/push 卡死 (WSL)**: `git fetch` 长时间无输出、timeout 死掉，但 `curl -sI https://github.com` 正常 → 用 `git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 fetch origin main` 或后台跑 `git fetch` (notify_on_complete)。诊断顺序: `timeout 20 git ls-remote origin` 通 = 网络/认证 OK，问题在 pack 传输; fetch 成功后 `git log origin/main --oneline -3` 确认拿到了远端。rebase 中途超时会留 `<<<<<<<` 冲突标记并污染工作区 → `git rebase --abort` 恢复。
- **merge -X theirs 覆盖本地集成点**: `git merge origin/main -X theirs` 会用远端版本覆盖本地对同文件的改动 (Simulink 集成点 4 处全丢, 页面消失但模块文件还在)。合并后必须 `grep -n "simulink" tools/gui/studio.py` 验证。rebase 冲突多 (同批文件被远端大改) 时: `git rebase --abort` + `git merge origin/main -X theirs --allow-unrelated-histories` 更干净。
- **WSL 显示中文方块 (乱码)**: 根因是 WSL 无 CJK 字体。`sudo apt-get install -y fonts-noto-cjk && fc-cache -f` 后 `fc-list :lang=zh | wc -l` 应为 30+。用户看到"方块"第一反应是编码问题，实际是缺字体。
- **WSL Qt xcb 插件崩溃**: `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"` → 装 `sudo apt-get install -y libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-render-util0 libegl1`。系统 python 无 PyQt5 时 `pip3 install --break-system-packages PyQt5 numpy` (PEP 668 环境)。PyQt5 首次装在本机系统 python (Docker 里才有) — 别假设系统已有。
- **PyQt offscreen 验证**: `QT_QPA_PLATFORM=offscreen` 可无显示跑 GUI 单测。验证脚本必须用**系统 python3** (execute_code 的 sys.executable 是 Hermes venv 无 PyQt5, 会误判 exit 1); 模态 QMessageBox 必须 monkeypatch `_qmsg/_qmsg_yes` 防 exec_ 阻塞; palette 断言 ≠ 渲染, 先渲染采样像素。完整模板 + 排查顺序见 `references/offscreen-verify.md`。
- **⚠️ 192 DPI 高分屏 offscreen 误判 (2026-08-22 v2.4.0)**: U盘 Xorg 3200x2000 高分屏 logicalDotsPerInch=192, 字体渲染=offscreen默认96DPI的2倍 → offscreen 测的 sizeHint 只有真实一半, 硬编码 setMinimumHeight/setFixedHeight 在真实屏幕被裁 (标题需54px/描述63~91px, 症状="显示不全")。**铁律: 验证 UI 像素尺寸必须真实 DISPLAY=:0 跑, offscreen 只测逻辑/拓扑/字符串**。修法=弃硬编码改自适应 (setWordWrap + QSizePolicy.Preferred 弃 setFixedHeight, 同行自动等高)。诊断: xdpyinfo resolution + primaryScreen().logicalDotsPerInch()。详见 references/hidpi-192dpi.md + font-rendering-pitfalls.md + row-bg-layout.md。
- **⚠️ QMessageBox 黑字根治 (2026-08-04 用户两次反馈 "提示框里全是黑色字体, 看不清" — commit c14c1ae1 才解决)**: 第一轮把 QMessageBox.question/information/warning 静态调用换成 `_qmsg` 辅助方法 (手动构造 + setStyleSheet(DIALOG_SS) 深色背景白字) **用户反馈仍黑** — 因为 WSLg/Windows 下 QMessageBox 和 QToolTip 走**系统原生渲染, QSS 不生效**。根治在 studio.py `main()` 里两处: ① `app.setAttribute(Qt.AA_DontUseNativeDialogs, True)` (在 `app = QApplication(...)` 之后、setStyle 之前) 强制 Qt 自绘, 全局 QSS 才对所有对话框生效; ② QToolTip 见下方专项。**⚠️ QMessageBox 没有 setOption/DontUseNativeDialog (那是 QFileDialog 的 API, 调用 AttributeError)** — QMessageBox 是 Qt 自绘控件, setStyleSheet 直接生效, 唯一敌人是原生渲染开关 AA_DontUseNativeDialogs。验证: offscreen 断言 `QMessageBox.exec_` monkeypatch 捕获的 styleSheet 含 "background:#0d1117" + "color:#fff"。
- **⚠️ QToolTip 黑字最终方案 = 自绘气泡, palette 也管不住 (2026-08-04, commit d583a2d6, 老倪第三次反馈 "提示框里还是黑色字体")**: 第一轮用 `QToolTip.setPalette()` (ToolTipBase 深色 + ToolTipText 白) 实测仍黑 — **QToolTip.showText() 是系统原生气泡, WSLg 下 palette 也不生效**。最终放弃 QToolTip 全家: simulink_module.py 的 `_tutorial_hint_mismatch` 里 `QToolTip.showText(...)` 换成自绘浮层 `_show_bubble(global_pos, text, ms=4000)` = `QLabel` + `setWindowFlags(_Qt.ToolTip | _Qt.WindowStaysOnTopHint | _Qt.FramelessWindowHint)` + `setStyleSheet("QLabel { background:#0d1117; color:#e6edf3; border:1px solid #00d4aa; border-radius:6px; padding:10px 14px; font-size:12px; }")` + adjustSize + move(全局坐标-宽/2, +16) + show/raise_ + `QTimer.singleShot(ms, lambda: self._close_bubble(bub))`。`_close_bubble` 用 `if getattr(self, "_bubble", None) is bub` 防误关新气泡。**通用原则: 任何"气泡提示"在 WSLg 下都不要用 QToolTip (原生渲染黑字无解), 一律自绘 QLabel 浮层; 消息框用 AA_DontUseNativeDialogs + setStyleSheet 深色**。用户对黑字 UI 反馈最多三次, 每次都是"上轮没改到位" — 排查时先问自己"是不是还有别的弹窗路径没覆盖" (主窗口 45+ 处 QMessageBox / QToolTip / QFileDialog / QInputDialog / QMessageBox.about 全要查)。
- **⚠️ 右键菜单"没反应" = WSLg 下 QGraphicsSceneContextMenuEvent.screenPos() 坐标异常 (2026-08-04 老倪 "右键没反应", commit bee335bf)**: 在 QGraphicsItem.contextMenuEvent 里用 `menu.exec_(e.screenPos())` 弹菜单, WSLg 虚拟屏下 screenPos 返回异常坐标 → 菜单弹出在屏幕外 → 用户看到"右键没反应" (菜单其实弹了)。**正解: 右键统一在 SimCanvas.mousePressEvent 处理** — 加 RightButton 分支: `item = self.itemAt(e.pos()); if isinstance(item, SimNodeItem): self._show_node_menu(item, e.pos())`, 菜单坐标用 `self.viewport().mapToGlobal(e.pos())` (viewport 事件坐标, WSLg 可靠); **同时删掉 SimNodeItem.contextMenuEvent** — 系统 QContextMenuEvent 与 canvas 分支会双弹, 且 item 级只能拿到 scene event 的 screenPos。菜单本身必须显式深色 QSS (`QMenu { background:#161b22; color:#e6edf3; ... } QMenu::item:selected { background:#1f6feb; color:#fff; }`) — QMenu 属 QToolTip 黑字家族, 别指望全局 QSS 兜底。**验证坑: QTest.mouseClick(viewport, Qt.RightButton) 不产生系统 QContextMenuEvent** — 它只发 mouse press/release, 而 QGraphicsView 的右键菜单走系统 context-menu 事件链, offscreen 下无法触发 item.contextMenuEvent; 测试右键必须走 mousePressEvent 分支 (canvas 接管后 QTest 直接可测: monkeypatch QMenu.exec_ 捕获菜单项 + monkeypatch on_show_node_logic 防 dialog.exec_ 阻塞; 右键空白处断言不弹菜单)。QGraphicsSceneContextMenuEvent 不能直接实例化 (PyQt 报 cannot be instantiated), 别试图手工构造它。
- **⚠️ 批量替换 QMessageBox 静态调用 = 括号配对扫描, 别用正则 (2026-08-04, commit 9349e5a5)**: studio.py 主窗口还有 **45+ 处** `QMessageBox.warning/information/critical/question` 静态调用不走深色 (只改 simulink_module.py 的引导框没用, 用户点主程序任何功能仍黑字)。批量替换时**正则必踩两坑**: ① `re.sub(r'QMessageBox\.warning\(self,\s*([^,]+),\s*(.+)\)', ...)` 的 `[^,]+` 遇含逗号的多参调用 (带 Yes|No 按钮参数) 会把 `main(, kind="warning", kind="critical")` 这种坏代码拼出来 → SyntaxError; ② `(.+)` 贪婪 + re.S 会跨行吞到下一个 `)` 把中间代码全吃掉。**正确做法: 逐字符括号配对扫描** — `find_calls(src)`: 定位 `QMessageBox.` → 读方法名 → 从 `(` 起 depth++/`)` depth-- 找匹配右括号 → 提取 args; `split_top(s)`: 按顶层逗号分割 (跳过括号/引号内逗号)。然后按方法名 + 是否含 Yes|No 分类替换: question 或带按钮 → `_msg_ask(parent, title, text)`; warning/critical → `_msg_ok(parent, title, text, kind=...)`; information → `_msg_ok(parent, title, text)`。**从后往前替换** (保持前面索引有效), 替换完 `ast.parse` 验证, 残留引用 grep 确认只剩 `reply != QMessageBox.Yes` 比较 (配合 _msg_ask 返回值没问题) + 自定义按钮 addButton (深色 QSS 覆盖)。QMessageBox.about 单独处理: 手动构造 mb + setTextFormat(RichText) + setStyleSheet(_MSG_SS) + addButton(Ok) + exec_。**教训: 修改后必须重启控制台且用户在真实窗口验证 — offscreen 断言 styleSheet 字符串 ≠ 用户屏幕上真的白字, 黑字类 UI 问题要一次到位 (AA_DontUseNativeDialogs + palette + 全量替换), 别分三轮让用户反复反馈**。
- **merge 后 `AA` 状态**: rebase 中断 (rebase-merge 目录残留) 会让文件呈 AA (both added) 状态且工作区被污染 — 先 `git rebase --abort` 恢复干净再换策略。
- **版本号三处**: 必须同步更新，tag 必须新号。
- **Zone.Identifier**: Windows runner checkout 失败。git rm --cached + .gitignore。
- **torch依赖**: _TORCH_AVAILABLE try/except 优雅降级。
- **HomeWidget信号**: 子 Widget 不能直接调主窗口。用 pyqtSignal(str) + emit + connect。
- **打开文档目录**: 先 os.makedirs(path, exist_ok=True)。
- **帮助菜单 frozen**: 打开 GitHub docs URL，文件靠同步下载。
- **新增模块**: 三处同步更新。
- **notify.php**: getenv 写成了字符串。

### 17. 录屏 (用户要求"帮我录屏，把控制台窗口所有渲染录下来", 2026-08-02 实测)
用户要看控制台操作演示时用 ffmpeg x11grab 录 DISPLAY=:0 (WSLg):
```bash
# 启动录屏 (后台, 全屏; 控制台 + 所有弹出窗口都录进去)
ffmpeg -f x11grab -framerate 15 -i :0.0 -c:v libx264 -preset ultrafast -crf 23 -pix_fmt yuv420p ~/recordings/studio_$(date +%H%M%S).mp4 2>/tmp/ffmpeg_rec.log
# 结束: kill 后台进程 → ffprobe 验证 duration/size
ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=1 <mp4>
```
**关键坑 (实测踩过)**: 指定 `-video_size 1920x1080` 超 WSLg 虚拟屏实际尺寸 → `Error opening input file :0.0.` (Invalid argument)。**不要带 -video_size, 用默认自动检测**。探测是否可录: `ffmpeg -f x11grab -i :0.0 -t 1 -f null -` (不带尺寸, 有 frame 输出=OK)。
- 交付: 告诉用户文件路径 + ffprobe 时长/大小; WSL 侧路径 `~/recordings/xxx.mp4`, Windows 侧 `\\wsl$\...\recordings\`。
- 用户流程: 启动录屏 → 告知"开始点击" → 用户操作完说"结束录屏" → kill + 验证 → 交付。

**⚔️ ACT vs SmolVLA 对比 (2026-08-05, 老倪: "对比按钮改造成对比act和smolvla模型, 数据集统一metaworld, 你来决定模块划分, 同等结构的模块要复用, 让用户清晰感知哪个模块被复用了, 增加scope图表: 训练速度/精确度/鲁棒性")**:
- **⚠️ 已删除 (2026-08-05, commit dacf60b9, 老倪: "对比和三模型对比是不是重复了" 确认去重)**: 「⚔️ ACT vs SmolVLA 对比」双模型模板/按钮/open_compare 全部删除 — 双模型是三模型对比的真子集, 单入口铁律。删除后**代码级零残留验证**: `[l for l in src.splitlines() if l.strip() and not l.strip().startswith("#")]` 拼接后断言 `"def open_compare(" not in j and "self.btn_compare = " not in j` — 注释里的旧名 (如 paint 复用说明 "ACT vs SmolVLA 对比") 不算残留, 子串 count 会误报。
- **模块划分 (2026-08-05 晚修订, commit 22dbdaaf → 终态)**: REFERENCE_APPS「🔬 三模型对比」**18节点22连线** = ♻共用2 (📦metaworld数据 / 📊对比评估Scope) + ACT 8 (数据→ResNet18→CVAE→Encoder→Decoder→ActionHead·ACT→Ensemble→训练) + SmolVLA 纯动作 4 (数据→SmolVLM2→DiT-B→ActionHead·S→训练, 无LEW) + SmolVLA+LEW 6 (**主链** 数据→SmolVLM2·LEW→DiT-B·LEW→ActionHead·LEW→训练 **+ LEW 旁路** 数据→LeWorldModel(视频+动作)→ActionHead·LEW(世界预测))。⚠️ **Action Head 4D 拆成两个 (老倪纠正: "action head 4d应该是两个, 分别链接 ACT 和 somlvla, 因为是两个模型运行")** — 原共用 ActionHead 节点 (画布只画一次, 双路入线 (4,5)(10,5)) 拆为「🎯 Action Head 4D · ACT」(idx5, 接 4→5→6) + 「🎯 Action Head 4D · SmolVLA」(idx11, 接 10→11→12), 评估连线 (7,13)(12,13)。**教训: 模型拓扑别自作主张合并同构模块 — 用户视角两个模型 = 两套独立组件, 画布必须如实反映独立运行; "同构复用"只适用于真正共享的数据/评估入口**。**shared 可视化**: 节点 params.shared=True → paint 紫色 #a371f7 粗框 + ♻ 徽章 (paint 里 is_active_src/hl/shared 三分支, 顺序: hl 金框 → shared 紫框 最后覆盖)。
- **两训练节点 params.policy=act/smolvla_lew → node_logic.node_train 可修改区 `policy = p.get("policy", "act")` → on_train(policy=)**。on_train 双策略: policy==smolvla_lew → config_smolvla_metaworld.yaml + ts_dir=smolvla_<ts>; 否则 config_act_metaworld.yaml。训练完 `_parse_step_s(out_lines)` (tqdm "12.68step/s" 正则取**平均会混入噪声** — 实测 SmolVLA 平均 19.2 但真实 2.0, 修: 取最后稳定值) → 落盘 `reports/train_curve_<policy>.json` {curve, step_s, ckpt}。
- **NODE_RUN_ACTIONS**: ("对比评估","on_compare_scope") 必须在 ("Scope","on_scope") 之前 (名字「📊 对比评估 Scope」含两者, 顺序匹配优先长名)。on_compare_scope 检查两曲线文件存在 → 后台跑 `compare_models.py --frames 120` → `_done` 里 stage=="compare" && ok → 自动 `ModelCompareDialog.exec_()`。
- **▶运行环节节点 = 仅2个训练** (对比评估Scope 含 "Scope" 被 _canvas_stage_nodes 排除, 手动双击)。模板加载快: load_reference_app 批量禁 _sync (2026-08-05 性能修复: 14节点=14次 web POST 超时 → 加载期间 self._sync=lambda:None + 末尾一次 + on_flow_sync 改 threading 后台发)。**🆕 open_compare 加载后引导 (2026-08-05, commit 4b7e905e, 老倪: "点击ACT-Meta引导后, 又点击对比, 你要有提示")**: 加载完 QTimer.singleShot(300, _compare_load_hint) → 找名字含「对比评估」的节点 `_highlight_node(ms=6000)` 金框 + `_show_bubble` 白字气泡 "👆 双击金色高亮「📊 对比评估 Scope」→ 查看两模型对比图表" (气泡坐标 = canvas.mapToGlobal(mapFromScene(item.sceneBoundingRect().center())); 用 `self._items` 不是 `canvas._items` — 画布 item 字典挂在 module 级)。**原则: 模板切换类动作 (加载对比/引导/清空) 完成后必须给可见提示 (高亮+气泡), 不能只有日志 — 用户看不到 log_box 就等于没反应**。
- **compare_models.py 评估口径 (踩坑 3 轮)**: ① **必须 LeRobotDataset 加载** (root=data/metaworld_act) — npz 是 4D 但 info.json 是 pusht 模板残留 2D (state/action [2]), 训练出的两模型 checkpoint 全是 action[2]; npz 直接评估维度不匹配。② **归一化空间评估**: checkpoint config.normalization_mapping 是 None (postprocessor 反归一化失效/爆炸), gt 用数据 mean/std 归一化 `(gt-mean)/std`, 模型输出即归一化空间, **两模型都别 post 反归一化** (ACT post 后 200 量级 vs gt 233 → MSE 10万)。③ **SmolVLA select_action 有状态队列** (_queues 缓存 7 步 chunk) — 每帧必须 `policy.reset()` 否则取旧动作; ACT 无队列不用。④ 图像 batch 统一 NCHW 0-1 — tensor_to_pil 期望 CHW (内部 *255+permute(1,2,0)), 传 NHWC 报 `KeyError: ((1,1,96),'|u1')`。
- **SmolVLA-LEW 环境坑 (实测)**: lerobot[smolvla_lew] extras 装不全 → 逐个补 `transformers / num2words / diffusers` (阿里云镜像无 num2words → 直连官方 pypi)。权重 SmolVLM2-500M-Video-Instruct (~1GB, hf-mirror 无该模型 308 转直连) → `huggingface_hub.snapshot_download` 先下到缓存再训练。**加载 bug (已修 src/lerobot/policies/smolvla_lew/modeling_smolvla_lew.py)**: `_load_as_safetensor` 无条件读 `model.config.reinit_modules` 但 SmolVLALewConfig 无此字段 → AttributeError, 改 `getattr(config, "reinit_modules", None) or []`。
- **实测对比 (4060, 300步/模型, 60帧)**: 训练速度 ACT 13.0 vs SmolVLA 2.0 step/s; 动作MSE 1.40 vs 1.06 (SmolVLA 略准); 成功率 3.3% vs 3.3% (均未收敛, 300步太短); 鲁棒性(重复推理std) 0.014 vs 0.127 (ACT 稳 9x, SmolVLA DiT 采样噪声); 推理延迟 5.7ms vs 503ms (ACT 快 88x)。报告落 reports/model_compare_<ts>.json → ModelCompareDialog 双loss折线 + 五指标条形图 (训练速度/MSE/成功率/鲁棒性/延迟, 好值绿✓) + 表格, 导出 PNG 存 reports/。
- **ModelCompareDialog/BarCompareWidget 主题化**: paint 用 `_st()` (simulink_scope.CUR_THEME 由 simulink_module.switch_theme 同步); 对话框 QSS 用 `_qss()` 映射 (dark 时浅色值→深色值)。
- **🔬 三模型对比 (2026-08-05, commit ada65fb1, 老倪: \"增加一个没有leworldmodel的流程, 三个模型对比, 即 ACT, SmolVLA, SmolVLA+Leworldmodel串行\")**: 新模板「🔬 三模型对比」**18节点20连线** = ♻共用2 (📦metaworld数据 / 📊对比评估Scope) + **3 分支行**: ACT 7 (ResNet18→CVAE→Encoder→Decoder→ActionHead·ACT→Ensemble→训练) + SmolVLA 纯动作 4 (SmolVLM2→DiT-B→ActionHead·SmolVLA→训练, **无 LEW**) + SmolVLA+LEW 5 (SmolVLM2·LEW→DiT-B·LEW→🌐LeWorldModel→ActionHead·SmolVLA+LEW→训练)。三训练节点 policy=act / smolvla / smolvla_lew。入口 btn_compare3 \"🔬 三模型对比\" (#d4a800) → open_compare3()。**⚠️ 关键配置坑 (configuration_smolvla_lew.py:125-126 `__post_init__`)**: `freeze_smolvlm: true` 时 **`enable_lew_world_model` 被强制改 False** — 现有 config_smolvla_metaworld.yaml (freeze=true) 训练出的\"SmolVLA\"其实**根本没启用 LEW**! 要真 LEW 必须新建 `config_smolvla_lew_metaworld.yaml` (freeze_smolvlm: **false** + enable_lew_world_model: true + lew_* 参数)。on_train 三策略分支 (smolvla_lew→新配置+ts_dir=smolvla_lew_<ts> / smolvla→旧配置+smolvla_<ts> / else→ACT), 曲线落盘 reports/train_curve_<policy>.json 各写各的。compare_models.py main() 改循环 `policies=[(\"act\",\"ACT\"),(\"smolvla\",\"SmolVLA\"),(\"smolvla_lew\",\"SmolVLA+LEW\")]` 逐个 find_ckpt+eval (缺 checkpoint 跳过不报错); on_compare_scope 改\"有任一产物即可评估\"(不再强制双曲线都在)。ModelCompareDialog._load_data 通用 N 模型 (MODELS 表 + present=[k in m and m[k]]): loss 折线每模型一条 / 表格 N 列+胜出列 / bars.set_data(rows, names=[...]); simulink_scope.COLORS 加 `smolvla_lew: #a371f7` (紫)。**⚠️ BarCompareWidget paintEvent float 坐标崩 (2026-08-05 渲染对话框时暴露, commit 53164e6a)**: 原双模型版 `y0 = i * row_h` 是 float, `p.drawText(8, y0+14, ...)` **PyQt5 严格类型 → TypeError** (隐藏 bug 从未被触发, N 模型改造后测试渲染对话框才崩)。修: y0/yy 全部 `int()`。**教训: 自绘 paint 的 drawText/fillRect 坐标必须 int (同 QPen.setWidth 只收 int 一族); 改完必须真实渲染一遍**。验证 (offscreen EXIT=0): YAML 语义断言 (lew 配置 enable=true+freeze=false) / compare 语法 / 模板 18节点20连线 / Action Head 三行对齐 / ModelCompareDialog 假数据三模型表格含 \"3 模型\" / 画布渲染采样非白。

## simulink 工程完整性检查 (2026-08-28 v3.3.1, 老倪: 全面检查)
新增 `tools/ci/zmax_integrity_check.py` 一键检查器, 五项全绿:
1. **NODE_TYPES 三处同步** (simulink_module 15种 = validate_flow = simulink_ci) —
   曾不同步 (主15/验证6/CI8) → 画布 type=data/scene/row_bg 被验证器误判"非法"。
   新增节点类型必须三处同步 (老规矩, 检查器自动验证)。
2. **状态空间/业务闭环豁免**: flow_x.json/cooperation_closed_loop 的环是架构反馈
   (卡尔曼校正/感知-决策-执行/供应商区-实验室-现场), 非错误 — validate_flow 和
   simulink_ci 均降级警告。普通模板有环仍 FAIL。
3. **check_params 语义级校验**: 原只有类型白名单 → "pos":"not-a-list" 误判通过。
   PARAM_SCHEMA 只收确定类型的控制参数 (Kp/K_ff/Kd 数值; limit 兼容单值/区间;
   force_res="0.1N"/grid="7x9" 是文本; encoding 是 dict; in_dim/frames 可能是
   描述文本 '39D obs+4D action' — 实测校准, 不可一刀切)。
4. **check_ports 隐式端口兼容**: 真实画布节点无 outputs/inputs 字段 → 原代码
   p["id"] 对字符串索引 TypeError → 无端口列表的画布跳过。
5. **check_format 降级**: 合作闭环 (zmax-cooperation-closed-loop)/旧格式
   (hermes-flow) 模板硬判 FAIL 误伤 → warn 尽力校验。
模板加载验证: offscreen 下 SimulinkModule 构造后 monkeypatch `_qmsg_yes/_qmsg_info`
(否则第二个模板弹确认框 exec_ 卡死), 逐个 load_reference_app 断言 nodes==items。
**共享节点设计**: Model Zoo 的「🧩 结构条件」(无·后缀) 在 load_reference_app
4685 行被显式跳过 (已下放各模型行), 不进 layout 是正确设计 — 检查器要豁免它。

## VSCode 断点调试 node_logic 坑 (2026-08-31 老倪: "点运行进不了这个函数的断点")
- **症状**: 节点逻辑真实执行了(终端出现该函数日志如 "📦 数据源:")但 VSCode 断点不命中。
- **根因 ①(最常): node_logic 可修改区动态 exec** — 在 GUI「查看/编辑节点逻辑」里保存过 → `save_node_logic` 把 `NODE_LOGIC[key]["fn"]` 替换为 `exec(compile(new_code, "<node:key>"))` 出的函数, co_filename=`<node:data>` **无真实行号 → VSCode 磁盘文件断点永不命中**(函数照常执行)。判定: 断点红点空心/灰 = 未绑定。
- **解法三选一**: ① 右键节点→查看/编辑节点逻辑→「恢复出厂逻辑」(restore_default 从文件重新 exec, 行号真实) ② 重启 GUI(_SOURCE_CACHE 是内存, 重启即清) ③ `ZMAX_DEBUG_BREAK=1` 启动 GUI — execute_node_logic 开头(node_logic.py:124) `debugpy.breakpoint()` 任何节点逻辑执行前强制停, **不依赖断点绑定**, 调试动态 exec 函数唯一办法。
- **执行证据判定法**: 状态空间画布点运行 → 终端出现 "📦 数据源:" = node_metaworld_data 执行了; 有日志但断点没停 = 断点绑定问题(不是代码路径问题); 没日志 = 没执行到(画布/路径不对)。
- **F5 调试端口冲突**: 「🚀 全新调试进程」启动时 debugpy adapter 占 5678(--port 5678 --for-server), studio.py main 里 `debugpy.listen(5678)` 失败被 try/except 吞 → 想用「🔌 Attach 现有控制台(5678)」必须没有 F5 会话; GUI 启动即 listen 5678(main 内, 不阻塞)。
- **GNOME/Xorg 黑屏 (2026-08-31)**: studio.py main 的 `AA_UseSoftwareOpenGL` 软件 GL 在 Mutter 合成器下窗口内容渲染全黑(该行是 WSLg 假死修复, 已注释) — WSLg 环境才需要, 本机 GNOME 桌面不要开; 症状=窗口在但全黑, 关窗后事件循环 quitOnLastWindowClosed 退出(exit 0)。

## 本机推理/仿真环境 (2026-08-30 实测)
- **推理/评估/出视频的 python = ~/lerobot-venv**(项目无 .venv;GUI 用 gui-venv311 无 torch)。
  on_infer_rollout/on_eval_state_space 已改多候选探测: `.venv → ~/lerobot-venv → gui-venv311`。
- **metaworld 3.1.1 + mujoco 3.3.0 + glfw + PyOpenGL + scipy** 已装进 ~/lerobot-venv(2026-08-30)。
  requirements-macos.txt 锁 metaworld==3.0.0(3.0.0 wheel 从 files.pythonhosted.org 下载不稳/中断,未装成)。
- **⚠️ pip/uv 装 metaworld 系列会僵死**(resolver 卡,0% CPU 无网络,杀不掉会一直挂着):
  正解 = `pip download`/curl 拿 wheel → 校验 `unzip -t` → `--no-deps` 安装或直接 unzip 解包进 site-packages → 逐个补缺的 import(glfw/imageio/scipy/PyOpenGL, aliyun 源快)。
- **gen_insert_video 12/12 seed 卡"转移/下降"诊断**: full_pipeline.pt(08-24 fallback)与新 metaworld 3.1.1 物理不匹配 —
  contact_head 预测 0.30-0.41 徘徊达不到 0.5 阈值, 降阈值 0.35 会误进转移但 peg 抓空(peg z 不变)。
  **本机可用 left_right 模型被磁盘红线清光** → 要出视频需训练新模型或从 4090 拉。
- 历史: left_right_20260813_164959(曾验证成功 seed2)已被磁盘清理删除, 勿再引用。

## Windows exe 画布打不开 = /tmp 打点无保护 (2026-08-28 v3.3.2, 老倪: "3.3.1 3.3.0 无法打开画布, 3.2.4 可以")
- **症状**: Windows exe 上 simulink 画布 tab 打不开/空白, 状态栏 "⚠️ Simulink 初始化失败: [Errno 2] No such file or directory: '/tmp/...'"; 源码版 Linux 正常 (有 /tmp)。
- **根因**: 3.3.0 为排查 Mac 黑屏加的 SimulinkModule 构造打点直接 `open("/tmp/zmax_simulink_init.log", "a")` — studio.py `_init_simulink` 里 `_mk` lambda **无 try/except** → Windows 无 /tmp 目录 → FileNotFoundError 抛在 `SimulinkModule()` 之前 → 画布从未创建。simulink_module.py 里同款打点有 try/except 所以不崩 (静默失效)。
- **铁律**: ①跨平台诊断打点/临时文件一律 `os.path.join(tempfile.gettempdir(), name)` + try/except, 禁止裸 `/tmp` (Windows 没有); ②`_init_simulink` 这类"建画布"路径里任何语句抛异常都会让画布整体消失 — 打点类语句必须自身容错, 不能依赖外层 try 兜底 (外层 catch 后画布也没了); ③验证必须模拟 Windows: monkeypatch `tempfile.gettempdir` → 不存在目录, 再跑 `SimulinkModule()` + `load_flow_file`, 断言 nodes>0。
- **排查流程**: 3.2.4 正常 → 3.3.0 坏 = 二分 diff `git diff <v3.2.4>..<v3.3.0>`, 找新增的 IO/路径类语句; 用户报"Windows 打包的版本"时优先怀疑平台差异 (路径/权限/编码), 不是 UI 逻辑。

## QDialog 最大化按钮点了没反应 (2026-08-28, 节点逻辑/参数/源码窗口)
老倪「最大化按钮不好使, 不是让你禁用, 修复它」— 第一轮误把"不好使"理解成"禁用"
加了 `~WindowMaximizeButtonHint` (方向错误, 被纠正)。**根因**: QDialog 默认 Qt.Dialog
窗口类型在 X11 WM 下标题栏最大化按钮点击无效 → 显式转普通窗口类型:
```python
self.setWindowFlags(Qt.Window | Qt.WindowMaximizeButtonHint
                    | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
```
验证 (真实 DISPLAY, offscreen 会误判): showMaximized → isMaximized=True + 尺寸≈屏宽
(本机 3068x1862)。**教训: 老倪说"XX按钮不好使"= 修复功能, 绝不是禁用**;
窗口类型/按钮 hint 类问题先确认 Qt.Window vs Qt.Dialog 类型再动手。

## 状态空间画布连线因果检查 (2026-08-28, 触觉感知孤立节点)
老倪「触觉感知的数据源, 也应该是metaworld啊」— 画布上 🖐 触觉感知节点入度=0 (孤立),
但引擎真实数据 (state_space_sim._build_obs) 的 tactile4=[gripper, contact] 就是 metaworld
夹爪开度+物理接触检测。**画布连线必须如实反映引擎数据流**: 感知类节点 (传感器融合/YOLO/
触觉感知) 都应有 📦 metaworld 数据源 入边。排查法: 遍历 flows/*.json 入度=0 的非 row_bg
节点, 对照 state_space_sim/源码确认是否真有上游。修法: 补 link {f:ssdata, t:sstactile,
label:触觉数据} + 节点 desc 注明数据来源。拓扑验证: 单步第一节点应变为数据源 (因果正确)。
铁律: 画布每个节点要有真实的数据源连线, 不许有"引擎内部取数但画布孤立"的节点。

## pyqtgraph GL 跨上下文 shader 失效 (2026-08-28, 3D 视图二次打开背景丢)
**症状**: 老倪「3D 视图第二次打开, 场景背景没了」— 首次打开正常, 关窗再开只剩纯背景色。
**根因**: pyqtgraph `opengl/shaders.py:420 initShaders()` 模块导入时编译一次、全局缓存
ShaderProgram, 句柄绑定**第一个** GL 上下文。窗口 close 后再开 = 新建 GLViewWidget =
新 GL 上下文 → 旧句柄失效 → 绘制报 `GLError 1281 glUseProgram(3) invalid value`
(debug.printExc 打 RuntimeWarning, 界面无弹窗)→ 所有 GL item 静默失败。
**验证方法** (tools/gui 下跑, DISPLAY=:0): `view.grabFramebuffer()` 统计非背景像素,
实测 531589→0 px 复现; 同一窗口 close→show 像素不变 (531589→531589) → 只复用不新建。
**修法**: open_ss_3d 窗口复用逻辑从 `if w.isVisible()` 改为 `if w is not None` —
close 只是隐藏 (无 WA_DeleteOnClose), 对象+GL 上下文都在; 数据源变了再
`w.set_trajectory(tr)` 重建场景; close 停掉的 `_cam_watch` 定时器要重启。
`_ss_3d_windows` 清理用 `sip.isdeleted` 判断, 别用 `isVisible` 过滤 (会误删可复用窗口)。
**连带坑**: `_build_scene` 重建时同一 item 被多 key 引用 (yolo 列表 ↔ yolo_hand/peg/hole),
重复 `view.removeItem(x)` 抛 `ValueError: x not in list` → 重建中断。修: 按 `id(x)` 去重 +
`except (ValueError, RuntimeError)` 容忍。**铁律: pyqtgraph GL 窗口一律复用不新建;
重建 GL item 树必须去重 removeItem。**

## simulink 字体大挤调小 (2026-08-28, 192DPI)
老倪「终端字体/画布方框字体/工具栏按钮字体都大, 很挤」。真机 `logicalDotsPerInch=192`
(X 上报 96, 但 Qt 用 192) → 12pt 渲染成 **32px**。调小一档: 工具栏 mk_btn 12pt→10pt
(minHeight 34→30, padding 7x14→6x12); 终端 log_box 12pt→10pt; 画布节点标题
12/11/10→10/9/8; 节点内部文字/徽章/ID/背景行模型名 11→10、10→9; 连线数据流标签 10→9。
**⚠️ offscreen 是 96 DPI (10pt=14px), 真机 192 DPI (10pt=27px)** — offscreen 只能验
布局逻辑/文字放不放得下, 像素尺寸验证必须真实 DISPLAY=:0。验证:
`QFontInfo(QFont('Arial', pt)).pixelSize()` 打真机 px。

- **🗂 模板多行展开布局 (2026-08-05, commit ada65fb1, 老倪: \"你每次都是从一条直线上开始给出, 你需要把所有节点展开, 不要重叠成一条线; 类似的功能, 例如 Action Head, 应该垂直对齐\")**: **用户偏好 — 模板加载节点禁止单行横排 (13+ 节点一条直线出画布外)**。REFERENCE_APPS 条目支持可选**第4元素 layout** (3元组模板兼容, 4元组才启用): `layout = [[节点名...]每行]` 网格 — **行 = 模型分支 (y 递进 230), 列 = 功能角色 (x 递进 260), 空串 \"\" 占位跳过**。同名节点多行出现 → 取各自候选坐标 → **同列垂直对齐** (三模型 Action Head 都落第5列 x=1420, y=80/310/540)。load_reference_app 加 layout 分支: 先 `pos.setdefault(nm, []).append((x,y))` 收集同名多行坐标 → 每节点取 `next(p for p in cands if p not in used)` (used 去重保证共享节点只画一次, 如 metaworld 三行共用顶部一个) → 兜底单行。**⚠️ REFERENCE_APPS 改 4 元组后全仓库 3 处 `for nm, nodes, links in REFERENCE_APPS` 解包全崩 (ValueError) — 必须逐个改 `for item in ...: nm=item[0]`** (参考应用按钮 1758 / _act_build_link_existing / _act_build_finish)。验证 (offscreen): 三模型模板 18节点 / Action Head `len(set(x))==1` 且 `ys == [80,310,540]` / metaworld 只画一次 / 双模型+ACT-Meta 回归 (3元组) 不崩。