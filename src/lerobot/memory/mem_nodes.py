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


# ══════════════════════════════════════════════════════════════════
# 🧠🧬 S1 意图丛节点 (2026-09-10 老倪: 三层能力共享 — 记忆图谱连接层)
#   设计: docs/design/zmax_intent_bundle_3layer.md
#   真源: src/lerobot/memory/memory_graph.py (links / recall / 技能词典 / 意图直读)
# ══════════════════════════════════════════════════════════════════
def _mg():
    """memory_graph 访问器 (延迟导入, 失败返回 None)"""
    import sys as _s, os as _o
    _s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.dirname(
        _o.path.abspath(__file__)))), "src"))
    try:
        from lerobot.memory import memory_graph
        return memory_graph
    except Exception:
        return None


def node_ss_intent_bundle(ctx):
    """🧠 意图丛 · 四槽语法 — goal/from/skill/gate 统一意图接口
    (层间只传意图向量 Δz=z_g−z_t, 动作只在 L2 生成 — INTACT 同构接口落地)"""
    log = ctx.get("log")
    try:
        mg = _mg()
        m = ctx.get("module")
        tr = getattr(m, "_ss_tr", None) if m is not None else None
        i = int(getattr(m, "_ss_round", 0) or 0)
        if log:
            log("🧠 意图丛 · 四槽意图语法 (INTACT 同构接口):")
            log("    goal : 目标潜在点 z_g (L4 筹划产出 — 势场目标)")
            log("    from : 当前 z_t + 段 s + 夹持相位 (感知层)")
            log("    skill: L2 技能 id + 参数 (L3 编排产出)")
            log("    gate : 验收度量 (mani 6维 / 位置残差) + 阈值")
        if tr:
            import numpy as _np
            tgt = tr.get("target") or []
            stg_l = tr.get("stage") or []
            j = min(i, len(stg_l) - 1) if stg_l else -1
            stg = str(stg_l[j]).replace("阶段 ", "").split("·")[0].strip() if j >= 0 else ""
            sk = (mg.STAGE_TO_SK.get(stg, "SK-EXT:" + stg) if (mg and stg) else None)
            if log:
                _t = _np.round(_np.asarray(tgt[j], float), 4) if (tgt and j < len(tgt)) else "-"
                log(f"    当前帧[{i}]: 段={stg or '-'} → 技能={sk or '-'} | goal={_t}")
        if mg is not None and log:
            log(f"    L2 动作基可用: {len(mg.skill_dict())} 技能 (词典) — 层间只传 Δz, 动作只在 L2 出")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 意图丛读取失败: {e}")
        return False


def node_ss_skill_dict(ctx):
    """🧬 技能词典 · L2 动作基 — {skill → Δz/n_ok/帧长}
    (L4 预测 Δz 后在此词典上 kNN 直读技能, 无需连续动作空间搜索)"""
    log = ctx.get("log")
    try:
        mg = _mg()
        if mg is None:
            if log:
                log("⚠️ 技能词典: memory_graph 不可用")
            return False
        m = ctx.get("module")
        _sd = getattr(m, "seed", None) if m is not None else None
        try:
            seed = int(_sd) if _sd is not None else None
        except Exception:
            seed = None
        d = mg.skill_dict(seed=seed)
        if log:
            log(f"🧬 技能词典 · L2 动作基 (seed={seed if seed is not None else '全'}): {len(d)} 技能")
            for sk, v in sorted(d.items()):
                log(f"    {sk} {v.get('stage')}: Δz={v.get('dz')} n_ok={v.get('n_ok')} 帧={v.get('frames')}")
            log("    语义: L4 预测 Δz → 词典 kNN 直读技能 (动作基 = L2 已练成的标杆)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 技能词典读取失败: {e}")
        return False


def node_ss_mem_links(ctx):
    """🔗 跨层连接 · 记忆图谱 — links(L4筹划→L3流程→L2技能) + 意图检索 recall"""
    log = ctx.get("log")
    try:
        mg = _mg()
        if mg is None:
            if log:
                log("⚠️ 跨层连接: memory_graph 不可用")
            return False
        g = mg.graph_summary()
        if log:
            log(f"🔗 跨层连接 · 记忆图谱: 层间链接 {g.get('n_links', 0)} 条 · 技能词典 {g.get('skill_dict_size', 0)} 技能")
            log(f"    L2 {g.get('l2')} | L3 {g.get('l3')} | L4 {g.get('l4')}")
            for lk in (g.get("recent_links") or [])[-3:]:
                log(f"    ↳ 链接: seed{lk.get('seed')} {lk.get('cap')} 技能{lk.get('skills')} ({lk.get('cause')})")
        m = ctx.get("module")
        _sd = getattr(m, "seed", None) if m is not None else None
        try:
            seed = int(_sd) if _sd is not None else None
        except Exception:
            seed = None
        r = mg.recall(stages=["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"],
                      seed=seed, k=2)
        if log:
            if r.get("hits"):
                for h in r["hits"]:
                    log(f"    🔎 recall 命中 score={h['score']} seed={h['flow'].get('seed')} "
                        f"技能={h['skills'][:5]} L4={'有' if h.get('l4') else '无'}")
            else:
                log(f"    🔎 recall: {r.get('reason')}")
            log("    语义: L3/L4 经此检索复用 L2 标杆经验 (跨层能力共享, 带距离门防负迁移)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 跨层连接读取失败: {e}")
        return False


