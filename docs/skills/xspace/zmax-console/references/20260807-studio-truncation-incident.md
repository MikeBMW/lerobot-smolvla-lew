# studio.py 截断事故 + 恢复流程 + 指令最小化 (2026-08-07)

## 事故: execute_code 字符串操作截断 studio.py (8057 → 1266 行)

**经过**: 用 execute_code 做"删除 DATASETS 非 metaworld 条目"——Python `src.index(...)` + 切片拼接写回。
第二次删除 (asu 条目) 时 index 计算错位 → `src2 = src[:i] + ...` 把文件**尾部整段截掉** (1266 行, 只剩开头)。
`_local_datasets`/`DataSpaceModule`/`TrainingModule`/`StudioMainWindow` 全没。

**根因**: 大文件 (8000+ 行) 上多次 `str.index` 定位 + 切片拼接, 任何一次错位 (如第一个 `'        },\n    ]'` 出现在
预料外位置) 都会静默写坏文件。write_file/execute_code 写文件**没有保护**。

**恢复流程 (实测, ~10 分钟)**:
1. `git log --oneline -3 -- tools/gui/studio.py` + `git log -1 --format=%ci` → 确认 HEAD 时间。
   本会话 HEAD 是 15:52 (老倪工作仪式常提交) → 当天大部分改动已在 HEAD 里。
2. `git checkout tools/gui/studio.py` → 恢复 HEAD 版 (7787 行) → `python3 -c "import ast; ast.parse(...)"` 验语法。
3. **重新应用 HEAD 之后的所有 patch** (本会话 15:52 后的 ~9 处: _is_cached metaworld 分支 / _on_view_dataset
   非模态+local_root / 当前数据集卡片 / _local_datasets / _populate_table 本地行 / 缓存列 / 信息按钮本地分支 /
   DataSpaceModule+modules+stack+首页卡片 / DATASETS 删减)。每处 patch 工具有 diff 确认。
4. **补 _repo_root 方法** (HEAD 版没有, 我加的代码用到) — 恢复时容易漏的依赖。
5. fresh 验证: 行数>7500 + 关键类存在 + DatasetModule 表格 5 行 + DataSpaceModule 摘要。

**纪律 (防再犯)**:
- **大段删除/重排永远用 patch 工具** (old_string/new_string 精确匹配, 有 diff), 不用 execute_code 字符串脚本。
- 必须用脚本批量改文件时: 只做**简单替换** (整块文本替换), 且写回前 `ast.parse` + 行数断言
  (`assert lines > 7500`), 写回后立刻验证。
- 恢复时 patch 一个验证一个, 不要一次性批量。

## 指令最小化执行 (老倪"别删多了")

**教训**: 老倪说"YOLO 3D, 删掉检测" = **只删节点名里的"检测"两个字** (YOLO 3D 检测 → YOLO 3D)。
我先理解成"删 YOLO 3D 检测功能/节点"→ 又理解成"删背景行大字" (把 row_bg 大字+小标都删了) →
老倪三次纠正: "背景字删掉" → "就是删掉 检测两个字" → "别删多了"。

**规则**:
- **歧义指令先做最小改动**: 改名字/改文案优先, 不要删功能/节点/模块。
- "删掉 X" 先确认 X 是名字的一部分 (改名) 还是独立功能 (删除); 拿不准时先改名, 或问一句。
- 误删了要立即恢复 (git show HEAD:文件 提取原始代码段 patch 还原)。
- 恢复背景行大字: `git show HEAD:tools/gui/simulink_module.py | sed -n '1608,1650p'` 拿原始 paint 代码回填。

## GUI 重启纪律 (2026-08-07 补充)

- `pkill -f 'studio.py'` 命令行自身含 "studio.py" → **pkill 自匹配自杀** (exit -15), 且可能漏杀 GUI。
  重启 GUI 用**精确 PID**: `kill -9 <PID>` (跳过 closeEvent, 不触发 pkill lerobot_train 杀后台训练)。
- kill 后 `ps aux | grep '[s]tudio.py'` 确认无残留; 重启后 `ps -o lstart= -p <新PID>` 验证是新实例
  (老倪会问"重启了么/没关过" — WSLg 窗口无缝重开看起来像没重启)。
- closeEvent pkill 只匹配 lerobot_train / cicd_pipeline — kill -9 可保独立训练进程。

## 插销数据链路 (2026-08-07 完整打通)

- **gen_peg_data.py**: metaworld 官方专家 `SawyerPegInsertionSideV3Policy` 采样 peg-insert-side-v3,
  只留插入成功轨迹 (peg 抬升 0.05 + 距 hole < 0.05), 图像 128x128 corner2 视角 (与视频一致)。
  失败轨迹提前终止 (150 步) 提速。输出 data/metaworld_peg_v2/train.npz (30 eps / 5850 帧 / 39D state / 4D act)。
- **npz_to_lerobot.py** 转 data/metaworld_peg_lerobot (24 eps / 4800 帧 parquet, fps 10, episode-frames 200)。
- config root 指向 peg_lerobot → lerobot_train 1000 步 → act_pegdata_1000 ckpt → rollout 动作均值 0.564
  (旧数据模型 0.18 的 3 倍)。**插销训练是独立赛道, 曲线单独文件 train_curve_act_peg.json** (不与套环曲线合并)。
- rollout_peg_check.py: 插入检测评估 (多次 rollout, 统计抬起/插入/最小孔距) — 0/5 时先查训练不足。
- 数据集管理/DATASETS 列表按老倪要求**只留 metaworld** (删 pusht/xarm/aloha 等 11 个 HF 条目 + orin 本地条目,
  磁盘数据保留)。

## 曲线解析 K 后缀 (补充)

- lerobot 日志 `step:1K/2K/3K/4K` — 正则必须**先全部展开**: `re.sub(r"step:(\d+)K\b", lambda m: f"step:{int(m.group(1))}000", log)`
  再匹配 `step[:=]?\s*(\d+)\b.*?loss[=:\s]+([\d.eE+-]+)`。只展开 1K 会漏 2K-4K → 曲线只到 1995 步。
- 微调续训 (--policy.path=<ckpt> + 新目录 + steps 4000) 的曲线合并: step 偏移 +1000 (旧 1000 步 + 新 995/4000 步)。
- **曲线 ts 必须写真实训练完成时间**, 写当前时间会让 _check_newer_ckpt 误判 → 视频白屏 (见 dataspace-holographic ref)。
