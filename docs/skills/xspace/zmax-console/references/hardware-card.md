# 首页硬件资源卡 + DDS 节点区（studio.py / Z-MAX Console）

> 2026-09-25 实测。老倪要求「APP 上要看到真实硬件数据（4060 + Mac）」「硬件参数必须用 DDS 传递」。
> 配套技能：`dds-multinode-telemetry`（DDS 协议层/打包/8 个坑）

## 0. 对象先对齐（白做两轮的教训）
```
用户说 "APP / ZMAX app" = **本技能管的 PyQt5 桌面程序**（studio.py → Z-MAX_Console.exe），
**不是** Web 控制台（8799）。他连续 4 次说"APP 上还是没有硬件数据"，
我先去改 Web 页 → 对象错位，白做两轮。
⇒ 本项目里"APP"默认指桌面 studio.py。要改先确认是不是它 —— **问版本号最快**。
```

## 1. 卡片落在哪
```
tools/gui/studio.py
  class HardwareCard(QFrame)        # 新类，放在 class HomeWidget 之前
  HomeWidget._build(): layout.addWidget(hero) 之后 layout.addWidget(HardwareCard())
  2 秒 QTimer 自刷 + QTimer.singleShot(200, self.refresh) 立即先刷一次
```
显示行（每行一个 QLabel，`setTextFormat(Qt.RichText)`）：
`GPU / CPU / 内存 / 磁盘 / 算力 / DDS两端 / DDS节点列表 / 远端数据 / 数据源`

## 2. ★ 远端优先（关键设计，否则"看不到"）
APP 很可能跑在**没有 GPU 的机器**上（用户自己的电脑）→ 本机 `nvidia-smi` 永远为空。
**必须主动拉"数据源机"的真实数据**，本机只作补充行：

```python
def _hw_sources(self):
    cands = []
    u = os.environ.get("ZMAX_HW_URL") or (open(os.path.expanduser("~/.zmax_hw_url")).read().strip()
                                          if os.path.isfile(os.path.expanduser("~/.zmax_hw_url")) else "")
    if u: cands.append((u, "配置"))
    cands.append(("http://127.0.0.1:8799/api/hardware", "本机"))
    for ip in ("10.163.146.78", "192.168.23.50"):          # 数据源机(4060)已知 LAN IP
        cands.append(("http://%s:8799/api/hardware" % ip, "局域网 %s" % ip))
    return cands
# 命中即缓存 self._src_cache；「🔄 刷新数据源」按钮清缓存重探
```
界面必须同时给出两个排障答案：
- **版本号**（标题栏/菜单栏/首页小字）
- **数据源行**（`数据源: http://... (本机)` vs `数据源: 未连通（候选: …）`）
→ 这两行就是"到底哪一步断了"的直接答案，用户一贴就能定位。

## 3. DDS 节点区
- 订阅 `zmax/hw_state` / `train_prog` / `heartbeat` → 按 node 名聚合
- 节点列表：`🟢/🔴 + 名字 + 角色 + 设备 + 后端(CUDA/MPS) + 训练进度 + 在线龄`
- 按钮「📡 启动本机 DDS 发布」→ 自包含（用打包进来的 dds 模块起线程发布，不依赖外部脚本/venv）
- 卡片要标注**传输方式**：`DDS 直连` / `DDS 桥` / `⚠️非DDS(HTTP兜底)` —— 别偷偷降级

## 4. 改 studio.py 加控件的 4 个坑（都踩过）
| # | 坑 | 症状 | 修 |
|---|---|---|---|
| 1 | 猜颜色常量名 | 写 `C_TEXT`/`C_SUB` → NameError（实际是 `C_WHITE`/`C_GRAY`） | 先 `grep -nE '^[A-Z_]+\s*=' tools/gui/studio.py` |
| 2 | 宿主只有局部 import | `shutil` 模块级没有 → 异常被 try/except 吞 → 那行永远"—" | 新代码自己 import |
| 3 | `import threading` 非模块级 | 新类用到 threading → APP 直接崩 | 补到模块级 import 区 |
| 4 | **`str.replace` 静默 no-op** | 锚点没匹配但仍打印"✅已补" → 文件没改 → 崩 | **改完回读文件确认**（grep/sed 打印实际内容），别信自己的成功提示 |

验收（缺一不可）：
```bash
python3 -c "import ast;ast.parse(open('tools/gui/studio.py').read())"        # 语法
QT_QPA_PLATFORM=offscreen gui-venv311/bin/python -c "..."                    # ★ 离屏构造 + 读 lb.text()
```
语法过 ≠ 能构造：常量名/局部 import 这类错**只在构造时才炸**。

## 5. 版本发布纪律
```
· exe 是**单文件打包** → 新功能必须换文件（覆盖即可，无需卸载）
· 一件事只发一次版本：连发 v5.15.1→.5 而用户仍"没看到" ⇒ 瓶颈在用户手里的版本/网络, 不在功能
· 先问"你 APP 里版本号显示多少 / 数据源那行显示什么" —— 比再发一版有用得多
· 版本号 3 处显示位 + 顶部 `# vX.Y.Z:` 变更块；**别批量替换到历史变更块**（会篡改历史）
· 打包体积变化可作"依赖已打进"的证据（本轮 +4MB = cyclonedds 打包成功）
```
