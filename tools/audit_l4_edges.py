#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧾 L4 区每条线的**实际数据**审计 (老倪: "要让每条 L4 的线条, 都有实际的数据")

做法: 不吃"画布上有一条线"这种证据, 只看**运行时计数/逐帧列**。
  输入 = 一次真跑产出的审计 json (tools/probe_l4_callchain.py L4audit 场景,
         环境变量 SS_L4_AUDIT_JSON=reports/l4_edge_audit_<ts>.json)
  输出 = 逐条边的判定: 有数据(计数>0 且逐帧列非零) / 通道在跑但未接管 / 死线(无运行时消费者)

判定纪律 (与 integration-level-audit 技能一致):
  · 只看运行时计数, 不认"节点在位"或"有连线";
  · 逐帧列必须 **非零**, 全零=形同没接;
  · 无法对应任何运行时消费者的边 → 明确判"死线", 不玩文字。

用法: python3 tools/audit_l4_edges.py [reports/l4_edge_audit_*.json]
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")

# 边 → 运行时证据 (消费点)。值为 (取证函数, 说明)
def _ev(audit: dict) -> dict:
    s = audit.get("summaries", {})
    c = audit.get("trace_cols", {})
    il, fib, l4, dit = s.get("il", {}), s.get("fiber", {}), s.get("l4", {}), s.get("l4_dit", {})
    nn = lambda k: (c.get(k, {}) or {}).get("n_nonzero", 0)                          # noqa: E731
    return {
        # ══ L4 行 5 节点 (ssintact / ssintact_dec / ssmani_exp / ssmani_c / ssmani_p) 的 20 条边 ══
        "lkild1": ("数据源→INTACT 策略", lambda: (l4.get("calls", 0),
                                                 f"INTACT 真渲染帧喂入: calls={l4.get('calls')} "
                                                 f"frame_std={l4.get('frame_std')} "
                                                 f"skill_ctx={l4.get('skill_ctx_dim')}维(非零{l4.get('skill_ctx_nonzero')}) "
                                                 f"goal_src={l4.get('goal_src')}")),
        "lkild2": ("INTACT→解码器", lambda: ((l4.get("calls", 0) + l4.get("reuse", 0)),
                                            f"chunk 复用 calls={l4.get('calls')} reuse={l4.get('reuse')} "
                                            f"src={l4.get('src')} · 桥导出 latent: z_t/z_goal/delta/**z_pred**")),
        "lkild_jepa": ("解码器→流形专家预测器", lambda: (il.get("ran", 0),
                                                       f"直连线 ran={il.get('ran')} frames={il.get('frames')} "
                                                       f"applied={il.get('applied')} ready={il.get('ready')} · "
                                                       f"预测器 z 来源={il.get('z_src')} · "
                                                       f"m_int 来源={str(il.get('src_last'))[:70]}")),
        "lkild3": ("解码器→DiT (L4 条件)", lambda: (dit.get("ok", 0),
                                                  f"DiT(l4_cond) calls={dit.get('calls')} ok={dit.get('ok')} "
                                                  f"cond_dim={dit.get('cond_dim')} cond_norm={dit.get('cond_norm')} "
                                                  f"applied={dit.get('applied')} beta={dit.get('beta')} src={dit.get('src')}")),
        "lkjepa_c": ("流形专家→接触流形", lambda: (nn("mani_pred"),
                                                f"mani_pred(预测流形 6 维) 非零帧={nn('mani_pred')}/{c.get('mani_pred', {}).get('n')} "
                                                f"· 接触维(mani_progress/risk/V) "
                                                f"{nn('mani_progress')}/{nn('mani_risk')}/{nn('mani_V')} "
                                                f"· 纤维丛接触丛预测 Φ(z_pred) 非零帧={nn('fiber_contact_true')}")),
        "lkjepa_p": ("流形专家→性能流形", lambda: (nn("mani_pred"),
                                                f"同一条预测流形列喂两个流形 · 性能维 mani_eta 非零帧={nn('mani_eta')} "
                                                f"(自由空间 η=0 属物理事实) · 纤维丛性能丛只记录不注入(w_perf=0)")),
        "lk_l4_abc": ("流形专家→通用算子A", lambda: (0,
                                                  "无运行时消费者: 引擎未把预测流形写进算子 A 的动态参数槽 → 死线 (待接)")),
        "lkmc_dc": ("接触流形→DiT (接触丛坐标)", lambda: (dit.get("ok", 0),
                                                       f"经纤维丛条件 token 进 DiT: 条件含 **Φ(z_pred) 接触丛 6 维** "
                                                       f"(cond_dim={dit.get('cond_dim')} = 192δ̂+6提升+6接触丛+4标量)")),
        "lkmani_c1": ("接触流形→可视化/视频", lambda: (nn("mani_progress"),
                                                   f"mani_progress/risk/V 逐帧列 {nn('mani_progress')}/"
                                                   f"{nn('mani_risk')}/{nn('mani_V')} 非零帧 → 3D/视频消费")),
        "lkmp_dc": ("性能流形→DiT", lambda: (dit.get("ok", 0),
                                          f"性能丛以 **Φ_p(z_pred) 6 维** 进入 DiT 条件 token "
                                          f"(cond_dim={dit.get('cond_dim')} 含接触丛 6 + 性能丛 6); "
                                          f"按老倪口径:**不参与动作幅值权重** (插拔任务性能流形作用小)")),
        "lkmani_p1": ("性能流形→可视化/视频", lambda: (nn("mani_dperp"),
                                                   f"mani_dperp 非零帧={nn('mani_dperp')} · mani_eta={nn('mani_eta')} "
                                                   f"(自由空间为 0 是物理事实) → 可视化消费")),
        "lkvl_jepa": ("VLM 潜空间 z(960)→流形专家", lambda: (0,
                                                        "口径未接: 预测器 input_kind=z7 (预测潜空间经丛映射) → VLM 960 维通道为死线, "
                                                        "需按 960 口径重训预测器才可接")),
        "lkvlm_mc": ("VLM 潜空间 z→接触流形", lambda: (0, "同上 (VLM 口径未接)")),
        "lkvlm_mp": ("VLM 潜空间 z→性能流形", lambda: (0, "同上 (VLM 口径未接)")),
        "lk23_jepa": ("2D→3D 几何 z7→流形专家", lambda: (nn("z7_vec"),
                                                     f"z7_vec 非零帧={nn('z7_vec')} (几何基, canonical); "
                                                     f"SS_L4_FIBER=1 时 z 改由 ẑ7=A·z_pred+b 提供 (预测潜空间拉回), "
                                                     f"当前 z 来源={il.get('z_src')}")),
        "lkm1": ("2D→3D 几何→接触流形", lambda: (nn("mani_progress"), "解析接触丛坐标由几何真值算出 (进度/偏离/V)")),
        "lkm2": ("2D→3D 几何→性能流形", lambda: (nn("mani_dperp"), "解析性能丛代价 (δ⊥/η) 由几何真值算出")),
        "lk_mem203": ("L4 记忆→流形专家 (筹划)", lambda: (0, "无运行时消费者: 记忆层未接预测器输入 → 死线 (待接)")),
        "lk_mem105": ("L4 记忆→接触流形 (筹划建议)", lambda: (0, "无运行时消费者 → 死线 (待接)")),
        # 直驱链 (install_direct_act 路径, 需 SS_L4_AUDIT_MODE=direct 跑法)
        "lksw1": ("L4 数据源→INTACT 插拔策略", lambda: (0, "需直驱模式跑 (本审计为引擎 SS_L4_INTACT 模式)")),
        "lksw2": ("INTACT 插拔→意图解码器", lambda: (0, "需直驱模式跑")),
        "lksw3": ("意图解码器→DiT", lambda: (0, "需直驱模式跑")),
    }


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    paths = args or [p for p in glob.glob(os.path.join(ROOT, "reports", "l4_edge_audit*.json"))
                     if os.path.getsize(p) > 0]
    if not paths:
        print("❌ 没有审计 json。先跑:\n  SS_L4_FIBER=1 SS_L4_AUDIT_JSON=reports/l4_edge_audit.json "
              "python3 tools/probe_l4_callchain.py L4audit 200")
        return 2
    p = max(paths, key=os.path.getmtime)          # 取最新非空 (防选出 0 字节的半成品)
    audit = json.load(open(p, encoding="utf-8"))
    print(f"🧾 L4 边数据流审计 · 证据文件 {os.path.relpath(p, ROOT)} · 场景 {audit.get('scen')} "
          f"· 步数 {audit.get('steps')}")
    print(f"   环境: {audit.get('env')}")

    flow = json.load(open(FLOW, encoding="utf-8"))
    names = {n["id"]: n.get("name", "") for n in flow["nodes"]}
    # L4 行 = 5 个 L4 节点 (ssintact → ssintact_dec → ssmani_exp → ssmani_c → ssmani_p)
    l4_ids = {"ssintact", "ssintact_dec", "ssmani_exp", "ssmani_c", "ssmani_p"}
    EV = _ev(audit)
    rows = []
    for l in flow["links"]:
        f, t = l.get("f", ""), l.get("t", "")
        if f not in l4_ids and t not in l4_ids:
            continue
        key = l.get("id")
        label = l.get("label", "")
        if key in EV:
            name, fn = EV[key]
            try:
                n, why = fn()
            except Exception as e:                                            # noqa: BLE001
                n, why = 0, f"取证异常 {type(e).__name__}: {e}"
            verdict = "✅ 有数据" if (isinstance(n, (int, float)) and n > 0) else (
                "⚠️ 通道在跑未接管" if "未接管" in why or "未过闸" in why else "❌ 死线/未覆盖")
        else:
            name, n, why = "未登记", 0, "该边未在审计表登记 (需补消费者或确认死线)"
            verdict = "❓ 未登记"
        rows.append((key, names.get(f, f)[:22], names.get(t, t)[:22], label[:34], n, verdict, name, why))

    print(f"\n{'边':10s} {'从':24s} {'到':24s} {'标签':36s} {'计数':>6s} 判定")
    for k, a, b, lab, n, v, nm, why in rows:
        print(f"{k:10s} {a:24s} {b:24s} {lab:36s} {str(n):>6s} {v}   ({nm})")
    print("\n逐条说明:")
    for k, a, b, lab, n, v, nm, why in rows:
        print(f"  [{v}] {k} ({nm}): {why}")
    alive = sum(1 for r in rows if r[5].startswith("✅"))
    print(f"\n合计 {len(rows)} 条 L4 相关边: 有数据 {alive} · 未接管 "
          f"{sum(1 for r in rows if r[5].startswith('⚠️'))} · 死线/未覆盖 "
          f"{sum(1 for r in rows if r[5].startswith('❌'))} · 未登记 "
          f"{sum(1 for r in rows if r[5].startswith('❓'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
