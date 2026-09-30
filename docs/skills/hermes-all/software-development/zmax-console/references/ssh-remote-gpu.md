# SSH 远程 GPU 服务器 (2026-08-09 实测)

## 服务器清单 (凭据存 ~/.zmax_ssh.json, 结构见下)
- gpu_v100: 223.109.239.36:24340 root (V100 32G)
- gpu_4090: 223.109.239.30:15032 root (RTX 4090 24G, CUDA 12.4) — 老倪新加的远程训练机
- 通用坑: `-p 24340` 会被吞 → 必须 `-o Port=24340`; 探针 3s 连不上即明说

## ⚠️ ~/.zmax_ssh.json 结构: 扁平 vs 嵌套 双兼容 (VEH.2.08 连不上的真根因)
- 2026-08-09 把 json 从扁平 `{"host","port","user","pwd"}` 改成嵌套 `{"gpu_v100":{...},"gpu_4090":{...}}`
- **代码读取端 (studio.py 2399-2407) 只认扁平 `_cred.get("pwd")`** → 嵌套结构下 pwd 取到 None → 控制台"连接"失败
- 运行中控制台的 `_connect_gpu` (3890) 会把**界面上当前填的 ssh_pass 原文 dump 回 json** — 若用户误把整条 `ssh root@... -p 15032` 填进密码框, json 就被污染成错误密码 (本次真实发生)
- 修复 = 双向兼容:
  - **加载端**: 有 `"host"` key → 扁平; 否则 `_cred.get("gpu_4090") or _cred.get("gpu_v100")` (优先 4090 最近连接)
  - **保存端**: 读旧 json → 扁平自动归入 `gpu_v100` → `_old.setdefault("gpu_4090", {}).update(new)` 合并更新, 保留两台
- 排查顺序: 连不上 → 先 `cat ~/.zmax_ssh.json` 看 pwd 是不是被污染成命令文本; 再查加载端读的是扁平还是嵌套

### ⚠️ 第 5 处同源坑: _auto_connect_gpu 自动连接也用旧扁平字段 (老倪: \"没变化, 再改\")
- 症状: 控制台启动日志恒定 `⚠️ 远程 GPU 连不上 (已关机/网络不通) — 使用本地引擎` — **即使服务器明明在线**
- 真根因: `_auto_connect_gpu` 读凭据用的是旧扁平字段 `creds.get(\"port\")` + `creds.get(\"password\")`, 而 json 已是嵌套 `gpu_4090/gpu_v100` → 取到空 host/port/pwd → 探测必然失败 → 永远走本地引擎。**跟 VEH.2.08 连接按钮是同一个扁平/嵌套错位的病, 只是第二个读点** — 改 json 结构时必须 grep 全部读点 (加载端 / _connect_gpu 保存端 / _auto_connect_gpu / _poll_remote_env 等), 一个都不能漏
- 修复: `if \"host\" in creds: c=creds else: c=creds.get(\"gpu_4090\") or creds.get(\"gpu_v100\") or {}`; pwd 用 `c.get('pwd', c.get('password', ''))` 双键回退 (兼容旧 password 字段名)
- 教训: 用户日志里重复出现 `训练引擎 → 本地 GPU` + 口头说\"已连接\" → 先查**所有**凭据读点, 别只修界面连接按钮

## 新服务器 nvidia-container-toolkit 安装 (docker --gpus all 报 could not select device driver)
- 机器无 curl → 用 wget; gpg 报 "cannot open /dev/tty" → 用 `gpg --batch --yes --dearmor -o key < <(wget -qO- URL)`
- 步骤: wget gpgkey → dearmor 到 /usr/share/keyrings → 写 sources.list (sed 加 signed-by) → apt update → apt install nvidia-container-toolkit → `nvidia-ctk runtime configure --runtime=docker` → `systemctl restart docker` → 验证 `docker info | grep -A3 Runtimes` 出现 nvidia
- 冒烟: `docker run --rm --gpus all --entrypoint nvidia-smi zmax-train:latest`

