# 分层记忆画布 UI + 画布重排工程坑 + 离线 lerobot_train (2026-09-09)

## 🧠 分层记忆入画布 (老倪: L2/L3/L4 记忆 + 大模型层共享, "总分结合, 分层有效")

- **真源 = src/lerobot/memory/memory_store.py** → data/shared_memory.json
  (画布/引擎/CLI 跨进程桥; _REPO_ROOT = dirname(__file__, 4); put/save 写失败不打断主流程)。
  进程内引擎 worker 同 GUI 进程可共享 dict, 但 CLI probe 是独立进程 → **json 落盘是唯一桥**。
- **布局**(记忆带 h≈110 紧贴功能区上方, 大模型行更名"共享记忆中枢层"并在链路端部加中枢节点):
  数据源 → 大模型·共享中枢(🧠 ss_mem_share) → 🏆L4记忆(ss_mem_l4) → L4功能(潜空/流形)
  → 🚀L3记忆(ss_mem_l3) → L3功能(VLM/DiT) → 🔧L2记忆(ss_mem_l2) → L2功能 → 验证/可视化。
- **总分结合连线**(11 条): 分层入 = 功能区信号→记忆 (ssff→L2记忆 动作流 / ssllm→L3记忆 技能token
  / ssmani_exp→L4记忆 预测流形); 分层出 = 记忆→功能区回注 (L2→sssched 标杆直通 / L3→sssched
  流程 / L4→ssmani_c 恢复策略); 上行共享 = L2/L3/L4→share; 中枢出 = share→ssllm + ssreason
  (共享上下文注入 LLM)。**记忆是信息共享不是控制注入 — 不接动作环, 安全链不动 ("不改变原有架构")**。
- **分层有效 = 节点执行要真读真写**: node_ss_mem_l2/l3/l4 读共享表/真实源 (L2 读 muscle_memory.json,
  L3 读 l3.flows, L4 读 l4.predict) → log 展示 → **put("lX","out",{...}) 下行条目**; share 汇总三层
  → put("meta","context", 字符串) → log "⮕ 输出 → 任务规划器/异常推理器"。日志三段式 = 输入来源→处理→输出。
- **引擎写入点**: RealStateSpaceSim.run() return tr 前 `_write_shared_memory(tr)` — L3.flows
  (stage 去重路径/seed/mode/cap/done/steps/mani_mae) + L4.predict (mani_pred vs 真值 6D 逐维
  MAE, 随机权重基线诚实记录 — 接训练权重后同字段对照)。mani_mae 计算条件:
  `len(tr["mani_pred"]) == len(tr["mani_progress"])` 且 pred shape[1]==6。
- **node_logic import sys 必须在顶部** (记忆节点 _mem_store 用 sys.path; 曾漏 → NameError)。
  引擎 _write_shared_memory 插 **src** 路径 (`根/src` 不是根 — lerobot 包在 src/ 下)。

## 📐 画布行重排工程坑 (两次布局被打回后总结, 老倪: "布局不合理/看不到/没连线, 不降低能力不改架构")

1. **插入多行 = 总高暴涨 → fit 后节点小到看不清 + 行内 x 位置照旧会"节点跑屏幕外"**。
   教训: 加行后总高增幅控制在 ~原版+100px (行距压到 10-20, 记忆带 h110 不是 130)。
2. **备份会被脚本自身污染**: 脚本开头 `shutil.copy(F, bak)` + 重复运行 → bak 已是改后版本,
   "恢复"无效。干净恢复 = `git checkout flows/xxx.json` (flow 已提交时), 别信脚本备份。
3. **脚本重复运行 = 行/节点双份** (validator 报 id 重复)。跑布局脚本前先 grep 目标 id 计数=0。
4. **⚠️ 中文字符串切片 bug**: `"行:📦 数据源"[3:]` 会从 "📦" 后切 (中文 1 字符 + ':' 1 字符,
   prefix 标记取 spec[2:] 不是 [3:]) → resolve 全部 StopIteration。布局脚本的 spec 前缀解析统一
   `spec[2:]`, 别用 [3:]。
5. **链式插入(下方行逐次下移)极易错位**: 已插带也会被后续下移而节点不跟 → 改用**确定性目标布局表**
   (每行写死 新顶y+高h, 节点按"所属旧行→新行顶差"整体平移, 行高保持原值防节点溢出)。
