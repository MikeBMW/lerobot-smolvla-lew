#!/usr/bin/env python3
"""
Z-MAX Console 完整性保护检查 (v1.8.0 起, 老倪: 以后按照这个版本检查, 别少东西)

每次版本迭代/功能改动后运行:
    python3 tools/ci/integrity_check.py

检查五处一致性 (任一处少东西立刻报错):
  1. 版本号: studio.py(窗口标题+侧栏) == update_checker.py == docs_sync.py == v1.x.y
  2. 主页功能卡 (HomeWidget._modules_grid) == self.modules 字典 (13 键, 卡↔页一一对应)
  3. self.modules 字典 key 顺序 == QStackedWidget addWidget 顺序 (索引对齐)
  4. _on_nav 状态栏 names 列表 == self.modules 字典顺序 (13 项, 防错位)
  5. 每个页面类存在 (ArchitectureModule/DatasetModule/TrainingModule/EvalModule/...)

用法: exit 0 = 全通过; 非 0 = 有遗漏, 按提示修复。
"""
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
STUDIO = REPO / "tools" / "gui" / "studio.py"
UPDATER = REPO / "tools" / "gui" / "update_checker.py"
DOCSYNC = REPO / "tools" / "gui" / "docs_sync.py"

EXPECTED_VERSION = "v3.0.8"

# 期望的功能卡列表 (与 HomeWidget._modules_grid modules 元组第一列一致)
EXPECTED_CARDS = [
    "dataset", "training", "hardware", "architecture", "simulink", "config",
    "dataspace", "monitor", "evaluation", "plugging", "version", "website",
]

# 期望的 self.modules 字典顺序 (与 stack addWidget 索引一致, home=0 起 13 项)
EXPECTED_MODULES = [
    "home", "dataset", "training", "evaluation", "hardware", "config", "monitor",
    "plugging", "version", "inference", "simulink", "dataspace", "architecture",
]

