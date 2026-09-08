# 远程 GPU 容器同步/训练调试手册 (2026-08-09 实战沉淀)

老倪多轮"没反应/还是这样/你干啥嫩/容器赶紧反馈啊"的完整排查链。按下面顺序排查: ①转义 ②日志丢失 ③旧进程。

## 1. SSH 命令 f-string 转义阶梯 (最易踩坑, 必看)

Python f-string → 本地 shell → 远程 shell → awk/docker --format，每层转义一次。

- **awk 取磁盘**: 源码 `awk '{{print \\$3, \\$5}}'`(f-string 内 2 个反斜杠)
  → 渲染 `\$3` → 本地双引号内 → awk 收到 `$3` ✅
  - 写成 4 反斜杠 (`\\\\$3`) 渲染 `\\$3` → awk 报 `unexpected character '\'` → check_output 抛异常 → **连接静默失败回退本地引擎**(用户只见"训练引擎 → 本地 GPU")。
- **docker images --format (单引号包裹的远程命令)**: 源码 `\"`(f-string 内 1 反斜杠)
  → 渲染 `"` ✅
  - 写成 `\\\"` 渲染 `\"`(反斜杠+引号) → docker 解析失败 → 查询空 → 上传短路失效 → 卡 28GB 打包。
- **验证法(每次改完必做)**: 用 `eval()` 求值 f-string 行看渲染结果, 再原样跑渲染出的完整命令
  (`sshpass -p ... ssh ... '远程cmd'`), 断言 exit 0 + 期望输出出现。
- **别被终端 repr 骗**: `git show` / `sed` / `repr()` 输出还会再转义一次, 看似 4 反斜杠实际文件可能只有 2。
  数反斜杠用 Python: `re.search(r'... (\\+)"', line)` 取 len, 或直接 `eval` 那行 f-string。
- 测试脚本必须用 `/usr/bin/python3`(有 PyQt5); execute_code 沙箱无 PyQt5, 只在纯 AST/正则断言时用。

## 2. ~/.zmax_ssh.json 双结构兼容 (读写端都要)

文件可能被写成 扁平 `{host,port,user,pwd}` 或 嵌套 `{gpu_4090:{...}, gpu_v100:{...}}`。

- **读取端**(`_auto_connect_gpu` / `_connect_gpu` / 上传探测): 兼容两者,
  优先 gpu_4090; `c.get('pwd', c.get('password', ''))` 双键回退。
- **保存端**: 合并更新 gpu_4090, 保留 gpu_v100; 旧扁平结构归入 gpu_v100。
- **大坑**: 运行中的控制台会把当时 UI 输入 dump 进 json, 覆盖你手写的结构 —
  改完文件必须确认进程已重启, 否则又被冲掉(本次文件被覆盖成扁平+pwd=错误命令, 连接全废)。
- 三台 GPU: 本机 4060 8G / V100 32G (223.109.239.36:24340) / 4090 24G (223.109.239.30:15032)。

## 3. PyQt5 子线程日志丢失 (核心根因, 症状迷惑性最强)

- **症状**: 点击按钮只出主线程第一条日志("🐳 容器同步开始…"), 线程里后续日志全丢。
  用户以为功能没反应/没改, 实际是日志没显示到 UI。
- `QTimer.singleShot(0, fn)` 跨线程在 PyQt5 下丢消息; `QMetaObject.invokeMethod(字符串槽)`
  只认 C++ 原生槽, Python `@pyqtSlot` 方法不一定能调到。
- **正解: 线程安全队列 + 主线程 QTimer flush**:
  - `__init__`: `self._log_queue = []; self._log_flush_timer = QTimer(self);`
    `timeout→self._flush_log_queue; start(200)`
  - `_log`: 主线程直接 `_append_log(text)`; 子线程 `self._log_queue.append(text)`
  - `_flush_log_queue`: 交换队列 + 遍历 `_append_log`
- **验证**: offscreen 实例化 + monkeypatch `_append_log` 计数, 调 `_upload_container` 等线程函数,
  QTimer 8s 后断言子线程日志("检测远程"/"🎉无需上传")全部出现。修复前只有 1 条, 修复后 6 条全出。

## 4. 重启后必须验证进程版本 (用户"还是这样"的高频原因)

- 每次改完重启后: `ps aux | grep studio.py | grep -v grep | wc -l` == 2,
  且 `git log --oneline -1` == 刚提交的 HEAD。窗口里的旧进程不会自动更新代码。
- 用户明确要求"删掉旧代码/旧进程": 用 `process kill session` 逐个杀(禁 pkill 自杀坑),
  确认计数归零再启动新的。
- **git 提交前先 `git status`**: cherry-pick/rebase 进行中时 commit 失败, 且
  `git cherry-pick --abort` 会还原工作区(已改的文件被打回 HEAD)。工作区常被
  rollout 产物/config 残留污染 → 一律选择性 `git add tools/gui/studio.py`。

## 5. 容器同步/上传短路逻辑 (别传 28GB)

- 本地镜像可能是 `zmax-std:1.0` 而非 `zmax-train` — 检测必须双命名兼容,
  否则误判"无镜像" → 走远程构建 (git pull 冲突挂死, 用户等几分钟没动静)。
- **远程已有 zmax 镜像直接短路**: 先查 `docker images | grep -E "zmax-(train|std)"`,
  有就打印 `🎉 无需上传`, return。远程 4090 已有 std/v7/v8 23.xGB。
- 传输用 Python 分块管道: `8MB read → p.stdin.write → ssh 'cat > /tmp/zmax-train.tar'`,
  每 1% 变化打 `百分比 · 已传/总GB · 速率GB/s` — 老倪明确要求"拷贝状态百分比"。
- rsync `--info=progress2` 用 \r 刷新, Python 行迭代卡到进程结束才输出 — 别用它做实时进度。

## 6. 远程训练日志实时拉流 (老倪: "远程信息得详细显示")

- 提交存活后 `_start_remote_log_stream()`: QTimer 5s → `_poll_remote_log`
- 增量: `docker ps -q --filter name=zmax_train | head -1; echo ---; tail -n +{lines+1} /tmp/remote_train.log`
- 打印新行加 `📡` 前缀; 容器退出(`docker ps` 空) → 打"日志流停止"并 stop timer。
- 每 5 秒 SSH 一次, tail 行号递增去重; 与 30s checkpoint 轮询并存。

## 7. 用户反馈节奏 (老倪风格)

- 上传/训练必须实时百分比 + 日志流, 不允许"开始…"后黑盒静默。
- "没变化 / 还没开始 / 你干啥" 三连 → 按 ①转义 ②日志丢失 ③旧进程 顺序排查, 别在错误层打转。
- 每次交互都要有即时可见反馈(按钮禁用/日志/状态条), 反馈=按钮+日志+气泡。
