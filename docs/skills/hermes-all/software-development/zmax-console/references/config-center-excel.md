# 配置中心 (VEH.6) — 全参数表 + Excel 导出 + 缩进吞代码 bug

## ⚠️⚠️ Python 方法缩进吞掉后续 __init__ 代码 (2026-08-09 抓到, 配置中心基础配置"消失"真根因)
症状: ConfigModule 实例化后 `findChildren(QGroupBox)` 为空 (9 个配置组一个都不显示), 但实例化不报错。
根因: 某方法 (如 `_on_style_changed`) 定义后, **后续原本属于 `__init__` 的代码块缩进仍是 8 空格** (方法体级), 被 Python 静默吸入该方法体 → `__init__` 在 style_group 处提前结束, 后面 250+ 行基础配置/按钮/表格代码**永不执行** (方法内还引用 `bl`/`self` 之外的 __init__ 局部变量, 且 try/except 吞异常)。
排查链 (踩 5 轮):
1. offscreen `ConfigModule()` 后 `findChildren(QGroupBox)` 空 → 不是渲染问题, 是 build 代码没跑
2. 用类内相对行号扫描 `def ` 与 `# ==== 分组` 标记的位置 — **发现 "基础配置" 标记在 `_on_style_changed` 定义之后**
3. 看缩进: 类内 4 空格=类级, 8 空格=方法体。被吞的块是 8 空格 → 在方法体内
修复 (两种):
- **方法体内 except 后加 `return`** 截断方法 + 把后续块 dedent 4 空格回 __init__ 级 — 但块内缩进不一致 (4/8/9/12 混用) 时 dedent 易错 (曾把 4 空格变 0 → NameError: self)
- **最稳**: 用行号精确定位块边界 (类起始行 + `def` 行 + `_build_shell` 行), 整块提取 → 每行 +4 空格 (类级 4→方法体 8) → 插入到 `_on_style_changed` 定义之前 (即 __init__ 尾), 原位置删除。插错位置 (find 到别的 `]`) 会 SyntaxError — 插前 `ast.parse` 验证, 坏了 `git checkout --` 恢复重来
- 教训: **任何"控件组消失/空"先查是不是方法吞了后续代码** — grep `def ` 后紧跟的分组注释行, 看缩进是否 8 空格但本应属 __init__

## 📋 Lerobot 标准参数总表 (对标 VEH.2.17 配置通道)
- 老倪: 配置中心要像 VEH.2.17 一样分类分组的参数对比表, 列 ACT/SmolVLA/VLA-JEPA 三模型, "配置中心是最全的配置参数"
- 数据结构 `cfg_spec = [(分类, [(参数, {模型: 值}), ...]), ...]` 6 大类 (🏗架构/📷视觉/🎮动作/⚙️训练/📊数据/🚀部署), 每类 3-6 行
- 渲染: 复用 `_build_zoo_table` 模式 — QTableWidget `objectName="cfg_std_table"`, 隐藏表头, 类别行 setSpan 横跨全宽 + 青色底, 参数行浅灰, 值行居中对齐; 32 行 × 4 列 (标准参数|ACT|SmolVLA|VLA-JEPA)
- **必须存 `self.cfg_std_table = zoo_t`** (导出 Excel 用) — 别只 local 变量

## 📊 导出 Excel (2026-08-09 老倪: "配置中心, 可以导出EXCEL形式的配置表")
- 按钮 "📊 导出 Excel" (蓝色 #1f6feb) → `_export_excel`:
  ```python
  header = [t.item(0,c).text() if t.item(0,c) else "" for c in range(t.columnCount())]
  rows = [[t.item(r,c).text() if t.item(r,c) else "" for c in range(t.columnCount())] for r in range(1, t.rowCount())]
  df = pd.DataFrame(rows, columns=header)
  df.to_excel(out, index=False, sheet_name="Lerobot标准参数")
  # out = reports/config_center_<ts>.xlsx
  ```
- 依赖: 系统 python (控制台运行时) 装 pandas+openpyxl: **PEP 668 需 `pip install --break-system-packages pandas openpyxl`** (实测 pandas 3.0.5 兼容)
- 实测: 31 行数据导出 6.6KB xlsx, openpyxl 可读