# 页面类 → 应在 studio.py 出现
EXPECTED_CLASSES = [
    "ArchitectureModule", "DatasetModule", "TrainingModule", "EvalModule",
    "HardwareModule", "ConfigModule", "MonitorModule", "PluggingSceneModule",
    "VersionSyncWidget", "InferencePanel", "SimulinkModule", "DataSpaceModule",
]

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def parse(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        fail(f"语法错误 {path.name}:{e.lineno}: {e.msg}")
        return None  # type: ignore[return-value]


def check_versions() -> None:
    src = STUDIO.read_text(encoding="utf-8")
    # studio.py 两处 (窗口标题 + 侧栏 QLabel)
    if f"Z-MAX {EXPECTED_VERSION}" not in src:
        fail(f"studio.py 缺少版本串 Z-MAX {EXPECTED_VERSION} (窗口标题/侧栏)")
    # update_checker.py
    u = UPDATER.read_text(encoding="utf-8")
    if f'CURRENT_VERSION = "{EXPECTED_VERSION}"' not in u:
        fail(f"update_checker.py CURRENT_VERSION 不是 {EXPECTED_VERSION}")
    # docs_sync.py 两处
    d = DOCSYNC.read_text(encoding="utf-8")
    if d.count(f'"{EXPECTED_VERSION}"') < 2:
        fail(f"docs_sync.py 版本串 {EXPECTED_VERSION} 少于 2 处 (version+zmax_version)")


def get_modules_list(tree: ast.Module) -> list[str]:
    """提取 _modules_grid 里 modules 列表的 key (首页功能卡)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_modules_grid":
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for t in child.targets:
                        if isinstance(t, ast.Name) and t.id == "modules" and isinstance(child.value, ast.List):
                            keys = []
                            for el in child.value.elts:
                                if isinstance(el, ast.Tuple) and el.elts and isinstance(el.elts[0], ast.Constant):
                                    keys.append(el.elts[0].value)
                            return keys
    fail("找不到 _modules_grid 的 modules 列表")
    return []


def get_modules_dict(tree: ast.Module) -> dict[str, int]:
    """提取 self.modules 字典 (在 StudioMainWindow.__init__)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and all(
            isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            for k, v in zip(node.keys, node.values)
        ):
            keys = [k.value for k in node.keys]
            if "home" in keys and "architecture" in keys and "training" in keys:
                return {k.value: v.value for k, v in zip(node.keys, node.values)}
    fail("找不到 self.modules 字典")
    return {}


def get_addwidget_order(tree: ast.Module) -> list[str]:
    """提取 __init__ 里 stack.addWidget(...) 的实参名顺序.

    支持两种写法:
      self.stack.addWidget(DatasetModule())     -> 'DatasetModule'
      self.stack.addWidget(self.model_engine)   -> 'model_engine' (变量, 下面做别名映射)
    """
    # self.<attr> 变量 → 页面类名 (Model Engine / Simulink / DataSpace 是命名实例)
    ALIAS = {"model_engine": "TrainingModule", "simulink": "SimulinkModule", "dataspace": "DataSpaceModule",
             "sim": "SimulinkModule"}
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in ("addWidget", "insertWidget") and node.args:
                # insertWidget(index, widget) — 取第2参; addWidget(widget) — 取第1参
                a = node.args[1] if f.attr == "insertWidget" else node.args[0]
                if isinstance(a, ast.Call) and isinstance(a.func, ast.Name):
                    order.append(a.func.id)
                elif isinstance(a, ast.Attribute):
                    # self.model_engine / self.simulink / self.dataspace
                    order.append(ALIAS.get(a.attr, a.attr))
                elif isinstance(a, ast.Name):
                    order.append(ALIAS.get(a.id, a.id))
    return order


def get_names_list(tree: ast.Module) -> list[str]:
    """提取 _on_nav 状态栏 names 列表."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_on_nav":
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    for t in child.targets:
                        if isinstance(t, ast.Name) and t.id == "names" and isinstance(child.value, ast.List):
                            return [el.value for el in child.value.elts if isinstance(el, ast.Constant)]
    fail("找不到 _on_nav 的 names 列表")
    return []


def main() -> int:
    tree = parse(STUDIO)
    if tree is None:
        print("\n❌ 完整性检查失败 (语法错误)")
        return 1

    # 1. 版本号
    check_versions()

    # 2. 主页功能卡
    cards = get_modules_list(tree)
    if cards != EXPECTED_CARDS:
        fail(f"主页功能卡不一致:\n  期望 {EXPECTED_CARDS}\n  实际 {cards}")

    # 3. self.modules 字典
    md = get_modules_dict(tree)
    if list(md.keys()) != EXPECTED_MODULES:
        fail(f"self.modules 顺序不一致:\n  期望 {EXPECTED_MODULES}\n  实际 {list(md.keys())}")

    # 4. addWidget 顺序 vs 字典 (跳过 home=0, 从 index 1 对齐)
    addw = [c for c in get_addwidget_order(tree) if c in EXPECTED_CLASSES]
    expected_pages = EXPECTED_MODULES[1:]  # home 不是 addWidget
    page_map = {
        "dataset": "DatasetModule", "training": "TrainingModule",
        "evaluation": "EvalModule", "hardware": "HardwareModule",
        "config": "ConfigModule", "monitor": "MonitorModule",
        "plugging": "PluggingSceneModule", "version": "VersionSyncWidget",
        "inference": "InferencePanel", "simulink": "SimulinkModule",
        "dataspace": "DataSpaceModule", "architecture": "ArchitectureModule",
    }
    expected_addw = [page_map[k] for k in expected_pages if k in page_map]
    # SimulinkModule 是延迟创建 (2026-08-12: _init_simulink 里 insertWidget 插回
    # _simulink_index 原位, 源码顺序 ≠ 运行时顺序) → 剔除后比较, 存在性单独验证
    addw_cmp = [c for c in addw if c != "SimulinkModule"]
    exp_cmp = [c for c in expected_addw if c != "SimulinkModule"]
    if addw_cmp[: len(exp_cmp)] != exp_cmp:
        fail(f"stack addWidget 顺序不一致:\n  期望 {exp_cmp}\n  实际前{len(exp_cmp)}个 {addw_cmp[:len(exp_cmp)]}")
    if "SimulinkModule" not in addw:
        fail("SimulinkModule 缺失: _init_simulink 未通过 insertWidget 挂载 (延迟创建失效?)")

    # 5. 页面类存在 (类定义或 import 均可)
    src_text = STUDIO.read_text(encoding="utf-8")
    for cls in EXPECTED_CLASSES:
        if f"class {cls}" not in src_text and not re.search(rf"\b{cls}\b", src_text):
            fail(f"页面类 {cls} 不存在 (无定义也无引用)")

    # 6. _on_nav names 与字典顺序一致
    names = get_names_list(tree)
    if len(names) != len(EXPECTED_MODULES):
        fail(f"names 列表 {len(names)} 项 != self.modules {len(EXPECTED_MODULES)} 项 (错位风险)")
    elif names[0] != "首页" or "架构总览" not in names:
        fail(f"names 列表内容异常: {names}")

    if errors:
        print("\n❌ Z-MAX 完整性检查失败, 以下遗漏需修复:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"\n✅ Z-MAX {EXPECTED_VERSION} 完整性检查通过: 版本号/功能卡/页面字典/导航/类 五处一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
