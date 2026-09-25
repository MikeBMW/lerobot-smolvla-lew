# 给桌面 APP 加 UI 面板 + 让用户真的看到（2026-09-25 实测教训）

## 0. 头号教训：**"APP" 有歧义 —— 先确认是哪个界面，再动手**

同一个人在同一天里说的「APP」可能指**两个完全不同的东西**：

| 说法 | 实际指的 | 存放 |
|---|---|---|
| 「APP」「在 APP 上显示」「APP 的训练控制界面」 | **桌面 APP**（PyQt5 `studio.py` / 已发布的 `Z-MAX_Console.exe`）| `tools/gui/studio.py` |
| 「Web 控制平台」「网页上看」 | **Web 控制台**（标准库 http.server 那个）| `tools/train_deploy_console.py` |

**实际踩坑**：用户连续 3 次要"4060 硬件参数显示在 APP 上"，我三次都做在 **Web 控制台**里
（还反复用 curl/Node 复现渲染、贴出"Web 上确实有"的证据），用户第 4 次说
「app 还是没有 4060 硬件参数」——因为**他打开的是桌面 APP**。

**规则**：
1. 用户说「APP」且项目里**同时**存在桌面 GUI 和 Web 界面 → **先花一句话确认**，或
   **两边都做**，别单方面认定。
2. 用户说"没有/看不到"时，**不要再重复证明"我这里有了"** —— 那意味着你看的对象不对。
   立刻换问法：*"您现在打开的是哪个界面？（截图/描述）"* 并同时检查自己是不是做错了对象。
3. 反复被追问同一件事 3 次以上 = 你的"完成"判据和用户的**观测面**不一致，**先对齐观测面**。

## 1. 仓库里改了 ≠ 用户能看到 —— 必须走版本发布

**桌面 APP 的用户装的是 exe/app 产物，不是源码。** 你在仓库里加完面板，用户装着的旧版本
**永远不会**出现它。

发布链路（实测可用）：
```bash
# ① 改代码 + 版本串升位（见 §3 的防篡改写法）
git commit
git -c http.sslVerify=false push
# ② 打 tag 触发 CI 构建（.github/workflows/build-win-exe.yml: Windows .exe + macOS .app）
git tag -a vX.Y.Z -m "..."
git -c http.sslVerify=false push origin vX.Y.Z
# ③ 等 CI → 查 Release 产物（.exe / -macOS.zip）→ 验下载链接 HTTP 200/206
```
**交付话术必带下载链接**（用户要的是"能装上的东西"）：
```
https://github.com/<owner>/<repo>/releases/download/vX.Y.Z/<asset>
```
CI 状态与产物查询走 **api.github.com 直连**：
`/repos/<o>/<r>/actions/workflows/build-win-exe.yml/runs?per_page=1`、
`/repos/<o>/<r>/releases/tags/vX.Y.Z`（看 `assets[].name/size`）。

> 发布时不要拿"仓库已提交/CI 成功"当交付 —— 用户要的是**装完能看到界面变了**。

## 2. 往 12k 行的 PyQt5 单文件里插面板：4 个必查项

`studio.py` 这类巨型单文件有**不成文的局部约定**，照常识写代码必踩：

| 必查 | 实测踩坑 | 正确做法 |
|---|---|---|
| **颜色常量是否真的存在** | 我按常识写了 `C_TEXT`/`C_SUB` → 文件里**只有** `C_WHITE`/`C_GRAY`（`C_TEXT` 零处）→ 运行时 NameError | 用之前 `grep -nE '^C_\w+\s*='` 列出**实际**存在的常量名，照抄 |
| **模块是否只在方法内局部导入** | `shutil` 在 `studio.py` **只在方法里 `import shutil`**，模块级没有 → 我的类里 `shutil.disk_usage` 抛 NameError，被 `try/except` 吞掉 → 该行永远显示"—" | 新增的类/方法**自己 import** 用到的模块（与该文件既有风格一致） |
| **插入点的 HTML/布局闭合** | 用 patch 替换模板字符串时，把 `</div>` 当锚点 → 前一张卡片**没闭合**，DOM 嵌套错乱 | patch 后**立刻回读**该段（`search_files` 定位卡片标题）确认开合配对 |
| **内嵌 JS 的语法** | Python 字符串里的 JS 有语法错 → 整块面板白屏（但 Python 语法检查通过） | 抽出 `<script>` 内容写临时文件 → **`node --check`** 验证 |

