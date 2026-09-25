# Qt 槽崩溃 / UI 延迟 / 版本五处同步（2026-09-16 实测，补 SKILL.md 未覆盖的三条）

本文件补充三类**跨控件通用**的教训（与具体页面无关），来自 2026-09-16 硬件工具箱真机联调会话。

## 1. Qt 槽内未捕获异常 = 进程直接中止（"点一下就崩"）
- **机理**: PyQt5 槽函数抛未捕获异常 → qFatal → **整个进程中止**。用户看到的是"窗口没了"，
  **没有报错弹窗**；journal/stderr 里也可能没有 traceback ⇒ 用户报"崩了"时**先按这条查**，
  不要去找并不存在的错误框。
- **本案真形**: `Z700_ROS2_NODES["real"]` 是 `[(名, 说明)]` **list**（不是 dict），
  旧代码 `Z700_ROS2_NODES.get("real", {}).get(n, "")` → `AttributeError: 'list' object has no attribute 'get'`
  → 进程中止。
- **潜伏机制（重要）**: 该分支此前**永远走不到**（"发现硬件"必先失败于废弃账号 nvidia）。
  一旦把前置故障修好，立刻撞上下游潜伏 bug ⇒ **"修好一个、暴露一个"是正常节奏**，不是改坏了。
  排查顺序: 先确认"这条路径以前跑通过吗"，再怀疑新代码。
- **修法三件套**:
  1. 数据形状兼容（list / dict 都归一成 dict）；
  2. 索引取值判空（`topLevelItem(i)`、`item(r,c)` 可能返回 `None`）；
  3. **渲染总闸**: 槽体拆成 `_on_x()`（try/except → 只写日志 + `traceback.print_exc()`）+ `_render_x()`，
     任何渲染异常都不许冒泡。这样"数据形状变了"最多是日志报错，不会把整个 GUI 带走。
- **验证**: offscreen 里直接调 `_on_x(真实数据)` —— 修复前抛 AttributeError、修复后正常返回，才算过。
- 通用原则: **任何"点按钮"路径的异常都必须被槽内拦住**；宁可功能降级 + 日志。

## 2. 按钮"反应很慢" = 主线程同步 ssh / HTTP
- **先量再改**: offscreen 调用一次并记时 → 塔灯 `_tower_cmd` **阻塞主线程 5.48s**、夹爪 `_gripper_cmd` 0.39s；
  同时 100ms 的 `_refresh()` 一次只 0.1ms（**无辜**，别去优化它）。
- 根因: 命令函数在主线程 `subprocess.run(["ssh", ...])` 或 `requests.get(timeout=4~10)` ⇒ 点一下冻住几秒。
- 修法（复用仓库既有通道，别自造线程机制）: `_hw_async(work, label)` 把阻塞部分丢子线程，
  结果经 **`_oneshot(self, 0, lambda: self._apply(res))`** 回主线程（纯 Python 队列 + 主线程 QTimer 轮询，
  即"跨线程 Segfault 根治"那套）；worker 线程零 Qt 接触；命令函数只保留"立即反馈 + 起线程"。
- **反向教训**: 不要拿"某个现役服务 CPU 只有 0.1%"当优秀样板 —— 先看它在等什么
  （本案它在等 2s 的 HTTP 超时，所以 CPU 低）。CPU 归因用**变体二分**（全关 / 开一半 / 全开）
  或让脚本自报 `resource.getrusage`，不要靠猜。

## 3. 版本号 = 五处同步 + 提交前清 reports（取代旧"三处"说法）
小版本升级实际落点:
1. `tools/gui/studio.py` — 窗口标题 ×2（正常 + ⚠️非调试模式）+ `QLabel("Z-MAX vX.Y.Z")`；
2. 同文件顶部 **changelog 摘要注释新增一行前缀**（锚点 = 上一版 `# vX.Y.Z:`）；
3. `update_checker.py` `CURRENT_VERSION`；
4. `version_sync.py` `zmax_ver`（**不带 v**）；
5. `docs_sync.py` 的 `"version"` 与 `"zmax_version"` 两键；
6. `docs/VERSION.md` **版本历史表插到最上**（新条目在最前）。
验收: `grep -c "vX.Y.Z" studio.py` = **3**（版本号）+1（摘要注释）；`ast.parse` 过；
`git tag vX.Y.Z` + push；`git ls-remote --tags origin | grep vX.Y.Z` 复核远端。
⚠️ **提交前先看 `reports/`**: 证据视频动辄 GB 级（当天 283 个 >1MB 文件 ≈ 1.74GB）。
先补 `.gitignore`（`reports/**/*.mp4|avi|zip|tar.gz`），再写 `reports/EVIDENCE_MANIFEST_<日期>.md`
（大文件只记路径+体积，小文件才入库）；否则 `git add reports/` 会把几百个文件（含 GB 级 mp4）一起吞进提交。
`git status` 会把未跟踪目录折叠成一行，**别用行数判断规模** —— 用 `find`/`du` 核实。

## 4. pkill 自匹配的完整规则（补充 SKILL.md 的方括号技巧）
- 方括号技巧（`pkill -f "[s]tudio.py"`）只在"目标名只出现在方括号里"时有效。
- **反例（本会话连踩三次）**: 同一条命令行里**别处**出现明文进程名时照样自杀 ——
  典型是"杀 + 起/查"写在一条里：`pkill -f "[s]s_edge.py"; ... python3 tools/ss_edge.py ...`
  → 整条 bash -c 命令行含明文 `ss_edge.py` → pkill 命中自己 → **ssh 退出码 255，后续命令全部不执行**。
- 规则: **杀与起必须分两次调用**；`--dry` 自检同理不要和启动写一条。
- 量 pid 时过滤掉 shell 自己: `ps -eo pid,comm,args | awk '$2=="python3" && /<脚本名>/ {print $1}'`
  （只看 `comm == python3` 的进程，bash/ssh 命令行不会被算进去）。
- 远程 `ssh host 'bash -lc "…"'` 里的 `echo` 不能带括号/花括号（`echo === 自检 (dry) ===` → bash 语法错误）；
  远程复杂逻辑一律写成脚本 scp 过去再跑。
