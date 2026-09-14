# flow JSON 数字字段类型坑 + GUI venv 启动坑 (2026-09-08 v5.2 实锤)

## 1. flow JSON x/y/w/h 字符串 → GUI core dump (Aborted)

**症状**: 改/生成 flows/*.json 后重启 GUI，进程启动即崩 (`Aborted (core dumped)`)，
simulink_log 尾行:
```
File ".../simulink_module.py", line 2544, in boundingRect
    return QRectF(0, 0, self.w, self.h).adjusted(-12, -18, 12, 12)
TypeError: arguments did not match any overloaded call:
  QRectF(...): argument 4 has unexpected type 'str'
Fatal Python error: Aborted
```

**根因**: 用 Python 脚本重排/生成 flow 时把坐标写成字符串 (`"w": "280"`, `"h": "110"`,
f-string/引号误用)。SimNodeItem.boundingRect 直接用 `self.w/self.h` 构造 QRectF，
PyQt5 严格类型 → str 直接 TypeError → Qt Fatal Abort。
⚠️ 历史 flow 的 x/y 是字符串也能跑 (add_node 内部 int(x) 转换)，**w/h 字符串必崩**
(SimNodeItem 不转换直接用)。

**铁律**: 写/改 flow 的脚本结尾必须跑类型检查:
```python
d = json.load(open(FLOW))
bad = [n['id'] for n in d['nodes']
       if not isinstance(n.get('w'), int) or not isinstance(n.get('h'), int)]
assert not bad, f"w/h 非 int: {bad}"
```

**修复** (一键全转):
```python
for n in d['nodes']:
    for k in ('w', 'h', 'x', 'y'):
        if isinstance(n.get(k), str):
            try: n[k] = int(float(n[k]))
            except Exception: pass
```
统一 int 最稳 (x/y 字符串虽能跑但全转无害)。

**诊断线索**: GUI `Aborted (core dumped)` + studio_launch.log 见 QRectF TypeError。
崩溃发生在画布加载 (load_flow_file → SimNodeItem 构造) 时，不是启动早期。

## 2. GUI "No module named 'metaworld'" = venv 未生效 (2026-09-08 实锤)

**症状**: GUI 里点 ▶运行 (真实化) 报 `⚠️ 真实化运行失败: No module named 'metaworld'`；
但 CLI 同 venv `python -c "import metaworld"` 正常。用户反馈"本机没反映"。

**根因**: GUI 被以 `gui-venv311/bin/python studio.py` **相对路径 + cwd=tools/gui** 方式启动。
venv 的 python 是 symlink → 靠 argv[0]/pyvenv.cfg 定位 site-packages；argv[0]="studio.py"
(相对名) + cwd 不在 venv 根 → venv 定位失败 → 落回系统 python → 无 metaworld。
(常见于桌面守护/systemd 会话或历史脚本用 `cd tools/gui && python studio.py` 拉起)

**正解** (启动 GUI 必须完整路径 + 从仓库根):
```bash
cd /home/ubuntu/lerobot-smolvla-lew
export DISPLAY=:0
export XAUTHORITY=$(tr '\0' '\n' < /proc/$(pgrep -f 'gnome-shell' | head -1)/environ | grep '^XAUTHORITY' | cut -d= -f2-)
export VIRTUAL_ENV=/home/ubuntu/lerobot-smolvla-lew/gui-venv311
nohup /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python \
  /home/ubuntu/lerobot-smolvla-lew/tools/gui/studio.py > /tmp/studio_launch.log 2>&1 &
```
(即使 studio.py 内部 os.chdir 到 tools/gui，argv[0] 完整路径已让 venv 生效)

**诊断**: `tr '\0' ' ' < /proc/<pid>/cmdline` 看 argv[0] 是否相对路径；
`cat /proc/<pid>/maps | grep -c gui-venv311` 确认 site-packages 是否加载。
systemd/GNOME 会话自动拉起的守护若用坏方式，会反复拉坏实例 —— 修启动脚本本身。