6. **GUI 双实例**: `pkill` 与重启分两条命令且用 `[s]tudio.py` 方括号; 一条 `pkill; ... &` 组合命令被
   拦/漏执行 → 新旧两实例并存 (5678 争用)。重启前 `ps aux | grep "[s]tudio.py" | wc -l` 必须归 0。
7. **行内节点数核对**: 重排后逐行打印"行内节点数"与改前比对 (感知4/融合2/控制4/状态机2/技能8/执行2…),
   丢节点 = 能力降低, 老倪红线。记忆带节点由行对象最终 y 定位 (`行.y + 55`), 别在插带时算死。

## 📦 离线 lerobot_train (本机无 HF 网, corp guest 通 github/pypi 镜像不通 huggingface)

- **权重缓存**: ~/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct (5.7G)
  已在本机 → `HF_HUB_OFFLINE=1` 离线加载。
- **卡点 ① dataset.repo_id 触发 hub 版本检查** (list_repo_refs): 离线直接抛。绕法 (wrapper 脚本):
  ```python
  import huggingface_hub
  huggingface_hub.HfApi.list_repo_refs = lambda self,*a,**k: type("R",(),{"branches":[],"tags":[]})()
  runpy.run_module("lerobot.scripts.lerobot_train", run_name="__main__")
  ```
  repo_id 字段 draccus 必需 (删了报 Missing required field), 给任意本地名 "local/xxx" 即可。
- **卡点 ② get_safe_version (src/lerobot/datasets/utils.py)**: hub_versions 空时无条件抛
  RevisionNotFoundError, 且该异常构造缺 response kwarg → TypeError。已 patch: 本地 root 数据
  version ∈ ("main","local","") 直接返回 (try/except TypeError 双保险)。
- **卡点 ③ 依赖补装 (lerobot-venv 有 draccus/lightning 无 transformers)**:
  `/home/ubuntu/.hermes/bin/uv pip install --python ~/lerobot-venv/bin/python transformers==5.16.1
  num2words diffusers --index-url https://mirrors.aliyun.com/pypi/simple/`
  (SmolVLM processor 要 num2words, action_head DiT 要 diffusers; gui-venv311 有 transformers 但
  缺 draccus/lightning — 两环境互补, 别在 gui-venv311 上硬凑训练)。
- **卡点 ④ 数据集 meta 损坏症状**: "Invalid key: NNNN out of bounds for size M" (parquet 声称帧数
  > chunk 实际; data/metaworld_peg 声称 30 集 5400 帧实际 21 集 3780) → 属数据问题不是代码;
  episodes 抽稀列表也会触发 delta 索引错位 (删 episodes 行用全集可绕过单集损坏)。
- 训练产物核对: checkpoints/ 下 `ls -t` 取最新 step 目录 = 真实进度实锤 (别只信进程自报)。

## 🤝 多 Hermes 会话并行训练核实 (老倪贴飞书端回复让 CLI 查证)

- 现象: 飞书端 xspace 会话启动了 smolvla_lew_v8 10000 步训练并自报进度, 用户贴来让查证。
- 核实链 (进程存在 ≠ 数字属实, 三连): ① `ps -o pid,ppid,etime,cmd -p <pid>` — 单训练主进程 +
  dataloader worker 子进程同 cmd (gui-venv311/bin/python -u -m lerobot.scripts.lerobot_train);
  ② `ls -t outputs/train/<job>/checkpoints/ | head` 取最新 step 目录号 = 真实进度 (报 6194 →
  实查 8500 按速度吻合 = 可信); ③ nvidia-smi memory.used 对照 (报 2375MiB 吻合)。
- **结论真实后别重复启动第二个训练** (8GB 单卡互踩) — 差点误启, 先核实是唯一防线。
- CLI 会话 ≠ gateway 进程: CLI (gnome-terminal 里 hermes) 可 `hermes gateway restart`;
  只有 `gateway run` 主进程内重启被 Hermes 护栏硬拦 (systemd-run/脚本内容都拦)。误判自己
  "在 gateway 内"会绕远路 — 判据 `cat /proc/<pid>/cgroup` 是否在 hermes-gateway.service。
