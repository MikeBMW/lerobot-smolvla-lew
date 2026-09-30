#!/usr/bin/env python3
"""🧪 ss_feature_tests.py — 状态空间系统验证 CLI (薄封装, 真源 verification_layer.py)

三级树 (规范场三层 → 节点 → 功能 → 用例, v4.0.1): node_func_tree.py 550 用例
  22 节点 × 5 功能 × 5 用例; auto 339 全真实断言 (引擎/六层/源码审计)

用法 (gui-venv311):
  gui-venv311/bin/python tools/ss_feature_tests.py --list               # 三级清单
  gui-venv311/bin/python tools/ss_feature_tests.py --only-node sssched  # 单节点自动用例
  gui-venv311/bin/python tools/ss_feature_tests.py --only F-A01         # 旧兼容单用例
  gui-venv311/bin/python tools/ss_feature_tests.py                      # 三级树 auto 全量
  gui-venv311/bin/python tools/ss_feature_tests.py --skip-slow
  echo $?   # 0=全过 1=有 FAIL

YOLO 感知用例需要 DISPLAY (metaworld 渲染); 无显示环境自动报 FAIL 提示。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_P = os.path.join(ROOT, "src", "lerobot", "verification", "verification_layer.py")
_spec = importlib.util.spec_from_file_location("lerobot.verification.verification_layer", _P)
_vl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vl)


def _load_nft():
    _tp = os.path.join(ROOT, "src", "lerobot", "verification", "node_func_tree.py")
    _ts = importlib.util.spec_from_file_location("lerobot.verification.node_func_tree", _tp)
    _nft = importlib.util.module_from_spec(_ts)
    _ts.loader.exec_module(_nft)
    return _nft


def _list_tree():
    """打印三级树 (规范场层分组 + 每功能 5 用例)"""
    _nft = _load_nft()
    for gid, zh, en, desc, nks in _nft.GAUGE_LAYERS:
        print(f"\n════ {gid} {zh} ({en}) ════\n  {desc}")
        for nk in nks:
            node = _nft.NODE_TREE.get(nk)
            if not node:
                continue
            print(f"\n▸ {node['name']}  ({nk}) · {node['fb']}")
            for f in node["funcs"]:
                kinds = [t[1] for t in f["tests"]]
                print(f"  ▪ {f['name']} ({f['fid']}) — {f['desc']} "
                      f"[auto {kinds.count('auto')}/semi {kinds.count('semi')}/手动 {kinds.count('manual')}]")
                for ti, (td, kind, ref, step) in enumerate(f["tests"]):
                    print(f"      {ti+1}. [{kind}] {td}" + (f"  ← {ref}" if ref else ""))
    print(f"\n合计: {_nft.node_count()} 节点 / {_nft.func_count()} 功能 / {_nft.test_count()} 用例")


def _list_product():
    """打印产品作业分级 (L1基础/L2高级/L3扩展 + 泛化指标 + 模型选型)"""
    _nft = _load_nft()
    for lv in _nft.PRODUCT_TREE:
        print(f"\n════ {lv['level']} {lv['lvl_name']} · {lv['kind']} ════")
        print(f"  {lv['desc']}  [{lv['gauge']}]")
        for j in lv["jobs"]:
            print(f"\n▸ {j['job']}  {j['status']}")
            print(f"    {j['desc']}")
            print(f"    检测: {j.get('detect', '')}")
            print(f"    泛化: {j.get('gen', '')}")
            print(f"    选型: {j.get('model_route', '')}")
            print(f"    引用: {', '.join(j['funcs'])}")
    refs, missing = _nft.product_funcs_ref()
    print(f"\n合计: {len(_nft.PRODUCT_TREE)} 级 / "
          f"{sum(len(lv['jobs']) for lv in _nft.PRODUCT_TREE)} 作业 / "
          f"引用功能 {len(refs)} (缺失 {len(missing)})")
    print("泛化指标定义: G_data 数据外推(新批次成功率保持) · G_pose 位姿外推(±Δ偏移衰减) · "
          "G_skill 技能复用(组合链换场景免重训)")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="🧪 状态空间验证层 CLI")
    ap.add_argument("--list", action="store_true", help="三级树清单")
    ap.add_argument("--product", action="store_true", help="产品作业分级清单 (L1/L2/L3+泛化+选型)")
    ap.add_argument("--only", default=None, help="旧兼容单用例 (如 F-A01)")
    ap.add_argument("--only-node", default=None, help="单节点自动用例 (如 sssched)")
    ap.add_argument("--skip-slow", action="store_true",
                    help="跳过 semi 半自动用例 (需真机/DISPLAY)")
    a = ap.parse_args()
    v = _vl.VerificationLayer()
    if a.product:
        _list_product()
        sys.exit(0)
    if a.list:
        _list_tree()
        sys.exit(0)
    if a.only:
        sys.exit(0 if v.run(a.only)[0] else 1)
    # auto 全跑; semi (需真机/DISPLAY) 默认跳过 — CLI 无头环境必跳, GUI 后台同策略
    if a.only_node:
        ok, _res = v.run_tree(skip_slow=True, only_node=a.only_node,
                              log_fn=lambda *x: print(*x))
        sys.exit(0 if ok else 1)
    ok, _res = v.run_tree(skip_slow=True, log_fn=lambda *x: print(*x))
    if not ok:
        for _k, _x in _res.items():
            if _x and _x[0] is False:
                print(f"FAIL {_k}: {str(_x[1])[:120]}")
    sys.exit(0 if ok else 1)