## 3. 版本串升位：**别全量替换版本号**（会篡改历史）

这些文件顶部常有一长串**按版本分块的变更历史注释**（`# v5.15.0: ...`）。
若直接 `replace("v5.15.0", "v5.15.1")`：

- 显示位（`Z-MAX v5.15.0` 标签、窗口标题）**要升**
- 历史变更块的 `# v5.15.0:` 标题**绝不能改名** → 会把"v5.15.0 做了什么"记成 v5.15.1

**正确写法**：用**显示位专属模式**做替换，并在插入新块前**断言历史块还在**。

```python
p = "tools/gui/studio.py"; c = open(p, encoding="utf-8").read()
n = c.count("Z-MAX v5.15.0")                  # 只匹配显示位, 不碰 "# v5.15.0:"
c = c.replace("Z-MAX v5.15.0", "Z-MAX v5.15.1")
anchor = "# v5.15.0:"
assert anchor in c, "历史变更块不见了 → 中止!"   # ★ 守卫: 被篡改就停, 别写盘
c = c.replace(anchor, "# v5.15.1: <新变更>\n" + anchor, 1)
open(p, "w", encoding="utf-8").write(c)
```
**写盘前先 `assert` 守卫** —— 守卫命中时文件**没有被修改**，是安全的失败。
（实测：全量替换会命中 5 处而非 3 处，正是靠这个 assert 拦下来的。）

## 4. 无显示环境怎么验证 GUI 面板真的能用（离屏法）

没有屏幕/看不到界面时，**不要**只做"语法检查通过"就宣称完成。
用 Qt 的 offscreen 平台**真构造控件 + 真跑一次刷新 + 读回 label 文本**：

```bash
cd <gui 目录>
QT_QPA_PLATFORM=offscreen <venv>/bin/python -c "
import sys, os, importlib.util
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
spec = importlib.util.spec_from_file_location('sm','studio.py')
m = importlib.util.module_from_spec(spec)
try: spec.loader.exec_module(m)
except SystemExit: pass
except Exception: pass
w = m.HardwareCard(); w.refresh()          # ← 真跑一次采集
for nm, lb in (('GPU', w.lb_gpu), ('CPU', w.lb_cpu), ('磁盘', w.lb_disk)):
    print(nm, lb.text())
"
```
判据：每个 label 的文本**是实测值**（含 `MHz` / `GB 可用` / `%`），而不是 `—` 或异常串。
**哪一段是"—"就说明那一段的采集代码抛异常了** —— 逐个补依赖直到全段有值。
（实测：磁盘段从"—"变回 `93.6/396.0 GB 可用` 就是 `import shutil` 修复生效的证据。）

## 5. 面板内的实时数据采集：无第三方依赖优先
桌面 APP 要**打包成 exe 发出去**，所以面板里**别引第三方库**（numpy/psutil 都可能没打进包）。
实测可用的零依赖源：
```
GPU   : nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,\
        power.draw,clocks.sm,clocks.max.sm --format=csv,noheader,nounits
CPU   : /proc/stat 两次采样求差值 + /proc/loadavg
内存  : /proc/meminfo (MemTotal / MemAvailable)
磁盘  : shutil.disk_usage("/")
```
**每个字段都要有值或明确"—"**：查询不支持的项（如笔记本 GPU 不报 `power.limit`）要**三级回退**
（`power.limit` → `power.default_limit` → `enforced.power.limit`），仍取不到就写明确说明文案，
**绝不返回 None 让界面出现空白/undefined**。
`QTimer` 定时刷新（实测 2 秒）+ `QTimer.singleShot(200, self.refresh)` 立即先刷一次（别让用户盯着"—"等 2 秒）。
