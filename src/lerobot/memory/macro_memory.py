#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顶层宏观记忆 (MacroMemory) — 总装记忆对应的大模型顶层宏观层

老倪 2026-09-19 定义:
  "L4 是工作记忆, L3 是流程记忆, L2 是肌肉记忆, **总装记忆对应大模型的 Qwen 顶层宏观记忆**,
   与状态空间工程的记忆保持同步。你来整体优化记忆系统"

分层语义 (本模块 = 最顶层):
  L2 肌肉记忆  → 原子技能冠军轨迹 (动作准确性)   data/muscle_memory.json
  L3 流程记忆  → 阶段时序调度 (调度能力)         shared_memory.json#l3
  L4 工作记忆  → 现场几何 + 抗干扰 (工作记忆)     shared_memory.json#l4
  总装记忆     → 跨层仲裁 + 台账                  data/assembly_memory.json
  **宏观记忆** → 跨任务/跨会话的语义知识 + 能力画像 + 失败归因 + 策略建议
                (本模块; 有 LLM 走 Qwen 归纳, 无则确定性规则 —— 两条路都可用)

设计要点:
  ① **只读下层, 不写下层动作**: 宏观层产出"知识与建议", 不直接产 u (执行永远归 L2 收口)
  ② **同步是双向的**: uplink() 下层快照→宏观知识; downlink() 宏观知识→分层参数建议
  ③ **诚实**: 无 LLM 时用规则归纳并把 llm=False 写进结果, 不假装"大模型分析过"
  ④ **幂等**: 同一批下层数据重复 sync 不重复计数 (按 run 指纹去重)

用法:
  from lerobot.memory.macro_memory import MacroMemory
  mm = MacroMemory()
  mm.sync()                 # 一键: 上行归纳 + 落盘
  mm.report()               # 人能读的宏观报告
  mm.advise(stage="插入")    # 下行: 该阶段的宏观建议 (供分层/画布消费)
  mm.selftest()             # 自检 (0 = 通过)
