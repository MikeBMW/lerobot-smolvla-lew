# GUI/画布运维坑 — 2026-09-08 (venv 启动 / flow JSON int / 画布平移 / 多实例)

## 1. GUI "No module named 'metaworld'" / "本机没反应" = venv 启动方式坏了
**症状**: GUI 日志 `⚠️ 真实化运行失败: No module named 'metaworld'`, 或用户说"你的本机怎么没反映"。
CLI 里 `gui-venv311/bin/python -c "import metaworld"` 却 OK。
**根因**: GUI 被以**相对路径**启动 — cmdline 是 `gui-venv311/bin/python studio.py` 且
cwd=`tools/gui`。venv python 靠 argv[0] 定位 pyvenv.cfg; argv[0] 是裸 `studio.py` 时
venv 定位失败 → 落系统 site-packages → 无 metaworld (metaworld 只装在 gui-venv311)。
**判别**: `cat /proc/<pid>/cmdline | tr '\0' ' '` 看 argv[0]; 或 `readlink /proc/<pid>/exe`
只看解释器看不出 venv 是否生效 — 必须看 cmdline 是否含 venv 完整路径。
**修复** (start_gui_fixed.sh 模式):
```bash
cd /home/ubuntu/lerobot-smolvla-lew          # 仓库根, 别 cd tools/gui
export VIRTUAL_ENV=/home/ubuntu/lerobot-smolvla-lew/gui-venv311
nohup /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python \
      /home/ubuntu/lerobot-smolvla-lew/tools/gui/studio.py > /tmp/studio_launch.log 2>&1 &
```
**铁律**: GUI 启动必须 (a) cwd=仓库根 (b) python 用 venv **完整绝对路径** (c) studio.py 用绝对路径。
重启后验证: 跑一次 ▶运行 无 No module = venv 生效。
**连带**: 老倪反复只发"静静"且说"没反映"时, 先查 GUI 进程 cmdline/cwd + simulink 日志尾部 —
大概率是坏启动/两实例叠窗, 不是消息没送达。

## 2. 手改 flows/*.json 新增节点 → w/h/x/y 必须是 int (字符串 = GUI Fatal Abort)
**症状**: 加载画布即崩, `/tmp/studio_launch.log` 尾部:
`simulink_module.py boundingRect → QRectF(0,0,self.w,self.h) TypeError: ... argument 4 has
unexpected type 'str'` → `Fatal Python error: Aborted`。
**根因**: python 脚本写 flow JSON 时把新节点/行背景的 w/h (有时 x/y) 写成字符串 `"110"`
(从模板/旧代码抄的字符串风格)。SimNodeItem.boundingRect 直接用 self.w/self.h → QRectF 要
float/int, 字符串 TypeError → Qt abort。**本会话踩了两次** (relayout 脚本两次都写字符串)。
**修复**: 写完 JSON 必跑类型检查:
```python
bad = [n['id'] for n in d['nodes']
       if not isinstance(n.get('w'), int) or not isinstance(n.get('h'), int)]
assert not bad, bad
# 全量转 int: for n in nodes: for k in ('w','h','x','y'): 若 str → int(float(v))
```
**铁律**: 任何生成/改写 flow JSON 的脚本, 落盘前把 w/h/x/y 全部 int() 化 + 断言复查;
连线引用也要校验 (f/t 都在 nodes id 集内)。旧 flow 里 row_bg 的 h 偶尔是 str 但 row_bg
不走 SimNodeItem.boundingRect, 普通节点是 str 必崩 — 别学旧文件的字符串风格。

## 3. 画布平移 = 鼠标中键拖动 (左键=选中/连线)
SimCanvas.mousePressEvent: **MiddleButton → _panning** (拖动画布), LeftButton → 点节点/
连线, RightButton → 菜单。用 xdotool 远程拖画布必须 `mousedown 2 → mousemove_relative →
mouseup 2`; 用左键拖 = 用户看到"拖的不是画布" (拖出选区/误连线)。慢速分步拖 (每步
~100px + sleep 0.1) Qt 才识别为拖动; 快速一次跳太多不触发。方向: 中键向左拖 = 内容向右
(看更右侧); 向上拖 = 看下方。

## 4. 多 GUI 实例叠窗 = 旧代码残留 + "状态空间怎么没了"
systemd/GNOME 会话可能自动拉起 GUI, 与手动重启的新实例并存。症状: 窗口标题同款两三个、
用户看到旧行为 (旧代码没改)、或画面被盖。
**处置**: `ps aux | grep '[s]tudio.py'` 列全部 pid+启动时间 → **kill -9 旧的留新的**
(restart 脚本的 pgrep -f 常漏杀, 因匹配串差异) → `DISPLAY=:0 wmctrl -l | grep XSpace`
确认只剩一个窗口 → `wmctrl -i -a <winid>` 置前。
**遮挡**: Chromium(千问)/Terminal 全屏盖画布 → 截图看起来"画面没动" → wmctrl -i -a 拉前;
xdotool windowactivate 在 Mutter 下报 XGetWindowProperty 失败时改用 wmctrl。

## 5. 验证回归测试与肌肉记忆隔离 (SS_MUSCLE=0)
`verification_layer._chain()` 跑 insert/full 链回归测决策层基线 (343 步) — 若肌肉记忆
默认开 (SS_MUSCLE=1) 且 data/muscle_memory.json 已固化标杆 → 快通道重放让插拔变慢
(412-469 步, 仍成功但超 380 上限 → t_chain_regress FAIL)。修: _chain 临时
`os.environ["SS_MUSCLE"]="0"` + try/finally 恢复。肌肉记忆单独由 muscle 断言组验。
教训: 回归/基线测试要隔离"进化性叠加功能", 不然环境状态不同步就误报 FAIL。
