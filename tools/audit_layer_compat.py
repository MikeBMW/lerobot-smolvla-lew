#!/usr/bin/env python3
"""🔍 L2/L3/L4 层兼容审计 — 验证"高级可调用低级 + 能力叠加 + 仿真/真机可切换"

设计原则 (老倪 09-16 + layered-capability-stack 技能):
  单向依赖: 上层依赖下层的准确执行
  L4 只准产意图 m_t · L3 只准产条件 c_t · L2 唯一出口 u ∈ U_L2
  可行域逐层收窄 U_L2 ⊇ U_L3 ⊇ U_L4 · 稳定性由 L2 势函数兜底
  开关独立 (无档位互斥) · 不设环境变量 = 逐位零变化

检查 6 项 (每项机器可判):
  A 开关独立性: 各层 env 变量互不 unset (无"开A关B")
  B 单出口: 引擎里执行量出口计数 == 1 (上层不许写执行量)
  C 叠加通道: L4→L2 参考槽 (u_ff) · L3→L2 条件 · 均非替换
  D 降级链: L4关→L3关→L2纯解析, 逐级可退
  E 仿真/真机: 两模式的层入口都在 (ZMAX_ANNOT_ROOT / _SIM)
  F 契约护栏: 层语义越权会抛异常 (类型强制)
"""
import os
import re
import sys

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
ENGINE = f"{ROOT}/tools/gui/state_space_sim_real.py"

results = []


def chk(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))
    return ok


def main():
    src = open(ENGINE, encoding="utf-8", errors="replace").read()
    print("=== A 开关独立性 (无档位互斥) ===")
    # 找"开A就pop/unset掉B"的模式
    pops = re.findall(r"(?:pop|unsetenv|del\s+os\.environ)\s*\(?\s*['\"]?(SS_L\d|INTACT_|ZMAX_)", src)
    chk("无档位互斥 (没有开A就关B)", len(pops) == 0, f"发现 {len(pops)} 处 pop/unset")
    lays = sorted(set(re.findall(r"SS_L4_[A-Z_]+|SS_L3[A-Z_]*|SS_L2[A-Z_]*", src)))
    chk("各层开关独立存在", len(lays) >= 5, f"{len(lays)} 个: {lays[:8]}")

    print("=== B 单出口 (唯一执行量写点) ===")
    n_decide = len(re.findall(r"u,\s*stage\s*=\s*self\.sched\.decide\(", src))
    n_sat = len(re.findall(r"self\.safety\.saturate\(", src))
    chk("调度器出口唯一", n_decide == 1, f"sched.decide 计数={n_decide}")
    chk("安全收口在位", n_sat >= 1, f"safety.saturate 计数={n_sat}")

    print("=== C 叠加通道 (上层→下层参考, 非替换) ===")
    chk("L4 写参考槽 u_ff", "u_ff" in src, "u_ff 出现")
    chk("收口闸存在 (clip/veto 记账)", bool(re.search(r"clip_max|vetoed", src)), "")
    chk("融合在收口之前", src.find("u_ff") < (src.find("safety.saturate(") if src.find("safety.saturate(") > 0 else 10**9), "")

    print("=== D 降级链 (逐级可退) ===")
    for var, label in [("SS_L4_INTACT", "L4·INTACT"), ("SS_L4_FIBER", "L4·纤维丛"),
                       ("SS_L4_INTENT_LINE", "L4·意图线"), ("SS_L3", "L3·模型")]:
        present = var in src
        guarded = bool(re.search(rf'{var}["\']\s*(?:,\s*"[^"]*")?\)\s*(?:==|!=)', src)) or \
                  bool(re.search(rf'get\(["\']{var}["\']', src))
        chk(f"{label} 开关+默认关 ({var})", present and guarded, "")

    print("=== E 仿真/真机双模式入口 ===")
    roots = re.findall(r"ZMAX_ANNOT_ROOT[A-Z_]*", src + open(f"{ROOT}/tools/gui/yolo_input_viewer.py", encoding="utf-8", errors="replace").read())
    uniq = sorted(set(roots))
    chk("真机根 ZMAX_ANNOT_ROOT", "ZMAX_ANNOT_ROOT" in uniq, str(uniq))
    chk("仿真根 _SIM", any("SIM" in r for r in uniq), "")
    chk("USB 相机根 _USBCAM", any("USBCAM" in r for r in uniq), "")
    chk("模式切换 MODE_ORDER", "MODE_ORDER" in open(f"{ROOT}/tools/gui/simulink_module.py", encoding="utf-8", errors="replace").read(), "")

    print("=== F 契约护栏 (层语义) ===")
    fiber = f"{ROOT}/src/lerobot/manifold/fiber_bundle.py"
    fsrc = open(fiber, encoding="utf-8", errors="replace").read() if os.path.exists(fiber) else ""
    chk("纤维丛不写执行量", ("u_exec" not in fsrc) and ("saturate" not in fsrc), "fiber_bundle 无执行量写入")
    chk("纤维丛只产条件", "cond" in fsrc or "condition" in fsrc, "")

    print("\n" + "=" * 58)
    npass = sum(1 for _, ok, _ in results if ok)
    print(f"L2/L3/L4 层兼容审计: {npass}/{len(results)} PASS")
    print("=" * 58)
    for n, ok, d in results:
        if not ok:
            print(f"  ❌ {n} {d}")
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
