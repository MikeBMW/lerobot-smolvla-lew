# -*- coding: utf-8 -*-
"""
══════════════════════════════════════════════════════════════════
🧠 记忆节点实现 (BLMA 分层记忆) — 真源归位 src/lerobot/memory
══════════════════════════════════════════════════════════════════
2026-09-09 老倪红线: L2/L3/L4 记忆节点 def 必须在此 (src), GUI 只薄注册转发。
生物映射: L2 小脑·肌肉记忆(DMP式标杆) / L3 海马体·情景记忆 / L4 前额叶·工作记忆(SSM)
数据: memory_store (data/shared_memory.json) + muscle_memory.json
"""
import time
import sys
import os

try:
    from lerobot.memory.memory_store import load, put, summary, muscle_lib, _path as _mem_path
except Exception:  # 同包相对兜底
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from memory_store import load, put, summary, muscle_lib, _path as _mem_path




def _sys_mem():
    """模块级记忆存储访问器 (memory_store 模块本身)"""
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))), "src"))
    try:
        from lerobot.memory import memory_store
        return memory_store
    except Exception:
        from memory_store import memory_store
        return memory_store

def node_ss_mem_l2(ctx):
    """🔧 L2 记忆 · 肌肉记忆 — 读真实固化库 muscle_memory.json: 固化技能/命中/模式"""
    log = ctx.get("log")
    try:
        st = _sys_mem()
        lib = st.muscle_lib() if st else {}
        skills = lib.get("skills") or lib.get("库") or {}
        if isinstance(skills, dict):
            items = [(k, (v.get("hits") if isinstance(v, dict) else v)) for k, v in list(skills.items())[:8]]
        else:
            items = []
        n_s = len(skills) if hasattr(skills, "__len__") else 0
        mode = lib.get("mode") or lib.get("_mode") or "off"
        if log:
            log(f"🔧 L2 记忆 · 肌肉记忆: 固化技能 {n_s} 项 · 模式 {mode} (🧠生物映射: 小脑/脊髓 — DMP式标杆回放)")
            for k, v in items:
                log(f"    · {k}: 命中 {v}")
            log("   语义: 重复动作≥3 次成功 → 标杆固化 → 快通道直通 (跳过精算, 安全链保留)")
            log("   总装: L3 规划取此标杆编排长链; 总装中枢汇总上报大模型层")
            # ⮕ 输出: 下行条目入共享 (供调度/技能行检索标杆)
            try:
                if st:
                    st.put("l2", "out", {
                        "time": __import__("time").strftime("%H:%M:%S"),
                        "固化技能": n_s, "模式": mode, "建议": "标杆直通可用" if n_s else "练习中 (≥3次成功固化)",
                    }, cap=20)
            except Exception:
                pass
        return True
    except Exception as e:
        if log:
            log(f"⚠️ L2 记忆读取失败: {e}")
        return False

def node_ss_mem_l3(ctx):
    """🚀 L3 记忆 · 长程规划 — 共享记忆里最近走通的跨段技能序列 (流程经验)"""
    log = ctx.get("log")
    try:
        st = _sys_mem()
        mem = st.load() if st else {}
        flows = (mem.get("l3", {}) or {}).get("flows") or []
        if log:
            if flows:
                f0 = flows[-1]
                log(f"🚀 L3 记忆 · 长程规划: {len(flows)} 轮流程经验 (🧠生物映射: 海马体 — 情景/扩散检索)")
                log(f"    最近: seed={f0.get('seed')} mode={f0.get('mode')} cap={f0.get('cap')} "
                    f"done={f0.get('done')} {f0.get('steps')}步")
                stg = f0.get("stages") or []
                log(f"    段路径 ({len(stg)}): {' → '.join(str(s)[:8] for s in stg[-12:])}")
                log(f"    mani 预测残差均值: {f0.get('mani_mae')} · z RMSE: {f0.get('z_rmse')}")
                # ⮕ 输出: 最近走通流程下行 (供调度/规划检索)
                try:
                    if st:
                        st.put("l3", "out", {
                            "time": __import__("time").strftime("%H:%M:%S"),
                            "seed": f0.get("seed"), "done": f0.get("done"),
                            "steps": f0.get("steps"),
                            "段路径": " → ".join(str(s)[:10] for s in (f0.get("stages") or [])[-10:]),
                        }, cap=20)
                except Exception:
                    pass
            else:
                log("🚀 L3 记忆 · 长程规划: 暂无流程经验 — 跑一轮真实化后自动入库")
            log("   语义: 每轮 13 段状态机路径/成败/质量指标 → 规划器检索'上次怎么走通的'")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ L3 记忆读取失败: {e}")
        return False

