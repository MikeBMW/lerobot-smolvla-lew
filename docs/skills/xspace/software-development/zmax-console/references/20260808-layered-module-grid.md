# 2026-08-08 首页分组框分层 UI + 产品主页卡 + System 1 命名

老倪对首页功能模块卡的 UI 分层要求（最终形态），改 studio.py `_modules_grid()`。

## 分层分组框设计（老倪 UI 偏好 — 明确要求）

- 每层（3 张卡）一个 **QFrame 分组框**：圆角边框 + hover 边框高亮
- 层背景 **深色 C_BG**，卡背景 **C_CARD 浅色** → 深框浅卡对比清晰
  （老倪："系统和数据集管理背景一样，感觉像是一个东西"——必须区分）
- 标题行 = `▍` 色条 + 组名（12px 粗体）+ 副标题（9px 灰），全部用该层专属色
- **每层专属色**：系统 `#58a6ff` 蓝 / 架构 `#00d4aa` 青 / 数据 `#a371f7` 紫 / 场景 `#e3b341` 金
- 分组标题：系统 / 架构 / 数据 / 场景；副标题：平台底座·数据/训练/硬件、系统结构·架构/仿真/配置、数据资产·空间/监控/评估、应用场景·插拔/版本/官网

代码骨架（_modules_grid 后半段）：
```python
_GROUP_TITLES = ["系统", "架构", "数据", "场景"]
_GROUP_SUBS = [...]
_GROUP_COLORS = ["#58a6ff", "#00d4aa", "#a371f7", "#e3b341"]
outer = QVBoxLayout(); outer.setSpacing(10)
for gi, (gtitle, gsub) in enumerate(zip(_GROUP_TITLES, _GROUP_SUBS)):
    gcol = _GROUP_COLORS[gi]
    frame = QFrame()
    frame.setStyleSheet(f"QFrame {{ background:{C_BG}; border:1px solid {gcol}55; border-radius:10px; }}"
                        f"QFrame:hover {{ border-color:{gcol}; }}")
    # 标题行: 色条 ▍ + 组名(12pt bold, gcol) + 副标题(灰9px) + stretch
    # 3 张卡: modules[gi*3 + c] → ModuleCard, 横排 QHBoxLayout
    outer.addWidget(frame)
container = QWidget(); container.setLayout(outer)
```

## 模块顺序（老倪指定 — modules 数组 = 3 列网格顺序）

第一行: dataset 数据集管理 / training 训练控制台 / hardware 硬件工具箱
第二行: architecture 系统架构 / simulink Simulink模式 / config 配置中心
第三行: dataspace 全局数据空间 / monitor 实时监控 / evaluation 评估分析
第四行: plugging 插拔场景 / version 版本同步 / **website 产品主页**(最后新增)

## 产品主页卡（打开外部 URL）

- modules 数组加 `("website", "🌍", "产品主页", "datadrive.world", "产品官网 · 技术展示\nhttps://datadrive.world", "#1f6feb")`
- `_on_nav` 加特殊分支（在 check_updates 旁）：
```python
if target == "website":
    from PyQt5.QtCore import QUrl
    from PyQt5.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl("https://datadrive.world/"))
    return
```

## System 1 badge（三层命名统一）

- 训练控制台卡 syslbl 从 `"Sys-11 · 动作系统"` → `"System 1 · 动作系统"`
- ModuleCard 右上角 badge = `syslbl.split("·")[0].strip()`（即 "System 1"）——改 syslbl 即改 badge
- 三层系统命名：System 2(顶 云端训练) / System 1(中 含 SYS11 VLA-T + SYS12 Z-Flow) / System 0(底 红底)

## 验证模式

- 静态: `ast.parse(studio.py)` + 断言模块数组 mid 顺序（re.findall `\("(\w+)",` on modules 段）
- 运行时: 找含 `_modules_grid` 的 Home 类 → `cls()` → `_modules_grid()` 返回 **container(QWidget)**，
  用 `container.layout()` 拿 QVBoxLayout；分组框 = `outer.itemAt(i).widget()`(QFrame)，
  标题 = `frame.layout().itemAt(0).layout().itemAt(1).widget()`(QLabel)，卡 = `itemAt(1).layout()`
- badge 验证: `card.findChildren(QLabel)` 找含 "System" 文本的（ModuleCard 无 sys_label 属性，badge 是 QLabel）
