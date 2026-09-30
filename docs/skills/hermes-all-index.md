# Hermes 技能全量镜像 (静静) — 索引

> 共 155 个技能 · 源 `~/.hermes/skills` · 排除 `.curator_backups/*.tar.gz` 与 >2MB 单文件

> 目录: `docs/skills/hermes-all/<技能名>/` (SKILL.md + references/ + scripts/ + templates/)

| 技能 | 分类 | 文件数 | 说明 |
|---|---|---|---|
| `desktop-app-packaging` | .archive | 2 | Desktop App Packaging |
| `windows-app-deployment` | .archive | 2 | >- |
| `apple-notes` | apple | 1 | Manage Apple Notes via memo CLI: create, search, edit. |
| `apple-reminders` | apple | 1 | Apple Reminders via remindctl: add, list, complete. |
| `findmy` | apple | 1 | Track Apple devices/AirTags via FindMy.app on macOS. |
| `imessage` | apple | 1 | Send and receive iMessages/SMS via the imsg CLI on macOS. |
| `claude-code` | autonomous-ai-agents | 1 | Delegate coding to Claude Code CLI (features, PRs). |
| `codex` | autonomous-ai-agents | 1 | Delegate coding to OpenAI Codex CLI (features, PRs). |
| `computer-use` | autonomous-ai-agents | 1 | Drive the desktop in the background without stealing focus. |
| `feishu-gateway` | autonomous-ai-agents | 4 | Set up Feishu/Lark gateway for Hermes Agent from scratch. |
| `merge-reconciler` | autonomous-ai-agents | 1 | Neutral third-party resolution of agent merge conflicts. |
| `multi-agent-project-recovery` | autonomous-ai-agents | 3 | Recover agent context from repo after crash/reinstall. |
| `opencode` | autonomous-ai-agents | 1 | Delegate coding to OpenCode CLI (features, PR review). |
| `architecture-diagram` | creative | 2 | Dark-themed SVG architecture/cloud/infra diagrams as HTML. |
| `ascii-art` | creative | 1 | ASCII art: pyfiglet, cowsay, boxes, image-to-ascii. |
| `ascii-video` | creative | 10 | ASCII video: convert video/audio to colored ASCII MP4/GIF. |
| `baoyu-infographic` | creative | 47 | Infographics: 21 layouts x 21 styles (信息图, 可视化). |
| `claude-design` | creative | 1 | Design one-off HTML artifacts (landing, deck, prototype). |
| `comfyui` | creative | 33 | Generate images, video, and audio via diffusion workflows. |
| `design-md` | creative | 2 | Author/validate/export Google's DESIGN.md token spec files. |
| `excalidraw` | creative | 5 | Hand-drawn Excalidraw JSON diagrams (arch, flow, seq). |
| `humanizer` | creative | 2 | Humanize text: strip AI-isms and add real voice. |
| `manim-video` | creative | 17 | Manim CE animations: 3Blue1Brown math/algo videos. |
| `p5js` | creative | 17 | p5.js sketches: gen art, shaders, interactive, 3D. |
| `popular-web-designs` | creative | 55 | 54 real design systems (Stripe, Linear, Vercel) as HTML/CSS. |
| `pretext` | creative | 4 | Build creative browser demos with DOM-free text layout. |
| `sketch` | creative | 1 | Throwaway HTML mockups: 2-3 design variants to compare. |
| `songwriting-and-ai-music` | creative | 1 | Songwriting craft and Suno AI music prompts. |
| `touchdesigner-mcp` | creative | 23 | Control TouchDesigner via twozero MCP. |
| `e-drive-ubuntu-clone` | devops | 1 | Use when 把U盘LiveUSB系统迁移到E盘装Ubuntu(nvme0n1p5)。含授权红线。 |
| `gnome-desktop-launchers` | devops | 2 | Use when GNOME桌面 .desktop 快捷方式有叉号/未信任/建桌面图标。DING缓存坑+修复序列。 |
| `http-relay-service` | devops | 5 | Use for HTTP relay/queue services on remote hosts. |
| `linux-chinese-input` | devops | 1 | Use when 在 Linux/WSL/U盘Live系统装中文输入法 (ibus/fcitx5). |
| `linux-wifi-troubleshooting` | devops | 4 | Use when Linux WiFi 连不上/掉线/只能连热点. 诊断国家码/省电/Intel驱动/信号. |
| `novnc-remote-desktop` | devops | 3 | Use when 要浏览器/手机远程看+操作 Linux 桌面或 websockify 转发 VNC 失败. |
| `sdlc-review` | devops | 1 | Review Kanban handoffs and route verified outcomes. |
| `unattended-pipeline-supervision` | devops | 6 | Use when 无人值守长流水线(下载/校验/解压/训练/评测)需终态上报 — 静默哨兵+沙箱验两分支. |
| `zmax-dual-boot-hermes` | devops | 2 | Use when U盘出差要带Hermes记忆或双系统数据架构(nvme0n1p5)维护。 |
| `zmax-usb-hermes-mirror` | devops | 1 | Use when U盘随身镜像/E盘数据盘bind/离家记忆 部署维护排障。静静大脑跨盘架构 (09-06)。 |
| `zmax-ws-chat-debug` | devops | 2 | Use when datadrive.world 群聊/WS 无消息, 诊断 WS 服务端推送。chat.html 空。 |
| `email-inbox-triage` | email | 1 | Triage an inbox: prioritize threads, draft replies safely. |
| `himalaya` | email | 3 | Himalaya CLI: IMAP/SMTP email from terminal. |
| `codebase-inspection` | github | 1 | Inspect codebases w/ pygount: LOC, languages, ratios. |
| `git-history-slimming` | github | 1 | Use when a git repo is bloated or user wants 精简/不要什么都上传. |
| `github-actions-ci` | github | 8 | 'Use for GitHub Actions: Windows exe, Docker, ACR, releases.' |
| `github-auth` | github | 3 | GitHub auth setup: HTTPS tokens, SSH keys, gh CLI login. |
| `github-code-review` | github | 2 | Review PRs: diffs, inline comments via gh or REST. |
| `github-issue-to-pr` | github | 1 | Carry a GitHub issue to a verified PR with honest CI state. |
| `github-issues` | github | 3 | Create, triage, label, assign GitHub issues via gh or REST. |
| `github-pr-workflow` | github | 5 | GitHub PR lifecycle: branch, commit, open, CI, merge. |
| `github-repo-management` | github | 2 | Clone/create/fork repos; manage remotes, releases. |
| `gif-search` | media | 1 | Search/download GIFs from Tenor via curl + jq. |
| `songsee` | media | 1 | Audio spectrograms/features (mel, chroma, MFCC) via CLI. |
| `youtube-content` | media | 3 | YouTube transcripts to summaries, threads, blogs. |
| `dataset-archive-provisioning` | mlops | 4 | Use when 大归档(.zst)未解压致下游FileNotFoundError或需回收磁盘。 |
| `disk-redline-guard` | mlops | 1 | 磁盘红线守护, 训练产物只留最后ckpt, HF缓存清incomplete, cron每2h自动执行。 |
| `docker-gpu-training` | mlops | 8 | Docker GPU Training |
| `evaluating-llms-harness` | mlops | 5 | lm-eval-harness: benchmark LLMs (MMLU, GSM8K, etc.). |
| `hf-dataset-subset` | mlops | 6 | Use when 只要一小部分数据/磁盘不够 — download a small HF dataset subset. |
| `hf-weight-download` | mlops | 1 | HF权重下载卡死解决, ignore_patterns跳onnx, 断点续传, 离线加载验证。 |
| `huggingface-hub` | mlops | 1 | HuggingFace hf CLI: search/download/upload models, datasets. |
| `intact-jepa-official-eval` | mlops | 12 | Use when 跑 INTACT-JEPA 论文权重官方评测或核口径/视频。 |
| `intact-lewm-official-eval` | mlops | 1 | Use when 复现/跑 INTACT(LeWM) 四任务官方评测或数据集报错。 |
| `lerobot-act-training` | mlops | 8 | Use when training ACT policies in lerobot-smolvla-lew fork. |
| `lerobot-dataset-engineering` | mlops | 6 | LeRobot 数据集构建坑 — timestamp相对/索引重编号/视频对齐/hub覆盖。训练数据出错时用。 |
| `llama-cpp` | mlops | 7 | llama.cpp local GGUF inference + HF Hub model discovery. |
| `metaworld-sim-eval` | mlops | 6 | Metaworld 仿真 rollout 视频 + 多模型对比评估。生成 sim 视频时用。 |
| `nvidia-gpu-driver-setup` | mlops | 6 | Use when Ubuntu 装 NVIDIA 驱动或 nouveau 冲突加载失败。 |
| `policy-direct-drive-integration` | mlops | 7 | Use when 策略直接输出指令开机器人 (直驱) 或先判动作头能否用. |
| `python-ml-env-mirrors` | mlops | 4 | Use when pip/pytorch.org is slow: use aliyun mirrors. |
| `pytorch-cuda-install` | mlops | 2 | Use when official PyTorch+CUDA wheel installs fail. |
| `research-repo-official-eval` | mlops | 2 | Use when 跑研究仓库官方评测或接其权重 (预检/ckpt config/数据布局). |
| `robot-policy-eval` | mlops | 3 | 机器人策略仿真评估管道陷阱, 归一化来源, 图像尺寸, 反归一化, 长轨迹平均化, 假0%诊断。 |
| `robot-policy-eval-pitfalls` | mlops | 17 | 机器人策略训练/评估管道坑, 长轨迹平均化, 逐维stats, 图像尺寸, 反归一化, 坐标叠加架构。 |
| `robot-policy-eval-rollout` | mlops | 5 | 评估/rollout 已训练机器人策略(ACT/SmolVLA/AWE/MLP), 0%成功率排查, 行为视频生成。 |
| `robot-policy-eval-training` | mlops | 3 | 机器人策略(ACT/SmolVLA/AWE)评估管道同构性与训练数据坑, 防假0%抓取。 |
| `robot-policy-training` | mlops | 8 | 机器人策略训练(BC/RL/蒸馏)与评估管道正确性, 含长轨迹方向反转坑与夹爪头分离。 |
| `robot-sim-mujoco-rendering` | mlops | 2 | Use when mujoco/metaworld 仿真进程内多轮/多线程 env 渲染黑帧或做来料干扰鲁棒性测试. |
| `robot-vision-3d-localization` | mlops | 2 | Use when 视觉3D定位/抓取失败, 需分解2D-深度-公式误差或防遮挡幻影。 |
| `serving-llms-vllm` | mlops | 5 | vLLM: high-throughput LLM serving, OpenAI API, quantization. |
| `simulink-flow-engineering` | mlops | 27 | Use when 生成/改 simulink flow JSON、模块库LIBRARY加删按钮、VEH.5编号问题。 |
| `smolvlm-perception-integration` | mlops | 2 | 'Use when 把真实 SmolVLM/VLM 视觉编码接入画布感知节点, 或本地单帧编码。含回归红线。' |
| `unattended-job-orchestration` | mlops | 7 | Use when 长跑多阶段任务(下载/解压/训练/评测)要无人值守出结果 — 接力脚本 + 哨兵 cron 只报一次。 |
| `weights-and-biases` | mlops | 4 | W&B: log ML experiments, sweeps, model registry, dashboards. |
| `yolo-3d-perception-chain` | mlops | 1 | YOLO 2D→3D→state 感知链, 含 ultralytics BGR 坑与同构评估原则。 |
| `yolo-depth-head` | mlops | 2 | 给 YOLO 加 depth head 恢复 z 深度, 替代写死深度平面。 |
| `zmax-cicd` | mlops | 5 | Use when Z-MAX 数据闭环/CICD (Orin采集→ECS中转→4060训练ACT→部署Orin). |
| `zmax-cicd-pipeline` | mlops | 5 | Z-MAX robot policy train/deploy/iterate loop (ACT→ECS→Orin). |
| `zmax-data-closed-loop` | mlops | 1 | Z-MAX 边学边练闭环 — Orin采集→ECS→4060训练→静态URL部署→推理循环。机器人采集时用。 |
| `zmax-data-pipeline` | mlops | 9 | Z-MAX 数据闭环: Orin采集→Mac→ECS中转→本地训练ACT。数据不通/中转/上传训练时用。 |
| `zmax-left-right-policy` | mlops | 1 | Use when 训练/评估/部署 left_right 双脑策略 (左脑MLP+右脑WM+8状态机), 指标上报大屏。 |
| `zmax-metaworld-real-loop` | mlops | 7 | Z-MAX 引擎真实化闭环 (R0 物理 / R1 感知) |
| `zmax-mobile-3d-console` | mlops | 1 | Use when 把状态空间3D复刻成手机Three.js页看/控, 或手机触发真引擎的实况联动. |
| `zmax-model-compare-report` | mlops | 12 | Z-MAX 多模型对比评估→PDF技术选型报告→飞书交付。五模型横比/选型时用。 |
| `zmax-muscle-memory` | mlops | 1 | Use when 原子技能需要"越练越顺"机制 — 重复动作固化标杆模板后快速直通, 或状态空间引擎集成肌肉记忆. |
| `zmax-policy-training-eval` | mlops | 27 | Z-MAX 插拔策略训练与评估管道 — 评估铁律(逐维norm/图像尺寸/反归一化), 坐标叠加架构, BC多阶段退化。 |
| `zmax-real-closed-loop` | mlops | 1 | Use when 状态空间引擎换 metaworld+YOLO 真实化闭环, R0/R1 分层, 探针先行。 |
| `zmax-scene-engineering` | mlops | 1 | Use when Z-MAX 场景工程化/原子技能/合作闭环. 场景JSON、3D链接、POST、row_bg坑。 |
| `zmax-state-3d-mobile` | mlops | 1 | Use when 仿真3D视图接手机看/控制, Three.js复刻 pyqtgraph 场景或方案A真联动. |
| `zmax-state-space-architecture` | mlops | 22 | Use when 状态空间画布 debug — 字段来源(预定义vs预测), 教学解析层vs真实权重, 节点源码映射. |
| `zmax-state-space-training` | mlops | 1 | state_space 训练失败(lerobot-venv 缺/tasks.parquet 缺)时重建环境. |
| `obsidian` | note-taking | 1 | Read, search, create, and edit notes in the Obsidian vault. |
| `airtable` | productivity | 1 | Airtable REST API via curl. Records CRUD, filters, upserts. |
| `box` | productivity | 11 | Box manages cloud files, sharing, search, and metadata. |
| `document-to-action-items` | productivity | 1 | Extract cited obligations, deadlines, tasks from documents. |
| `docx` | productivity | 12 | Create, read, edit, template, and review Word .docx files. |
| `google-workspace` | productivity | 7 | Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python. |
| `maps` | productivity | 2 | Geocode, POIs, routes, timezones via OpenStreetMap/OSRM. |
| `meeting-action-items` | productivity | 1 | Turn meeting notes into cited decisions, owners, tickets. |
| `nano-pdf` | productivity | 1 | Edit text in existing PDFs via natural-language prompts. |
| `notion` | productivity | 2 | Notion API + ntn CLI: pages, databases, markdown, Workers. |
| `ocr-and-documents` | productivity | 4 | Extract text from PDFs/scans (pymupdf, marker-pdf). |
| `pdf` | productivity | 17 | Create, read, merge, fill, and secure PDF files. |
| `powerpoint` | productivity | 8 | Create, read, edit .pptx decks with python-pptx. |
| `pptx-templates` | productivity | 1 | Edit PPTX templates with python-pptx preserving layout. |
| `product-price-monitor` | productivity | 1 | Watch product, flight, or listing prices; alert on target. |
| `session-librarian` | productivity | 1 | Organize sessions by prompt: find, rename, archive, prune. |
| `teams-meeting-pipeline` | productivity | 1 | Teams meeting summaries, job replay, Graph subscriptions. |
| `weekly-review-planning` | productivity | 1 | Weekly reset: commitments, stalled work, next-week plan. |
| `xlsx` | productivity | 11 | Create, read, edit Excel .xlsx workbooks and CSVs. |
| `arxiv` | research | 2 | Search arXiv papers by keyword, author, category, or ID. |
| `blocked-page-recovery` | research | 2 | Recover blocked/paywalled/WAF'd pages via fallbacks. |
| `blogwatcher` | research | 1 | Monitor blogs and RSS/Atom feeds via blogwatcher-cli tool. |
| `competitor-news-monitor` | research | 1 | Watch named companies for material news; cited digests. |
| `grounded-citations` | research | 5 | Ground answers and documents in cited, verifiable sources. |
| `llm-wiki` | research | 1 | Karpathy's LLM Wiki: build/query interlinked markdown KB. |
| `polymarket` | research | 3 | Query Polymarket: markets, prices, orderbooks, history. |
| `research-paper-writing` | research | 56 | Research Paper Writing Pipeline |
| `openhue` | smart-home | 1 | Control Philips Hue lights, scenes, rooms via OpenHue CLI. |
| `xurl` | social-media | 1 | X/Twitter via xurl CLI: raw post search, posting, DM, media. |
| `android-webview-shell-apk` | software-development | 5 | Use when 要把网页包成安卓 APK 装手机 (WebView 套壳), 或需命令行打 APK 无 Gradle. |
| `branch-merge-review` | software-development | 1 | Review & safely merge a teammate's pushed branch (no PR). |
| `cross-venv-model-canvas-node` | software-development | 2 | Use when 外部venv模型要封装成画布节点 (跨venv子进程桥). |
| `dogfood` | software-development | 3 | Exploratory QA of web apps: find bugs, evidence, reports. |
| `hermes-agent-skill-authoring` | software-development | 1 | Author in-repo SKILL.md files: frontmatter and structure. |
| `hermes-crash-recovery` | software-development | 12 | Restore Hermes crash: repos, creds, memory, gateway. |
| `inspecting-hermes-desktop-dom` | software-development | 1 | Read the live Hermes desktop DOM/CSS over CDP. |
| `integration-level-audit` | software-development | 22 | Use when 判定模型/节点是否真的接进执行链 — 节点级 vs 档位级分级取证, 孤岛/假接入识别. |
| `layered-capability-stack` | software-development | 3 | Use when 打通分层能力栈或给已有链路加可选通道 — 上层只给意图/条件, 执行由最下层收口 + 零回退取证. |
| `model-capability-feature-dbc` | software-development | 5 | Model Capability Feature Library & feature.dbc |
| `node-inspect-debugger` | software-development | 1 | Debug Node.js via --inspect + Chrome DevTools Protocol CLI. |
| `plan` | software-development | 1 | Write a markdown plan to .hermes/plans/; no execution. |
| `ppt-as-control-interface` | software-development | 2 | Drive a desktop console via PPT slides with markers. |
| `ppt-driven-workflow` | software-development | 2 | PPT to console via markers. Template match, arch, sync. |
| `pyqt-gui-auto-verification` | software-development | 13 | Use when PyQt5 GUI 自动取证测试 — 驱动真实窗口截图作证据入报告。 |
| `pyqt5-distribution` | software-development | 14 | Package PyQt5 apps — Docker X11, Windows .exe CI, doc sync, auto-update, PPT instruction engine. |
| `pyqt5-gui-development` | software-development | 13 | Use when developing/debugging PyQt5 GUIs on WSL/WSLg. |
| `python-debugpy` | software-development | 1 | Debug Python: pdb REPL + debugpy remote (DAP). |
| `qt-gl-rendering-pitfalls` | software-development | 1 | Qt/pyqtgraph GL 渲染坑与 QPainter 2.5D 替代 |
| `requesting-code-review` | software-development | 1 | Pre-commit review: security scan, quality gates, auto-fix. |
| `simplify-code` | software-development | 1 | Parallel 4-agent cleanup of recent code changes. |
| `spike` | software-development | 1 | Throwaway experiments to validate an idea before build. |
| `systematic-debugging` | software-development | 1 | 4-phase root cause debugging: understand bugs before fixing. |
| `test-driven-development` | software-development | 1 | TDD: enforce RED-GREEN-REFACTOR, tests before code. |
| `zmax-console` | software-development | 300 | Z-MAX Console |
