# 2026-08-08 坐标叠加节点注册 4 处清单 / Windows exe data 守卫 / 飞书端对账

## 🧩 新节点注册完整清单 (飞书端只加布局 → 3 处漏 → 崩溃+不可见)
老倪: "飞书端说画了坐标叠加功能块, 但本地没看到" — 对账发现飞书端改了本地文件但**不完整且未提交+GUI 未重启**。

**simulink 新节点 = 4 处注册, 缺一不可**:
1. **模板定义** (REFERENCE_APPS 的 node_specs): `("coord_overlay", "🧩 坐标叠加", {params})` — 布局行引用了但定义缺失 → 模板加载时该节点跳过
2. **icon 字典** (add_node 里): `"coord_overlay": "🧩"` — 漏了 → `KeyError: 'coord_overlay'` 模板加载直接崩 (本会话实测)
3. **node_logic 注册**: `_reg("coord_overlay", ["坐标叠加", "CoordOverlay"], "...", node_coord_overlay)` — 双击执行逻辑
4. **LIBRARY 条目**: 模块库可拖 (`{"name": "🧩 坐标叠加", "params": {...}}`)
另外 39 行 NODE_TYPES/类型表 (`"coord_overlay": {"cn": "坐标叠加", "color": "#58a6ff"}`) 也要在。

**同名节点多实例机制**: 模板布局同一行名出现 N 次 (如 5 模型行各一 🧩) → node_specs 里写 **N 个同名定义元组** → 加载循环 (node_specs 逐个, 布局 pos 按名分配+used 去重) 每个定义占一个布局位 = N 实例。一个定义 = 只占第一个位置, 其余行空着。
验证: `[n for n in m.nodes if n["name"]=="🧩 坐标叠加"]` 长度 == 5。

## 🪟 Windows exe (PyInstaller onefile) cwd=AppData — 数据探测坑
- 老倪反馈: v1.7.1 启动即崩 `FileNotFoundError: [WinError 3] 'C:\Users\Admin\AppData\Local\data'`
- 根因: onefile exe 的 cwd = %LOCALAPPDATA% (非 exe 目录) — 裸相对路径/裸 `os.listdir(root/data)` 炸
- **修法**: 任何文件系统探测先 `os.path.isdir` 守卫 (不存在 → 跳过/空列表, 不 listdir)
  ```python
  _data_root = os.path.join(root, "data")
  if os.path.isdir(_data_root):
      for _d in sorted(os.listdir(_data_root)): ...
  ```
- 模拟验证: `inst._repo_root = lambda: "/tmp/nonexistent"` → `_local_datasets()` 返回空列表不抛异常
- 修复后立刻 tag v1.7.2 重建 (Windows 报错 → 修 → 新 tag → 发飞书链接, 老倪直接用新 exe)

## 🔄 飞书端/其他会话改本地文件 — 对账流程 (老倪: "你没看到" 排查)
1. `git status --short` (未提交改动 = 飞书端/其他会话直接改的)
2. `grep` 目标功能名 (代码里有没有) + `git log --oneline -3` (提交有没有)
3. 有代码但用户看不到 → **GUI 没重启** (改文件必须重启 GUI 才生效)
4. 补全缺失注册 (见上 4 处) → fresh 验证 → **提交推送** (含对方改动, 别丢) → 重启 GUI → 汇报
5. 教训: 共享环境 (CLI/飞书端同机) 改 GUI 文件后**必须 commit + 重启** 才算"画入控制台"

## ✅ fresh 验证断言修正模式 (本会话 3 次误报)
- 断言用字面 `"_mx 步"` 但代码是 f-string `"{_mx} 步"` → 断言写 `f"..." in src` 或匹配花括号
- `_modules_grid` 返回 container (QWidget) 不是 grid → `container.layout()` 再 `itemAtPosition`
- ModuleCard 无 title/sys_label 属性 → `card.mid` + `card.findChildren(QLabel)` 找文本
- `cls.__new__(cls)` 免构造会缺信号 (module_clicked) → 用真实构造或 `__new__` + monkeypatch