def node_ss_intent_direct(ctx):
    """🔮 意图直读 · Direct (INTACT) — Δz → 技能 kNN (无搜索, 实测延迟 ms 级)"""
    log = ctx.get("log")
    try:
        mg = _mg()
        if mg is None:
            if log:
                log("⚠️ 意图直读: memory_graph 不可用")
            return False
        d = mg.skill_dict()
        if not d:
            if log:
                log("🔮 意图直读: 技能词典为空 (L2 尚未固化 — 先练 ≥3 次成功)")
            return True
        qk = next((k for k, v in d.items() if v.get("dz")), None)
        q = d[qk]["dz"] if qk else None
        r = mg.intent_direct(q)
        if log:
            log(f"🔮 意图直读 · Direct (INTACT): 查询 Δz={q} (取自 {qk})")
            log(f"    命中技能={r.get('hit')} dist={r.get('dist')} 延迟={r.get('latency_ms')}ms")
            log(f"    method: {r.get('method')}")
            log("    参照 INTACT 论文: Direct 推理 2.9-5.5ms (无 CEM 搜索); 真意图向量接入待 S2/S3")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 意图直读失败: {e}")
        return False


def node_ss_motor_hub(ctx):
    """🦾 运动基元库 — L2 肌肉记忆的共享抽象 (发力/速度/加速度/时长 → 全局基元)

    老倪 09-10: "L2 原子技能都是肌肉记忆, 应该都知道怎么发力、速度、加速度, 怎么更快更稳更准
    — 把这个信息共享给总装记忆。" 本节点展示从标杆提取出的共享基元库。
    """
    log = ctx.get("log")
    try:
        import json as _j
        import os as _o
        _root = _o.environ.get("ZMAX_ROOT", "/home/ubuntu/lerobot-smolvla-lew")
        _sh = _j.load(open(_o.path.join(_root, "data", "shared_memory.json")))
        m = _sh.get("motor") or {}
        prim = m.get("primitives") or []
        s = m.get("sharing") or {}
        if not prim:
            if log:
                log("🦾 运动基元库: 空 (先运行 src/lerobot/memory/motor_hub.py 提取)")
            return True
        if log:
            log(f"🦾 运动基元库: {s.get('n_prim')} 个共享基元 / {s.get('n_seg')} 条标杆 · "
                f"参数压缩 {s.get('compression')}× · {s.get('n_multi_stage')} 个基元被多技能共用")
            for p in prim:
                f = (p.get("feat") or [0] * 11)
                log(f"   #{p.get('id')} {p.get('name')}: {'/'.join(p.get('stages') or [])}")
                log(f"      速度峰 {f[5]:.4f} · 加速峰 {f[7]:.4f} · 发力峰 {f[8]:.3f} · "
                    f"{f[0]:.0f}帧 · 离散度 {p.get('spread')}")
            mp = m.get("mapping") or {}
            if mp:
                log("   阶段→基元: " + " · ".join(f"{k}→#{v.get('primitive')}" for k, v in mp.items()))
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 运动基元库读取失败: {e}")
        return False


def node_ss_global_mem(ctx):
    """🧠 全局记忆中枢 — L4 物理规律 / L3 流程 / L2 肌肉 三层联合体检 + 一次性就位

    参考 INTACT Fig.1: 共享编码器 + 图同构二态意图语法(attached 局部 / detached 目标),
    公共键 = (阶段, Δz); 判定基于证据(L3 成功率 / L4 可行率), 不做无根据的乐观结论。
    """
    log = ctx.get("log")
    try:
        from lerobot.memory.global_memory import GlobalMemory
        gm = GlobalMemory()
        if log:
            for line in gm.report().split("\n"):
                log("   " + line)
            q = gm.query("插入")
            log("   二态意图语法: attached z_t+1−z_t (肌肉记忆) | detached z_g−z_t (流程/物理)")
            log(f"   插入段体检: 基元={(q['l2'] or {}).get('name')} · "
                f"L3成功率={(q['l3'] or {}).get('done_rate')} → {q['consistency']['verdict']}")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 全局记忆中枢失败: {e}")
        return False