## 容器同步 (VEH.2 页 上传本地容器给远程) — 老倪要详细进度
- 功能 = docker save 本地 zmax-train → 传到远程 → docker load (远程训练用同一容器)
- 2026-08-09 老倪: "看不到上传的信息" (第一次修复) → scp 换成 **rsync --info=progress2** (实时百分比/速率逐行 _log)
- 三阶段日志: ① docker save 打包 (大小 GB + 耗时) ② rsync 实时进度 + 平均 GB/s ③ 远程 docker load 结果 + docker images 确认 + 清理 tar
- 远程仓库有未提交改动时 `git pull` 会冲突 (config_act_metaworld.yaml / reports/*.json) → 远程构建链路失败, 需先 stash/commit 远端

### ⚠️ 第二次修复 (老倪: "还是不对, 看不到上传信息") — 两个真根因
1. **远程未连接时静默 return**: 原代码 `re_ = remote_engine` 在 docker 检测**之后**, `if re_:` 为假直接 `return` — 用户只看到"🐳 容器同步开始…"再无下文。修复: 函数开头先查 `re_`, 未连接 → 明说 "❌ 未连接远程 GPU — 请先点「🔌 连接」" + 当前远程状态, 再 return。**任何异步长任务开头先做前置守卫 + 明说失败原因, 不要静默退出**
2. **rsync --info=progress2 的实时输出 Python 读不到**: progress2 用 `\r` 刷新不换行, `for line in p.stdout` 会**卡到 rsync 进程结束**才 flush → 传输期间一条进度都不显示。**教训: 要实时进度别解析 stdout (尤其 \r 刷新), 别依赖第三方工具的输出格式**

### ✅ 第三次修复 = 定稿 (老倪: "你得显示拷贝的状态, 百分比") — 弃 rsync, 改分块管道直写
- **方案**: `sshpass ssh 'cat > /tmp/zmax-train.tar'` 开 Popen(stdin=PIPE), Python 侧 `open(savef,"rb")` 循环 `read(8MB)` → `_p.stdin.write(chunk)` → `sent += len(chunk)` → `pct = int(sent/sz_b*100)` → **每 1% 变化 `_log(f"  {pct:3d}% · {sent/1e9:.2f}/{sz_b/1e9:.2f}GB · {spd:.2f}GB/s")`**
- 最后 `_p.stdin.close()` → `_p.wait(timeout=3600)`; finally 里 try close stdin 防 BrokenPipe
- 百分比/速率完全由 Python 自己算, 不依赖 rsync 输出、不依赖远程 stat 轮询 — 传输进度彻底可见
- 定稿日志形态: `① 打包本地镜像… (约几分钟)` → `① 打包完成: X.XGB · 耗时 Ns` → `② 传输到 host:port (X.XXGB) …` → `  1% · 0.02/5.13GB · 0.02GB/s` → ... → `② 传输完成 · 耗时 Ns · 平均 X.XXGB/s` → `③ 远程载入: ... · 耗时 Ns` → `✅ 容器已上传远程`
- f-string 里嵌 docker `--format "{{.Repository}}:{{.Tag}}"` 的转义: Python 层 `\"` + 模板 `{{{{.Repository}}}}` (四花括号), 别多转义成 `\\\\\"` (会坏, 冒烟验证必查)

### ✅ 第四次修复 (老倪: "还是这样, 还没开始, 改") — 上传前连通性探测 + 重启确认
- **识别信号**: 用户日志连续出现 `训练引擎 → 本地 GPU (RTX 4060)` = `remote_engine` 为 None 的指示器 (连接失败回退本地)。老倪口头说"远程已经连接了"但日志显示本地 → **别信口头, 以日志/实测为准**
- `_upload_container` 开头 (守卫之后、docker 检测之前) 加探测: `sshpass ssh 'echo REMOTE_OK'` (ConnectTimeout=8, timeout=20) → 成功打 `└ ✅ 远程可达 (host:port) — 开始同步`; 失败打 `└ ❌ 远程不可达 — SSH 失败: <stderr>` + "请确认远程已开机/网络通, 或重新点「🔌 连接」" 然后 return
- **排查第一步永远是确认运行中进程加载的是最新代码**: 改完 GUI 必须 kill + 重启 (老倪窗口里点按钮看到旧行为 = 进程还是旧 commit)。`git log -1` 对不上运行中 pid 的行为时, 先重启再看
- **上传前先查远程已有镜像**: 实测 4090 上已有 `zmax-train:std` 23.9GB (docker images) — 若远程已有同名/近版容器, 可能不用传 26GB 大包 (先问老倪要 tag 复用还是重传)

## ⚠️ 第五次修复 (老倪: "没变化, 改") — _connect_gpu 的 awk f-string 转义是连接失败真根因
- **识别信号**: `_auto_connect_gpu` 已打 `✅ 远程 GPU 可达 — 自动连接` (探测用简单 `echo OK` 能过), 但紧接着 `训练引擎 → 本地 GPU` ×2 → remote_engine 被设回 None → 点上传又被守卫拦。**探测命令能过 ≠ 连接命令能过** — 两者是不同 cmd
- **真根因**: `_connect_gpu._worker` 的远程命令含 `awk '{print $3, $5}'`, 源码 f-string 写成 `\\\\$3` (四反斜杠) → 渲染给 shell 的是 `\\$3` → 远程 awk 收到 `\` → 报 `awk: 1: unexpected character '\'` → `check_output` 抛异常 → 走 except → `remote_engine=None` + `_set_engine_ui(False)` → "训练引擎 → 本地 GPU"
- **修复**: f-string 里必须恰好 **2 个反斜杠** `\\$3` → 渲染 `\$3` → shell 双引号内转义 → awk 收到 `$3`。三层转义链: Python f-string → 本地 shell (双引号) → 远程 awk。每层剥一层: 4→2→1→awk $3
- **排查方法 (可复用)**: 把 f-string 拼出的 cmd 完整 print 出来 + 本地 `sp.run(cmd, shell=True)` 实测 exit code — awk 报错立现。别猜, 直接复现生成的命令串
- 顺手补: `remote_engine` 字典加 `"connected": True` — `_auto_connect_gpu` 用它判断已连接防重复自动连接 (原结构无此键, `remote_engine.get("connected")` 恒 None → 每次启动都重新自动连)
- **f-string 嵌 shell 命令的转义铁律**: 要进嵌套 shell/awk 的 `$变量`, f-string 写 `\\$` (2 反斜杠); 别随手多打反斜杠, 也别用单反斜杠触发 SyntaxWarning (`\$` 是无效转义序列警告)。改完必跑真实命令冒烟 (exit 0 + 输出含预期字段), 语法检查通过 ≠ 运行时正确

## ⚠️ 第六次修复 (老倪: "你到底是不是在转送啊") — 本地镜像名 zmax-std ≠ 检测的 zmax-train
- **识别信号**: 连接已成功 (`训练引擎 → 远程 GPU`), 点容器同步后只有 "🐳 容器同步开始…" 再无下文, 用户怀疑根本没在传
- **真根因**: `_upload_container` 本地镜像检测写死 `"zmax-train" in docker_images_stdout`, 但本地实际镜像名是 **`zmax-std:1.0` (28GB)** → `has_local=False` → 误走"本地无 docker → 远程构建"分支 → 远程 `git pull` 又因远端未提交改动 (config_act_metaworld.yaml / reports/*.json) 冲突 → 整条链路挂死, 用户干等几分钟
- **修复 (双管齐下)**:
  1. **本地检测兼容双命名**: 遍历 `docker images` 输出, `_nm in ("zmax-train", "zmax-std")` 取实际存在的镜像名 `_img`, docker save 用 `_img` 而非硬编码 `zmax-train:latest`
  2. **远程已有镜像短路 (关键省时)**: 检测本地之前先 SSH 查远程 `docker images | grep -E "zmax-(train|std)"` — 有就直接 `_log("✅ 远程已有: ...") + "🎉 无需上传 — 远程镜像已就绪"` 并 return, **不传 28GB 大包**。实测 4090 已有 zmax-train:std 23.9GB / v8 / v7, 上传秒跳过
- **教训**: 硬编码镜像名/路径是定时炸弹 — 本地和远程的容器命名可能不同 (zmax-std vs zmax-train), 检测时取"实际存在的名字"而不是假设一个名字; 传输大文件前先问"对面是不是已经有了"
- **通用铁律 (老倪反复踩)**: 用户报"点了没反应/没变化"时, 排查链 = ① 进程加载的是不是最新 commit (改完必 kill+重启) ② 有没有前置守卫把失败原因写进日志 ③ 真实复现命令冒烟 (别只看语法) ④ 是不是硬编码名字/路径与实际情况不符

## ⚠️ 第七次排查 ("还是没改/没反应") — 转义误判 + git cherry-pick 残留
- **假警报教训**: 用 `grep -n` / `cat -A` 看含反斜杠的 f-string 源码行, 终端显示的反斜杠数量**不可靠** (repr 会翻倍, grep 原样输出也易数错)。本次花了几轮以为 `\\"` 转义坏了, 实际 `git diff tools/gui/studio.py` **为空** (工作区==HEAD, 代码没被改坏) + `eval()` 该 f-string 行渲染结果完全正确 + 真实命令 exit 0。**判定转义是否坏的正确顺序: ① `git diff` 空 = 没改动别瞎猜 ② `eval(该行)` 看渲染结果 ③ 跑真实命令冒烟 — 别用肉眼数终端里的反斜杠**
- **git cherry-pick in progress 恢复**: 本地 repo 可能遗留 `cherry-pick` 进行中状态 (提示 "Cherry-pick currently in progress"), `git commit` 会拒。恢复: `git cherry-pick --abort` (有 warning "You seem to have moved HEAD" 也正常) → `git checkout -- tools/gui/studio.py` 还原工作区 → 重新选择性 `git add tools/gui/studio.py` 再 commit。**⚠️ 绝不用 `git add -A`/`git add .`** — 工作区常被 rollout 产物 (reports/*.mp4, frames/*.png, config_*.yaml) 污染, 全加会把这些大文件扫进提交; 永远选择性 add 本版相关文件
- **进程版本确认**: 用户"没反应"时先 `ps aux | grep studio.py` 看 pid 启动时间是否晚于 `git log -1` 的 commit 时间; 改完 GUI 必 kill + 重启 (老倪窗口里可能一直挂着旧进程, 重启后行为才对得上新代码)

## ⚠️ 第八次修复 = 最终根因 (老倪: "容器赶紧反馈啊" / "删掉原来的旧代码。删掉旧进程") — 子线程日志丢失

- **识别信号**: 连接已成功 (`✅ 远程 GPU 可达` + `训练引擎 → 远程 GPU`), 点容器同步后**依然只有 "🐳 容器同步开始…" 再无下文** — 连转义/镜像名/短路全修完还是这样。此时所有代码逻辑都对 (守卫/探测/查询全在), 问题在**日志本身显示不出来**
- **真根因**: `_log` 的非主线程分支用 `QTimer.singleShot(0, lambda...)` (旧版) 或 `QMetaObject.invokeMethod(self, "_append_log", Qt.QueuedConnection, Q_ARG(str, text))` (改版) 跨线程调度 → **PyQt5 下这两种方式都会丢消息** → 线程里打的所有日志 (检测远程/可达/查询/百分比) 一条都不显示 → 用户只看到主线程打的第一条"开始…"
- **调试方法 (可复用, 关键)**: monkeypatch `_log` 本体直接 `append` (绕过一切调度) — 若日志全出 = 线程在跑、逻辑对, 问题 100% 在调度层; 若还缺 = 线程没启动/逻辑断。**用 loud-log 隔离法分清"线程没跑" vs "日志调度坏", 别在错误层排查**
- **修复 (定稿) = 线程安全队列 + 主线程 QTimer flush**:
  ```python
  # __init__ (log_text 创建后):
  self._log_queue = []
  self._log_flush_timer = QTimer(self)
  self._log_flush_timer.timeout.connect(self._flush_log_queue)
  self._log_flush_timer.start(200)
  # _log 非主线程分支:
  self._log_queue.append(text)
  # 新方法 (主线程定时冲刷):
  def _flush_log_queue(self):
      q = self._log_queue
      if q:
          self._log_queue = []
          for t in q: self._append_log(t)
  # _append_log 加 @pyqtSlot(str) (invokeMethod 方案需要; 队列方案无害)
  ```
- **验证**: offscreen 实例化 TrainingModule + 设 remote_engine + 调 `_upload_container` + 等 8-9s → 断言日志含 `检测远程` 与 `无需上传`。**注意: offscreen 冒烟脚本必须用 `/usr/bin/python3` 跑 (沙箱 python 无 PyQt5), 写成文件放 /tmp 再 terminal 执行**
- **教训**: 跨线程 UI 更新 (日志/进度) 的可靠模式 = 子线程入队 + 主线程 QTimer 周期 flush, **不要用 singleShot(0)/invokeMethod 字符串槽** (PyQt5 下不可靠); 老倪连续多轮"没反应"时, 前面的修复可能全对但被日志层掩盖, 排查到"代码全对但用户看不到"就要怀疑显示链路本身

## ⚠️ 容器同步最终定稿判断 (2026-08-09 收尾)
- 判定"是否真修好"的三重证据: ① `git diff` 空 = 工作区与 HEAD 一致 (改动已提交) ② `eval(f-string行)` 渲染正确 + 真实 SSH 命令 exit 0 ③ **offscreen 运行时冒烟: 用原始 `_log` (零 monkeypatch) 跑完整 `_upload_container` → 日志全出** (开始→检测→✅可达→查询→✅已有→🎉无需上传, 全链路 1 秒内)

## ⚠️ 第九次修复 (老倪: "远程信息，得详细显示" / "没有滚动日志") — 远程训练日志要看 docker logs, 不是 /tmp 文件
- **识别信号**: 远程容器训练提交后, 控制台只有一条 "🐳 远程容器训练已启动 … · 日志 /tmp/remote_train.log", 然后日志流拉回来的只有一行**容器 ID** (64位hex), 没有训练输出; 几秒后 "容器已退出"
- **真根因 (docker 常识坑)**: 提交命令是 `docker run -d ... > /tmp/remote_train.log 2>&1` — `-d` 模式下 **`>` 重定向的是 `docker run` 命令本身的 stdout = 容器 ID**, 容器内部训练日志根本没进这个文件。真实训练日志在 `docker logs zmax_train` 里
- **修复**: 日志流命令从 `tail -n +N /tmp/remote_train.log` 改成 `docker ps -q --filter name=zmax_train | head -1; echo ---; docker logs zmax_train 2>&1 | tail -n +N` (行数游标照旧, 容器退出时再拉一次最终日志再停)。两处同改: studio.py `_poll_remote_log` + simulink_module.py `_rstream` (Model Zoo 队列走的是 simulink 路径, studio 路径只覆盖直接 Start 按钮 — **用户报日志问题时两个提交入口都要查**)
- **"容器已退出"误报**: 日志流线程用 `docker ps` 匹配容器名, 但 simulink 提交时 `docker rm -f zmax_train; docker run -d` 会换新容器 ID → 旧线程看到旧 ID 消失就停。可接受 (新提交会开新流); 若反复, 改成按容器名而非 ID 判断
- **验证**: 真实 SSH `docker logs zmax_train | tail -3` 必须能看到 `ot_train.py Creating dataset / Creating policy / torchcodec 警告` 等训练初始化输出 — 只有容器 ID 就是重定向搞错了

## 老倪: "远程的容器，是你上传的么？我得看到路径，看到实际的上传过程"
- **回答前先查来源, 别猜**: `docker images --format '{{.Repository}}:{{.Tag}} | ID {{.ID}} | {{.Size}} | 创建 {{.CreatedSince}}'` — 本次实测 4090 上 zmax-train 系列 10 个镜像全是 **16-19 小时前创建** (std/v8/v7/v6/v5/final/latest/v4/v3), 即**在 4090 服务器上直接构建的, 不是任何人上传的**; 且 `ls /tmp/zmax-train.tar` 不存在 → 没有传过 tar。用"创建时间 + 无 tar + 磁盘 docker system df"三证据回答
- **上传路径透明化 (已在 _upload_container 实现)**: 远程已有镜像时不静默跳过, 而是打印 ① 远程镜像列表 (前3个) ② 镜像存储路径 ③ 磁盘余量; 并提示"再点一次 = 强制重新上传"(计数器 `_upload_force_cnt` 连续两次触发真传, 走分块管道百分比)
- **⚠️ 存储路径空的真根因 — 远程 docker 版本不支持 `{{.GraphDriver}}`**: `docker inspect --format '{{.GraphDriver.Data.UpperDir}}'` 报 `template parsing error: map has no entry for key "GraphDriver"` (部分 docker 版本的 image inspect 不提供该字段) → 打印为空。**改用三连简单命令 (无嵌套转义)**: `docker inspect --format '{{.Id}}' | cut -c8-19` (短 ID) + `docker info --format '{{.DockerRootDir}}'` (存储根目录, 实测 /var/lib/docker) + `df -h / | tail -1` (磁盘) — 三行各自独立, 无 awk 无嵌套引号, 转义零风险
- **教训: 复杂转义的命令段, 优先改成"无 awk / 无嵌套引号"的简单命令**, 而不是继续在多层转义里调参数。本次 awk 内嵌 `{{print \$2, \$4}}` 反复坏 (patch 每次重写都引入新转义错误), 换成三个独立简单命令后一次通过
- **教训**: 用户问"这是你传的吗/路径在哪" = 要**可追溯证据** (创建时间/存储路径/传输日志), 不是要你口头保证; 涉及 28GB 大文件时"对面已存在且更合适"比"重新传"更有价值

## ⚠️ 工具坑: patch 工具在复杂 f-string 转义上反复失败 → 用 Python 字节级/行级替换
- 本次多次出现: 用 patch 工具改含 `\\\"`/`\\\\$3`/`{{{{.Repository}}}}` 的 f-string 行, patch 的 old_string/new_string 匹配或转义层数错位, 把文件改出 SyntaxError (常见: f-string 拼接列表漏行尾逗号、反斜杠多一层少一层)
- **正确姿势 (定稿)**: ① `git checkout -- tools/gui/studio.py` 恢复 ② 用 execute_code 按**行号定位** (`for i,l in enumerate(lines) if 特征 in l`), 用 `chr(92)` 显式拼反斜杠数, `lines[idx] = new_line` 整行替换, 写回 ③ 立刻 `ast.parse` 验证 ④ eval 该 f-string 行看渲染结果 ⑤ 真实命令冒烟
- **f-string 拼接列表 (多段 f"..." 相邻) 每段末尾必须保留逗号** — 行替换时最容易丢的是行尾 `,` (本次 3474 行丢逗号导致 `SyntaxError: invalid syntax. Perhaps you forgot a comma?`)
- patch 工具适合普通文本; 含转义深渊的 shell 命令构造一律走 Python 字节级替换

## 小坑: QTextEdit padding 8px → 光标/行距视觉两倍 (老倪: "你的光标也太大了，相当于两倍行高")
- log_text QSS `padding: 8px` 上下留白会让 QTextEdit 内每行视觉间距翻倍 (光标/行高看起来 2x)
- 修: `padding: 2px 4px` (上下 2px 左右 4px) — 保留左右留白舒适度, 消掉上下虚高
- 经验: QSS padding 在 QTextEdit 上会同时放大"视觉行距", 报"光标太大/行高两倍"先查 padding 而非 font-size
- **⚠️ 用户报"还是那么大, 也没改啊"时 (padding 已修仍大)**: WSLg 下 `Consolas` 可能回退到其他字体, 行高由回退字体决定 → 必须**显式设置 QFont + 零文档边距**:
  ```python
  _f = QFont("Consolas", 11)
  _f.setStyleHint(QFont.Monospace)   # 强制等宽族, 防回退
  self.log_text.setFont(_f)
  self.log_text.document().setDocumentMargin(0)  # 消除文档默认 4px 边距
  ```
- 光标两倍行高排查链: ① padding (QSS) ② document margin ③ 字体回退 (WSLg 无 Consolas → 设 Monospace style hint) — 别只改一处就以为完事

## ⚠️ 第十次修复 (老倪: "崩溃啦" / "远程容易为什么退出") — cuDNN CUDNN_STATUS_NOT_INITIALIZED 是真根因
- **症状**: 远程训练提交后容器 20-40s 退出 (`docker events` 显示 `execDuration=22, exitCode=1`), 日志流停在 "Creating policy"/"Downloading resnet18", GPU 利用率 0% 12MiB, 无 OOM (dmesg 空)
- **真根因**: zmax-train:latest 镜像 (torch 2.4.1+cu124, cuDNN 9.19) 在驱动 550.127 下**首次 conv2d 必崩** `RuntimeError: cuDNN error: CUDNN_STATUS_NOT_INITIALIZED`。诡异点: `torch.cuda.is_available()` True、`torch.backends.cudnn.version()` 91900、`ctypes.CDLL(libcudnn.so.9)` 加载 OK、`ldd` 依赖齐全 — 但 `F.conv2d` 一跑就崩
- **调试链 (可复用)**: nvidia-smi 正常 → cuda init OK → 纯 `nn.Conv2d(...).cuda()(x)` 崩 → `torch.backends.cudnn.enabled=False` 后 conv OK → 定位到 cuDNN 初始化坏。**逐层缩小: 驱动→cuda→cudnn→conv, 每层一个冒烟命令**
- **修复 (定稿)**: 新增 `remote_train_entry.py` 包装入口:
  ```python
  import torch
  torch.backends.cudnn.enabled = False   # cuDNN 9.19+驱动550 组合 conv 崩 → 禁用回退普通CUDA卷积
  import sys
  sys.argv = ['lerobot_train'] + sys.argv[1:]
  from lerobot.scripts.lerobot_train import main
  main()
  ```
  提交命令改 `python remote_train_entry.py --config_path {cfg}`。**⚠️ 环境变量 `TORCH_CUDNN_ENABLED=0` 不生效 (torch 不读此变量) — 必须代码级禁用**
- **验证**: `docker run --rm --runtime nvidia --gpus all --entrypoint python zmax-train:latest -c "cudnn.enabled=False; Conv2d..."` 打印 CONV_OK
- **容器崩溃诊断法**: 容器被 `docker rm -f` 重建后旧日志全丢 → 用 `docker events --since 15m | grep zmax` 看 `die` 事件的 `exitCode` + `execDuration` (exit 1 = 程序崩, 137 = OOM/kill); 需要保留崩溃现场时先别 rm -f 旧容器

## 远程 GPU 容器运行方式: `--runtime nvidia --gpus all` (不是 --device 透传)
- 4090 装了 nvidia-container-toolkit 1.19.1, daemon.json 有 nvidia runtime — 但**单用 `--gpus all` 报 "Found no NVIDIA driver"**, 该 docker 版本必须**显式 `--runtime nvidia --gpus all`** 才进容器看到 GPU
- 旧代码 `--device /dev/nvidia0 --device /dev/nvidiactl --device /dev/nvidia-uvm -v /usr/lib/.../libcuda.so.1:ro` 设备透传方案整体替换; 三处提交路径统一 (studio `_start_remote_training` + studio `_container_action('train')` + simulink `on_train` ModelZoo) — **grep `--device /dev/nvidia0` 查漏, 一个都不能剩**
- 验证链: `nvidia-container-cli info` 认出 4090 = toolkit 好; `docker info | grep -A2 Runtimes` 有 nvidia = runtime 注册; `--runtime nvidia --gpus all` 的 nvidia-smi 出表 = 容器内可见

## FileExistsError: output_dir 固定名已存在 → 时间戳唯一目录
- **症状**: 远程训练崩 `FileExistsError: Output directory outputs/train/act_metaworld_final already exists and resume is False` — config 里 output_dir 硬编码固定名, 上次训练留了目录, resume:False 拒绝覆盖
- **修复**: 提交命令加一条 sed 把 output_dir 改成时间戳目录 (两处提交路径都加):
  - simulink: 预计算 `_odir = cfg_base.replace(".yaml","") + "_$(date +%Y%m%d_%H%M%S)"` (f-string 外算好, **避免 f-string 内嵌 `cfg_base.replace(".yaml","")` 的嵌套引号 SyntaxError**) → `sed -i "s|^output_dir: .*|output_dir: outputs/train/{_odir}|" {cfg_base}`
  - studio: `{cfg[:-5]}` 切片去 .yaml (无引号无方法调用, f-string 安全) → `outputs/train/{cfg[:-5]}_$(date +%Y%m%d_%H%M%S)`
- **f-string 内嵌表达式铁律**: 要嵌方法调用/带引号表达式 → 先在 f-string 外算成变量, 或用切片等无引号写法; f-string 里 `{cfg_base.replace(".yaml","")}` 直接 SyntaxError (unmatched '(')

## 模型拉回链路 (老倪: 训练结果拉回本地, 模型引擎可见可编辑路径, Simulink 推理/报告/视频)
- **触发**: `_poll_remote_log` 容器退出分支 (`if not alive`) → `_pull_remote_model()`
- **步骤**: 远程 `ls -dt outputs/train/<cfg_full>_* | head -1` (注意 **config_ 前缀**: output_dir sed 用完整 cfg 名 → `config_act_metaworld_<ts>`, glob 必须用 `_cfg_full` 而非去掉 config_ 的 name) → 找 `checkpoints/*/pretrained_model | sort | tail -1` → `scp -r` 到本地 `outputs/train/<name>_<ts>/checkpoints/last/pretrained_model` → 写 `reports/train_curve_<policy>.json` (ckpt 记录, **Simulink rollout 按此消费**) → 注册 `models/saved/registry.json` → 回填 `ckpt_edit.setText` + `_refresh_saved_models()`
- **⚠️ policy 名 ≠ config 名**: rollout_video.py 读 `train_curve_<policy>.json` (policy = act/smolvla/smolvla_lew/vla_touch/awe_zflow/expert_mlp/expert_policy), 不是 config 名 (act_metaworld) → `_start_remote_progress_poll` 记录 `_remote_policy` 从 model_combo 映射 `{"ACT":"act","SmolVLA":"smolvla","SmolVLA+LEW":"smolvla_lew","VLA-Touch":"vla_touch","AWE":"awe_zflow","MLP 蒸馏":"expert_mlp","官方专家":"expert_policy"}`; curve json 用 `_pol` 命名
- **Simulink 消费端已通**: 拉回写了 train_curve_<policy>.json + 本地 outputs/train/<name>_<ts>/checkpoints/last/pretrained_model → 双击 rollout 推理节点 (rollout_video.py --policy <pol>) 自动按 ckpt 记录加载 → 出视频/报告。模型引擎 ckpt_edit (可编辑路径) + saved_combo (registry.json 下拉) 天然可复用
- **模型拉回是串行 scp (大文件可能几分钟)**: 放后台线程, 每步打日志 (找目录/找ckpt/scp中/写curve/注册/回填), 失败不静默

## ⚠️ 第十一次修复 (老倪: "你都显示自动交付了, 怎么回事?") — Model Zoo 队列完成判定被远程模式打破
- **症状**: 远程容器训练提交后, 控制台每 15 秒刷一条 `🏁 Model Zoo 完整训练完成` + `📤 自动交付: 生成 rollout 视频 + PDF 报告 → 飞书…`, 无限循环, 且每次真的调用 `_auto_finalize()` (白烧 GPU/CPU 生成视频+PDF+发飞书)
- **真根因**: Model Zoo 队列 (`_zoo_next`) 的完成判定是给**本地训练**设计的: `pgrep -f lerobot_train` 看本地进程。远程容器训练时**本地没有 lerobot_train 进程** → 每轮 15s 轮询都判定"训练完成" → 走完成分支 → 触发自动交付。而且 on_train 提交远程后 `_zoo_queue.pop(0)` 队列已空, 下一轮直接进空队列分支
- **修复 (双管齐下)**:
  1. **防重复交付标志**: 完成分支加 `_zoo_finalized` — 已交付过直接 return (否则 15s 轮询无限触发); 每次新训练启动 (`_zoo_queue.pop(0)` 后) 重置 `_zoo_finalized = False`
  2. **远程等待**: on_train 返回 `(True, "xxx 容器化远程提交")` 时设 `_zoo_remote_wait = pol`; `_zoo_next` 轮询开头若 `_zoo_remote_wait` 存在 → SSH 查 `docker ps -q --filter name=zmax_train` → 在跑则 return 等下一轮, 容器退出才清标志并推进队列。本地训练 (无远程提交) 不受影响, 仍走 pgrep 逻辑
- **识别信号**: 日志区连续多条 `🏁 Model Zoo 完整训练完成` (间隔=轮询周期) = 完成判定条件被打破; 远程模式 (容器提交) 下**任何依赖"本地进程存在"的完成判断都会误判**, 要么改查远程容器, 要么加防重
- **教训**: 架构从"本地训练"切到"远程容器训练"后, 队列/轮询/完成判定的语义全变了 — 改执行后端时 grep 所有"怎么判断训练结束"的读点 (pgrep/进程数/超时窗口), 别只改提交命令
- **验证**: 断言之类静态检查外, 需注意 `_zoo_next` 函数已很长 (窗口截取要放到下一个 def 为止); 完成分支 + 远程等待 + 返回处理三块都要断言

## 用户需求链路: "训练完 → 模型可见 → 可推理出报告视频" 的实现骨架
1. 训练提交时记录 `_remote_cfg` + `_remote_policy` (policy 名是下游消费键)
2. 容器退出 (训练完或崩) → 拉回模型 (scp + 落盘到 rollout 可找的目录结构)
3. 写 `train_curve_<policy>.json` = Simulink 推理/报告/视频的统一消费入口 (rollout_video.py 只认它)
4. 注册 registry + 回填 ckpt_edit → 模型引擎页用户直接看到可编辑路径
5. 验证闭环: 拉回后本地 `ls outputs/train/<name>_<ts>/checkpoints/last/pretrained_model` 存在 + curve json 有 ckpt 字段 → Simulink 双击推理节点可消费
