# simulink 模板节点机制 + SSH 端口坑 + GUI 多实例清理 (2026-08-08)

## simulink REFERENCE_APPS 模板加载机制（关键，踩坑多次）

模板结构 = `(name, node_specs, edges, layout)`。

- **布局引用节点名，但节点必须同时在 node_specs 有定义**——定义缺失 → 布局引用被**静默跳过**（画布缺节点，无任何报错）。「几何条件」事件：把定义从原位移走时只删了、忘了在末尾加回 → 感知链缺 🧩 几何条件，模板加载"成功"但节点不在，用户问"没看到"。
- **同名节点多定义 = 多实例**（每个定义占布局一个位置，`used` 去重）——想要 N 行同列各一个同名节点 → node_specs 写 N 个同名定义。
- **edges 索引 = node_specs 定义顺序索引**——增删定义会整体错位！所以**新节点定义一律放模板末尾**（不占原索引 → edges 全部保持）。
- 共享节点（七模型共用）参数加 `"shared": True`，desc 注明"♻ 七模型共用"。
- 布局位置公式：`x = 120 + col*200`，`y = 80 + row*230`（每列 200 宽 / 每行 230 高）。
- 端口语义：`add_node` 按 ntype 特判 inputs/outputs（如 coord_overlay = inputs [bbox, latent] → outputs [latent+]），默认节点只有 in/out 无语义，用户会嫌"输入输出奇怪"。
- **验证套路**：offscreen 加载模板 → 断言布局链每个节点存在 + x/y 位置正确（x==1120 且 y==80 即感知链列5第0行）。

## sshpass + ssh 端口坑（实测）

- `sshpass -p 'pwd' ssh -p 24212 user@host` —— **`-p` 被吞**，实测连接 port 22 → Connection refused（ssh -v 确认）。
- **改用 `-o Port=24212`**（选项形式）→ 实测成功。
- 已验证 GPU 服务器：`223.109.239.36:24212` root（ubuntu22 · Tesla V100-SXM2-32GB），凭据存 `~/.zmax_ssh.json`（模型引擎 SSH 面板读写，格式 {"host","port","user","pwd"}）。
- 远程状态探测一条命令：`nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader | head -1; echo '---'; ps aux | grep -c '[l]erobot_train'; echo '---'; df -h / | tail -1 | awk '{print $3, $5}'`。

## GUI 多实例 + auto_restart 守护清理

- 飞书端/其他会话会拉起 **auto_restart 守护**（`bash -lic "set +m; cd ... && python3 studio.py > /tmp/studio_restart*.log"`，父进程链到 hermes gateway）——kill studio 后守护**自动拉起新实例**，表现为"崩了又开"、多个 studio 实例并存。
- 清理：`pkill -9 -f 'studio.py'` **会误伤自身终端**（命令行本身含 studio.py → 退出码 -9）。正确做法：`ps aux | grep '[s]tudio.py'` 取 PID 逐个 kill + 找守护 bash（grep studio_restart）kill 守护，然后 ps 确认 0 实例。
- 清完确认 gateway 进程存活（别误杀 hermes gateway）。

## PyInstaller Windows exe 相对路径守卫

- exe 的 cwd = `C:\Users\Admin\AppData\Local` → 裸相对路径（`os.listdir("data")`）→ `FileNotFoundError: [WinError 3]` 启动即崩。
- 任何目录探测必须 `os.path.isdir(root/data)` 守卫 + 绝对路径（`_repo_root()` 拼接）；目录不存在返回空列表不抛异常。
- 验证：mock `_repo_root` 指向不存在路径 → 方法返回空不炸。
