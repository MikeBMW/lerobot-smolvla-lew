# 画布节点 source 映射 + 容器环境打开源代码 (2026-08-18 实测)

## 🔴 核心教训: 新画布节点 params.source 必须配到每个功能节点, 只配背景行不行

**症状**: 老倪报"状态空间画布右键打开源代码打不开"。
**根因**: flows/state_space_obs.json 初版只有 4 个 row_bg 背景行节点带 source,
10 个功能节点(📡传感器融合/⚡前馈加速器/🧭认知调度器等)全无 params.source →
右键功能节点点「打开源代码」只能弹"该节点未配置源码映射"。
背景行有 source ≠ 功能节点有 source — 两个概念别混。

**调试顺序铁律**: 用户报"右键打不开源代码"时
1. **先查 flow JSON 里节点 params.source 是否配全** (最可能的根因):
   ```python
   import json
   d = json.load(open("flows/xxx.json", encoding="utf-8"))
   with_src = [n["name"] for n in d["nodes"] if n.get("params", {}).get("source")]
   print(f"{len(with_src)}/{len(d['nodes'])} 节点带 source:", with_src)
   ```
   对照节点数, 功能节点缺失 = 补映射, 不用碰打开链路代码。
2. **再查打开链路** (open_node_source 环境/路径问题)。

本会话第一轮只修了打开方式(加弹窗), 用户再测仍打不开, 才查出是节点没映射 —
白绕一圈。先查数据再查代码。

## state_space 六层源码映射 (2026-08-18 定稿)

源文件 `src/lerobot/policies/left_right/state_space/` 六层:
perception / parallel / dynamics / cognition / safety / execution

| 画布节点 (id) | source |
|---|---|
| 📡 传感器融合 (sssensor) | perception.py (感知前端) |
| 🧩 43D 统一状态向量 (ssobs) | perception.py (感知输出) |
| ⚡ 前馈加速器 (ssff) | parallel.py (并行层快路径) |
| 🔮 自适应状态估计器 (ssest) | parallel.py (并行层慢路径) |
| 📈 先验动力学预测器 (sspred) | dynamics.py (PriorDynamicsPredictor) |
| 🧪 创新检测与状态校正器 (ssinnov) | dynamics.py (卡尔曼校正) |
| 🧭 认知任务调度器 (sssched) | cognition.py |
| 🛡 安全执行边界 (sslimit) | safety.py (saturate 饱和限幅) |
| 🤖 机器人执行器 (ssact) | execution.py |
| 🌍 物理世界 (ssworld) | execution.py (执行闭环) |

批量补法 (勿逐节点手写):
```python
BASE = 'src/lerobot/policies/left_right/state_space'
MAP = {'sssensor': 'perception.py', 'ssobs': 'perception.py', 'ssff': 'parallel.py',
       'ssest': 'parallel.py', 'sspred': 'dynamics.py', 'ssinnov': 'dynamics.py',
       'sssched': 'cognition.py', 'sslimit': 'safety.py', 'ssact': 'execution.py',
       'ssworld': 'execution.py'}
for node in d['nodes']:
    if node['id'] in MAP:
        node['params']['source'] = BASE + '/' + MAP[node['id']]
json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
```
生成器/手写 JSON 一律用 SRC_MAP dict 按 id 批量补(含背景行), 这是既有模式
(dual_brain 的 SRC_MAP 同款)。

## open_node_source 双路径环境自适应 (2026-08-18)

新家容器(纯 Docker Desktop)无 /mnt/c + 无 explorer.exe + 无 WSL interop,
WSL 老链路(复制到 /mnt/c/zmax_src_view + explorer.exe 打开)必挂。

```python
if os.path.isdir("/mnt/c") and shutil.which("explorer.exe"):
    # WSL 老家: 老链路 (复制到 /mnt/c/zmax_src_view/<name> + explorer.exe 打开)
    # 复制目标必须 /mnt/c/... (C:\... 在 Linux 是相对路径 → 错位+残留)
    # 打开参数用 C:\zmax_src_view\<name> (反斜杠, explorer.exe)
else:
    # 容器: SourceViewDialog 弹窗 (node_logic_dialog.py)
    # 绝对路径 + 行号 + 📋复制路径按钮 + 只读源码(可选中复制)
```

新功能若要走 Windows 侧(explorer/浏览器/盘符路径), 先探测 /mnt/c 与 explorer.exe,
容器环境给容器内回落方案, 别假设 WSL 通道存在。探测: `ls -d /mnt/c` + `which explorer.exe`。

## 验证手法 (open_node_source 集成测试)

- 弹窗 exec_() 阻塞 → QTimer.singleShot(2000, check) 里遍历 app.topLevelWidgets()
  找 SourceViewDialog 断言标题/行数, 再 close() 放行。
- ⚠️ 无 source 节点会弹 _qmsg_info(模态阻塞) → 测试必须先挑有 source 的节点,
  或把 QMessageBox 也纳入检查(否则脚本卡死到 timeout)。
- **load_flow_file 会把节点 id 重映射为 n<ts><suffix> 随机串** → 按 name 或
  params 键定位节点(如 '传感器融合' in name), 别按 json id。
- 改 flow json 后用户画布不更新 = 需重新点按钮加载(load_flow_file 每次重读),
  不必重启 GUI; 但改代码(open_node_source/弹窗类)必须重启 GUI。