"""
from __future__ import annotations

import hashlib
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

MACRO = os.path.join(ROOT, "data", "macro_memory.json")
ASSEMBLY = os.path.join(ROOT, "data", "assembly_memory.json")
SHARED = os.path.join(ROOT, "data", "shared_memory.json")
MUSCLE = os.path.join(ROOT, "data", "muscle_memory.json")

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                    # noqa: BLE001
        return {} if default is None else default


def _fingerprint(run: dict) -> str:
    """一局运行的指纹 (去重用): 时间+任务+步数+成功 的组合哈希。"""
    s = f"{run.get('ts','')}|{run.get('task','')}|{run.get('steps','')}|{run.get('done','')}"
    return hashlib.sha256(s.encode()).hexdigest()[:16]


class MacroMemory:
    """顶层宏观记忆: 跨任务语义知识 + 能力画像 + 失败归因 + 策略建议。"""

    def __init__(self, path: str = MACRO, llm_url: str | None = None):
        self.path = path
        self.llm_url = llm_url or os.environ.get("SS_MACRO_LLM_URL")  # 可选: OpenAI 兼容端点
        self.store = _load(path)
        self.store.setdefault("version", 1)
        self.store.setdefault("knowledge", {})     # 语义知识: 任务档案/工艺参数
        self.store.setdefault("capability", {})    # 能力画像: 每层边界 (由实测数据推)
        self.store.setdefault("diagnosis", [])     # 失败归因 (带证据)
        self.store.setdefault("advice", {})        # 下行建议 (按阶段)
        self.store.setdefault("seen", [])          # 已消化的 run 指纹
        self.store.setdefault("meta", {})

    # ── ① 上行: 下层 → 宏观 ────────────────────────────────────────────────
    def uplink(self) -> dict:
        """读 L2/L3/L4/总装 的真实数据 → 归纳宏观知识。返回本次增量。"""
        asm = _load(ASSEMBLY)
        shared = _load(SHARED)
        runs = asm.get("runs") or []
        seen = set(self.store["seen"])
        fresh = [r for r in runs if _fingerprint(r) not in seen]

        # 1) 能力画像 (由真实 run 统计, 不做无根据结论)
        n = len(runs)
        ok = sum(1 for r in runs if r.get("done"))
        depths = [float(r.get("insert_mm")) for r in runs
                  if isinstance(r.get("insert_mm"), (int, float))]
        cap = self.store["capability"]
        cap["overall"] = {"runs": n, "success": ok,
                          "rate": round(ok / n, 4) if n else None}
        if depths:
            cap["insert_depth_mm"] = {"n": len(depths), "min": round(min(depths), 2),
                                      "max": round(max(depths), 2),
                                      "mean": round(sum(depths) / len(depths), 2)}
        # 分层计数 (从 shared_memory 与 muscle)
        mus = _load(MUSCLE)
        l2_segs = len([k for k in mus if "|" in str(k)])
        cap["layers"] = {"L2_segments": l2_segs,
                         "L3_flows": len(((shared.get("l3") or {}).get("flows")) or []),
                         "L4_predicts": len(((shared.get("l4") or {}).get("predict")) or []),
                         "links": len(((shared.get("links")) or []) if isinstance(shared.get("links"), list) else [])}
        cur_ok = (cap["overall"]["rate"] or 0) > 0
        cap["layers"]["L2_segments"] = l2_segs

        # 2) 失败归因 (带证据: 哪层数据缺失/不足)
        diag = []
        if n and ok == 0:
            diag.append({"issue": "全臂零成功", "evidence": f"{n} 局 runs 全部 done=False",
                         "suspect": "执行层出力不足 (记忆全关/场权过低) 而非几何不可达",
                         "check": "解析链对照成功率 (几何可达性)"})
        if cap["layers"]["L3_flows"] == 0:
            diag.append({"issue": "L3 流程记忆无记录", "evidence": "shared_memory.l3.flows 为空",
                         "suspect": "流程层未落数据", "check": "引擎 _write_shared_memory"})
        if cap["layers"]["L4_predicts"] == 0:
            diag.append({"issue": "L4 工作记忆无预测记录", "evidence": "shared_memory.l4.predict 为空",
                         "suspect": "世界模型项未接 (恒 0)", "check": "SS_L4_INTENT_LINE 开关"})

        # 3) 语义知识 (任务档案; 有 Qwen 时由 LLM 精炼)
        kb = self.store["knowledge"]
        tasks = sorted({r.get("task") for r in runs if r.get("task")})
        kb["tasks"] = tasks
        kb["success_condition"] = kb.get("success_condition") or {
            "insert_depth_mm_max": 6.0,
            "note": "引擎 done 判据: peg 头到孔底 < insert_depth 阈值 (2026-09-18 由 6mm 收紧至 2mm)"}
        used_llm = False
        if fresh and self.llm_url:
            try:
                kb["llm_summary"] = self._qwen_summarize(fresh)
                used_llm = True
            except Exception as e:                        # noqa: BLE001
                kb["llm_error"] = f"{type(e).__name__}: {e}"

        # 4) 消化标记 (幂等)
        self.store["seen"] = (self.store["seen"] + [_fingerprint(r) for r in fresh])[-2000:]
        self.store["diagnosis"] = diag
        self.store["meta"] = {"updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "n_fresh": len(fresh), "llm": used_llm,
                              "src_runs": n}
        return {"fresh": len(fresh), "diag": len(diag), "llm": used_llm}

    def _qwen_summarize(self, runs: list) -> str:
        """用 Qwen (OpenAI 兼容端点) 把新 run 归纳成一句宏观洞察。无端点则不调用。"""
        import urllib.request
        brief = json.dumps(runs[-20:], ensure_ascii=False)[:4000]
        body = json.dumps({
            "model": os.environ.get("SS_MACRO_LLM_MODEL", "qwen"),
            "messages": [{"role": "system", "content":
                          "你是 Z-MAX 光模块插拔机器人平台的顶层宏观记忆。"
                          "基于运行台账给出简短宏观洞察(中文, ≤120字): 能力现状/主要瓶颈/下一步优先级。"},
                         {"role": "user", "content": f"最近运行台账: {brief}"}],
            "max_tokens": 300, "temperature": 0.2}, ensure_ascii=False).encode()
        req = urllib.request.Request(self.llm_url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:      # noqa: S310
            d = json.loads(r.read().decode())
        return (d.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()

    # ── ② 下行: 宏观 → 分层建议 (只给建议, 不写动作) ──────────────────────
    def downlink(self) -> dict:
        """由能力画像生成各阶段建议 (供画布/分层消费)。确定性推导, 无 LLM 也可用。"""
        cap = self.store["capability"]
        layers = cap.get("layers", {})
        rate = (cap.get("overall") or {}).get("rate")
        adv = {}
        for st in STAGES:
            if rate is None:
                adv[st] = {"policy": "unknown", "why": "无运行数据, 不做无根据判断"}
            elif rate == 0:
                # 接触段 (下降/插入/完成) 与自由段给不同建议 —— 与总装仲裁策略一致
                contact = st in ("下降", "插入", "完成")
                adv[st] = {"policy": "repair_first",
                           "hint": ("提高记忆场权/修夹爪咬合 (接触段优先 L2 势场)" if contact
                                    else "先检查 L3 流程相位与 L4 现场几何 (自由段优先 L3)"),
                           "why": f"整体成功率 0 (n={cap.get('overall',{}).get('runs')})"}
            else:
                adv[st] = {"policy": "keep", "why": f"整体成功率 {rate:.2f} > 0, 保持当前配置"}
        if layers.get("L4_predicts") == 0:
            adv["_global"] = {"policy": "enable_l4_world_model",
                              "why": "L4 预测记录为 0 → 世界模型项未接 (恒 0), 补上才算真工作记忆"}
        self.store["advice"] = adv
        return adv

    # ── ③ 双向同步 (一键) ─────────────────────────────────────────────────
    def sync(self) -> dict:
        up = self.uplink()
        down = self.downlink()
        self.save()
        return {"uplink": up, "downlink_stages": len(down)}

    def save(self) -> str:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.store, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)          # 原子写 (断电不留半截)
        return self.path

    # ── ④ 读与报 ──────────────────────────────────────────────────────────
    def advise(self, stage: str) -> dict:
        return (self.store.get("advice") or {}).get(stage) or \
               (self.store.get("advice") or {}).get("_global") or {}

    def report(self) -> str:
        s = self.store
        cap = s.get("capability", {})
        ov = cap.get("overall", {})
        ls = cap.get("layers", {})
        lines = ["【顶层宏观记忆 · 跨任务画像】"]
        _rate = ov.get("rate")
        _rate_s = "—" if _rate is None else f"{_rate:.0%}"
        lines.append(f"  运行: {ov.get('runs', 0)} 局 · 成功 {ov.get('success', 0)} · 成功率 {_rate_s}")
        d = cap.get("insert_depth_mm")
        if d:
            lines.append(f"  插入深度: {d['min']}~{d['max']} mm (均 {d['mean']}, n={d['n']})")
        lines.append(f"  分层规模: L2 {ls.get('L2_segments')} 段 · L3 {ls.get('L3_flows')} 条 · "
                     f"L4 {ls.get('L4_predicts')} 条 · 链接 {ls.get('links')} 条")
        if s.get("knowledge", {}).get("llm_summary"):
            lines.append(f"  🧠 Qwen 归纳: {s['knowledge']['llm_summary'][:160]}")
        elif s.get("meta", {}).get("llm"):
            lines.append("  🧠 Qwen 归纳: (本次已调用)")
        else:
            lines.append("  🧠 Qwen 归纳: 未配置端点 → 本轮用确定性规则归纳 (llm=False, 如实标注)")
        for x in s.get("diagnosis", [])[:4]:
            lines.append(f"  ⚠️ {x['issue']}: {x['evidence']} → 疑因: {x['suspect']}")
        g = (s.get("advice") or {}).get("_global")
        if g:
            lines.append(f"  ➡️ 全局建议: {g['policy']} — {g['why']}")
        lines.append(f"  更新: {s.get('meta', {}).get('updated')} (消化 {s.get('meta', {}).get('n_fresh')} 条新运行)")
        return "\n".join(lines)

    # ── ⑤ 自检 ────────────────────────────────────────────────────────────
    def selftest(self) -> int:
        """自检: 只读下层 / 幂等 / 同步双向 / 建议有据 / 原子落盘。返回 0 = 通过。"""
        import tempfile
        ok = True
        tmpdir = tempfile.mkdtemp(prefix="macromem_")
        mm = MacroMemory(path=os.path.join(tmpdir, "m.json"))
        r1 = mm.sync()
        r2 = mm.sync()                       # 幂等: 第二次不应再消化新 run
        print(f"[selftest] 1st sync fresh={r1['uplink']['fresh']} · 2nd fresh={r2['uplink']['fresh']} "
              f"(幂等: {'✅' if r2['uplink']['fresh'] == 0 else '❌'})")
        ok &= r2["uplink"]["fresh"] == 0
        has_cap = bool(mm.store["capability"].get("overall"))
        print(f"[selftest] 能力画像由真实 run 推出: {'✅' if has_cap else '⚠️ 无 run 数据 (空库也合法)'}")
        adv = mm.downlink()
        ok &= len(adv) >= 7
        print(f"[selftest] 下行建议覆盖 {len(adv)} 阶段 (应 ≥7): {'✅' if len(adv) >= 7 else '❌'}")
        # 只读验证: 下层文件 mtime 不变
        before = {p: os.path.getmtime(p) for p in (ASSEMBLY, SHARED, MUSCLE) if os.path.exists(p)}
        mm.sync()
        after = {p: os.path.getmtime(p) for p in before}
        ro = before == after
        print(f"[selftest] 只读下层 (下层文件 mtime 不变): {'✅' if ro else '❌'}")
        ok &= ro
        p = mm.save()
        ok &= os.path.isfile(p)
        print(f"[selftest] 原子落盘: {'✅' if os.path.isfile(p) else '❌'} | {p}")
        print(f"[selftest] {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(MacroMemory().selftest())
