# 案例：老倪的「APP」到底是什么（2026-09-25）

## 症状
老倪连续 4 轮说：
- 「app还是没有4060 硬件参数」
- 「4060 和 mac的硬件资源也要在APP显示 用DDS传数据」
- 「app上，4060和mac的硬件数据没有」
- 「app要显示4060的显存占用」
- 「APp必须马上显示」

## 我错的 4 轮（每轮都改了代码 + 发了一个版本）
| 轮次 | 我以为是 | 我做了什么 | 结果 |
|---|---|---|---|
| 1 | Web 控制台（我做的 8799） | 加硬件面板 + `/hw` 页 | 用户还是"没有" |
| 2 | 桌面 exe（studio.py / PyInstaller） | 首页加 HardwareCard，发 v5.15.0→v5.15.1 | 用户还是"没有" |
| 3 | 桌面 exe 缺"DDS 节点" | 加节点区 + 一键启动，发 v5.15.2~v5.15.4 | 用户还是"没有" |
| 4 | APP 装在无 GPU 的机器上 | 加"远端拉取 4060"行 + 数据源自动发现，发 v5.15.5 | 用户还是"没有" |
| ✅ | **一个 HTML 页面** | 给页面加卡 + 给它读的 JSON 喂真值 | 线上验证通过 |

## 真相（定位四板斧找到的）
```
界面:  docs/web/robot-monitor.html   （标题 "Z-MAX 实时状态 | XMS5-R800"）
数据源: fetch('https://raw.githubusercontent.com/MikeBMW/lerobot-smolvla-lew/mac/docs/web/robot-status.json')
页脚:  "Z-MAX · 智蜂创元 · 小芳(Mac)采集 · xspace渲染 · 每30分钟全量更新"
字段:  卡片只有 6轴关节/话题状态/六维力/安全/RealSense/⚡系统(ROS2节点/内存/模型/相机)
       → **完全没有 GPU / 显存 / 硬件字段**  ← 用户要的正是这个
```

**一次性解释全部现象**：页面存在、数据通道存在、就是**缺字段**。
所以正确动作 = 给页面加卡 + 给那个 JSON 加 `hardware` 段，**不需要发任何新版本**。

## 生效链路（零安装，刷新即见）
```
① tools/hw_to_robot_status.py   读-改-写合并: 读 robot-status.json → 加 hardware/hardware_mac → 写回
   （保留采集方的 metadata / L0 / L1 / L2 四个顶层键，绝不整份覆盖）
② docs/web/robot-monitor.html   加两张卡: 🖥 4060 硬件·显存占用 / 🍎 Mac 备份端
③ 推 mac 分支（页面读的就是它）→ 用户点「🔄 立即刷新」即见
④ 挂 no_agent 定时任务（*/2 * * * *）跑 scripts 保持显存实时
```
线上实证（直接读页面数据源）：
```
顶层键: ['metadata','L0','L1','L2','hardware','hardware_mac']   ← 采集方数据完整保留
★显存占用: 340.0 / 8188.0 MB (4.2%)   利用率 3.0% · 45°C · 10.16W
```

## 推 mac 分支的正确姿势（那是小芳的数据分支，不能强推）
```bash
git fetch origin mac
git worktree add -f --detach /tmp/wt origin/mac
git show main:docs/web/robot-monitor.html > /tmp/wt/docs/web/robot-monitor.html
git show main:tools/{hw_to_robot_status,hardware_view}.py > /tmp/wt/tools/   # 跨分支文件不共享
# 在 /tmp/wt 里读-改-写 JSON → git add/commit → push origin HEAD:mac（天然 fast-forward）
git worktree remove -f /tmp/wt
```

## 本轮踩的坑（全部已修）
1. **`git stash -u` 吞掉自己的新脚本** —— 脚本中途失败不会 `pop`，新脚本"消失"；
   靠 `git stash list` 找回。**别用 stash 保护未提交的新脚本**。
2. **mac 分支上的 `gui-venv311/bin/python` 是对方 Mac 的 venv**（指向 `/Users/xxx/.venv/bin/python`）
   → 跨分支跑脚本改用**系统 python3**。
3. **`tools/hardware_view.py` 只存在于 main 分支** → 在 mac 分支跑采集脚本会
   `ModuleNotFoundError`；要么先 `git show main:...` 取过来，要么在 main 上算好再合并。
4. **自测节点污染生产数据 1.7 小时**：我发过 `MacTEST(自测)`，它一直留在 JSON 里
   → 用户打开就会看到编造的 "Apple M2 Pro"。修法 = 命名带 TEST + 入口过滤 + 120s 自动过期 + 清理残留。
5. **studio.py 的坑（桌面那条线，虽然最后不是用户要的）**：
   - `C_TEXT` / `C_SUB` **不存在** → 应为 `C_WHITE` / `C_GRAY`
   - `shutil` 只在方法内局部 import，模块级没有 → 卡内必须自己 `import shutil`
   - `import threading` 必须模块级（我插到了函数里 → APP 直接崩）
   - 版本升级脚本差点把**历史变更块** `# v5.15.0:` 也改名 → 必须用精确显示串匹配 + 写盘前校验锚点
6. **别把 `PID` 认成包装进程**：`timeout`/`sh -c` 包一层时，`nvidia-smi` 里的是**子进程**；
   证明"真在 GPU 上跑"要解析到真进程 pid。

## 可复用的判据
- 用户说"看不到 X"且你看不到他屏幕 → **先跑四板斧定位 artifact**，再写代码
- 用户连续 2 次说"还是没有" → **停止发版本**，转去定位
- 给不出数据（如对方机器没上报）→ **明说给不出 + 给出让对方执行的一条命令**，
  绝不显示编造值
- 交付话术：给**可点的链接** + **用户只需做的一步** + 一个**能二分定位的问句**
  （"有没有出现这张卡？"）
