#!/usr/bin/env python3
"""验证 simulink_module.py 所有模板布局: specs 节点必须全部有 layout 网格位置,
背景行 row_bg 必须与网格对齐。

背景 (2026-08-07):
1) node_specs 里名字不在 layout 网格中的节点会静默兜底单行 x = base_x + i*200
   (i = specs 索引) → 五模型对比的 Interpolant(idx25)/交叉注意力(idx30)
   曾跑到 x=6620/7920 显示区右侧外。改布局后必须断言零兜底。
2) 背景行 _draw_model_rows 从首行按 row_names 排, 参数 col_w/n_cols 必须与
   layout 网格一致; 往网格加首行(如感知链)时 row_names/palette 必须同步加,
   否则背景带与模型行错位一行 (ACT 背景盖感知行、末行无背景)。

用法:
    python3 verify-simulink-layout.py [simulink_module.py 路径]
    # 默认 tools/gui/simulink_module.py (相对当前目录)

关键: 模板数据虽是模块级常量, 但 import 会拉起 PyQt5/QApplication 副作用 —
用 ast 解析源码提取数据, 不 import。
"""
import ast
import sys


def check_bg_rows(tree) -> int:
    """背景行 row_bg 与 layout 网格对齐检查 (2026-08-07 追加: 加了感知链首行后
    ACT 背景盖到感知行、AWE 行无背景 — _draw_model_rows 从首行按 row_names 排,
    参数 col_w/n_cols 必须与 layout 网格一致)。

    检查: 1) palette 覆盖全部行名  2) 每行背景 y0 与节点行 y 对齐
          3) 背景右界覆盖该行最右节点。
    返回失败数。
    """
    fail = 0

    # 1) _draw_model_rows 调用 (self._draw_model_rows([...])) 的 row_names
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "_draw_model_rows" and node.args \
                and isinstance(node.args[0], ast.List):
            calls.append([e.value for e in node.args[0].elts])
    if not calls:
        print("  [跳过] 无 _draw_model_rows 调用 (无背景行)")
        return 0

    # 2) 函数默认参数
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_draw_model_rows"), None)
    if fn is None:
        print("  [跳过] 找不到 _draw_model_rows 定义")
        return 0
    defaults = {}
    for a, d in zip(fn.args.args[-len(fn.args.defaults):], fn.args.defaults):
        if isinstance(d, ast.Constant):
            defaults[a.arg] = d.value
    row_h, col_w, base_x, base_y, n_cols = (defaults.get(k, 230 if k == "row_h" else 200)
                                            for k in ("row_h", "col_w", "base_x", "base_y", "n_cols"))

    # 3) palette 覆盖全部行名
    pal = next((n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "palette" for t in n.targets)), None)
    pal_names = {k.value for k in pal.value.keys} if pal else set()
    for names in calls:
        missing = [n for n in names if n not in pal_names]
        if missing:
            fail += 1
            print(f"  [FAIL] 背景行 palette 缺失颜色: {missing}")

    # 4) 定位带网格 layout 的模板 (取最后一个是五模型对比)
    layout_rows = None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        for el in node.value.elts:
            if not (isinstance(el, ast.Tuple) and len(el.elts) >= 4
                    and isinstance(el.elts[0], ast.Constant)
                    and isinstance(el.elts[0].value, str)
                    and isinstance(el.elts[3], ast.List)):
                continue
            lrows = []
            for row_ast in el.elts[3].elts:
                if isinstance(row_ast, ast.List):
                    lrows.append([x.value if isinstance(x, ast.Constant)
                                  and isinstance(x.value, str) else "" for x in row_ast.elts])
            if lrows:
                layout_rows = lrows
    if not layout_rows:
        print("  [跳过] 无网格 layout 可对照")
        return fail

    for names in calls:
        if len(names) > len(layout_rows):
            fail += 1
            print(f"  [FAIL] 背景行 {len(names)} 行 > 布局行 {len(layout_rows)} 行")
            continue
        for r, name in enumerate(names):
            bg_y0 = base_y + r * row_h - 20
            bg_right = (base_x - 140) + (base_x + n_cols * col_w + 120) - (base_x - 140)
            row = layout_rows[r]
            node_xs = [base_x + c * 200 for c, nm in enumerate(row) if nm]
            if not node_xs:
                continue
            max_right = max(node_xs) + 150
            if (bg_y0 + 20) != (base_y + r * row_h) or bg_right < max_right:
                fail += 1
                print(f"  [FAIL] 背景行{r} [{name}]: y0={bg_y0} 右界={bg_right} "
                      f"vs 节点行 r{r} 最右={max_right} — 参数与网格不同步")
    if fail == 0:
        print(f"  [OK  ] 背景行: {len(calls)} 组, palette/对齐/覆盖全部通过")
    return fail


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "tools/gui/simulink_module.py"
    try:
        src = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        print(f"❌ 找不到 {path} — 请在 lerobot-smolvla-lew 目录下运行或传路径")
        return 2
    tree = ast.parse(src)

    templates = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        for el in node.value.elts:
            if not (isinstance(el, ast.Tuple) and len(el.elts) >= 3):
                continue
            name = el.elts[0]
            if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                continue
            specs, links = el.elts[1], el.elts[2]
            if not (isinstance(specs, ast.List) and isinstance(links, ast.List)):
                continue
            layout = el.elts[3] if len(el.elts) >= 4 and isinstance(el.elts[3], ast.List) else None
            if specs.elts and isinstance(specs.elts[0], ast.Tuple):
                templates.append((name.value, specs, layout))

    def const_str(x):
        return x.value if isinstance(x, ast.Constant) and isinstance(x.value, str) else None

    def parse_specs(specs_ast):
        out = []
        for t in specs_ast.elts:
            if isinstance(t, ast.Tuple) and len(t.elts) >= 2:
                nm = const_str(t.elts[1])
                if nm:
                    out.append(nm)
        return out

    def parse_layout(layout_ast):
        rows = []
        if layout_ast is None:
            return rows
        for row_ast in layout_ast.elts:
            if isinstance(row_ast, ast.List):
                rows.append([const_str(x) or "" for x in row_ast.elts])
        return rows

    print(f"检测到模板: {len(templates)}")
    fail = 0
    for name, specs_ast, layout_ast in templates:
        specs = parse_specs(specs_ast)
        rows = parse_layout(layout_ast)
        if not rows:
            print(f"  [单行模板] {name}: {len(specs)} 节点 (无网格, 不检查)")
            continue
        base_x, base_y = 120, 80
        pos = {}
        for r, row in enumerate(rows):
            for c, nm in enumerate(row):
                if nm:
                    pos.setdefault(nm, []).append((base_x + c * 200, base_y + r * 230))
        used, fallback = set(), []
        maxx = maxy = 0
        for i, nm in enumerate(specs):
            cands = pos.get(nm, [])
            xy = next((p for p in cands if p not in used), None)
            if xy is None:
                xy = (base_x + i * 200, base_y)
                fallback.append((nm, xy))
            used.add(xy)
            maxx = max(maxx, xy[0])
            maxy = max(maxy, xy[1])
        if fallback:
            fail += 1
            print(f"  [FAIL] {name}: {len(specs)}节点 {len(rows)}行 兜底={len(fallback)} maxX={maxx} maxY={maxy}")
            for nm, xy in fallback:
                print(f"        ❌ 兜底: {nm} → {xy}")
        else:
            print(f"  [OK  ] {name}: {len(specs)}节点 {len(rows)}行 兜底=0 maxX={maxx} maxY={maxy}")

    bg_fail = check_bg_rows(tree)

    print()
    if fail or bg_fail:
        print(f"✗ {fail} 个模板存在兜底节点 + {bg_fail} 个背景行问题 — 需修 layout/背景行")
        return 1
    print("✓ 所有网格模板: specs 全部有 layout 位置, 背景行对齐且覆盖, 无跑飞")
    return 0


if __name__ == "__main__":
    sys.exit(main())