def node_ss_mem_l4(ctx):
    """🏆 L4 记忆 · 筹划 — 世界模型预测质量 + 恢复策略 (专家筹划输入)"""
    log = ctx.get("log")
    try:
        st = _sys_mem()
        mem = st.load() if st else {}
        preds = (mem.get("l4", {}) or {}).get("predict") or []
        recs = (mem.get("l4", {}) or {}).get("recover") or []
        if log:
            if preds:
                p0 = preds[-1]
                log(f"🏆 L4 记忆 · 筹划: {len(preds)} 轮预测质量 · 恢复策略 {len(recs)} 条 (🧠生物映射: 前额叶 — 工作记忆/SSM)")
                log(f"    最近: seed={p0.get('seed')} · mani 残差 {p0.get('mae')} · "
                    f"插拔段成功率 {p0.get('succ', '?')}")
                if recs:
                    r0 = recs[-1]
                    log(f"    恢复经验: {r0.get('event')} → {r0.get('action')} ({r0.get('n')}次)")
                # ⮕ 输出: 预测质量下行 (筹划建议给流形导航)
                try:
                    if st and preds:
                        st.put("l4", "out", {
                            "time": __import__("time").strftime("%H:%M:%S"),
                            "seed": preds[-1].get("seed"), "mae": preds[-1].get("mae"),
                            "建议": "预测残差已记录 — 恢复预算按流形误差分级",
                        }, cap=20)
                except Exception:
                    pass
            else:
                log("🏆 L4 记忆 · 筹划: 暂无 — 真实化完成后 predictor 残差自动入库")
            log("   语义: 预测流形误差/恢复动作选择 → 筹划下一步 (失败回退不放弃)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ L4 记忆读取失败: {e}")
        return False

def node_ss_mem_share(ctx):
    """🧠 共享记忆中枢 (大模型层) — 三层记忆汇总, 供 LLM 注入上下文"""
    log = ctx.get("log")
    try:
        st = _sys_mem()
        s = st.summary() if st else {}
        if log:
            log(f"🧠 总装记忆中枢 · 汇总 (前额叶总装 · 三层协同):")
            log(f"    L2 肌肉: 固化 {s.get('l2', {}).get('固化技能', 0)} 项 · "
                f"L3 流程: {s.get('l3', {}).get('流程经验', 0)} 轮 (最近 {s.get('l3', {}).get('最近')}) · "
                f"L4 筹划: {s.get('l4', {}).get('预测记录', 0)} 条 (残差 {s.get('l4', {}).get('最近残差')})")
            meta = s.get("meta") or {}
            log(f"    任务: {meta.get('task')} · 档位: {meta.get('cap')} · 更新: {meta.get('updated')}")
            log("    总装模式: L4 筹划→L3 编排→L2 执行, 各层写入总装表; LLM 规划器/异常推理器"
                "取总装条目作上下文, 高层决策回写 (信息总装非参数共享)")
            # ⮕ 输出: 组装总装上下文 → 写 meta.context (任务规划器/异常推理器消费)
            try:
                if st:
                    _ctx = (f"任务 {meta.get('task')} 档位 {meta.get('cap')} | "
                            f"L2固化{sum((s.get('l2') or {}).values())}项 | "
                            f"L3流程{sum((s.get('l3') or {}).values()) or 0}轮 | "
                            f"L4预测{sum((s.get('l4') or {}).values()) or 0}条")
                    st.put("meta", "context", _ctx)
                    log(f"    ⮕ 输出 → 🧠任务规划器/🔍异常推理器: {_ctx}")
            except Exception:
                pass
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 共享中枢读取失败: {e}")
        return False
