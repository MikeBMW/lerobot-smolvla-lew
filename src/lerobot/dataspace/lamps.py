#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚦 状态灯 (Lamp) —— 每个模块/每条 topic 一盏灯, 四色语义

老倪 2026-09-29: 「所有 topic 数据, 都是一种系统状态的反馈或输入/输出信号; 每个模块要有个状态灯,
这个 DDS 总线上, 绿色表示正常, 红色表示故障, 黄色表示报警, 黑色表示无信号。」

四色定义(唯一口径, UI 不许自己另判):
  green  正常  : 该话题/模块在本档位下应有信号, 且所有规则都过
  yellow 报警  : 有告警级问题(频率偏低/抖动大/字段缺失/部分信号无/闭环缺证据) —— 记下来但不拦
  red    故障  : 有故障级问题(规则 violation / 闸门 veto / 值域越界 / NaN / 维度错)
  black  无信号: 本档位不发 / 窗口内 0 条 / 发布者没起 —— **无信号不是故障, 但要一眼看出来**

聚合规则(模块灯 = 它所有**输出信号**所在话题的灯):
  任一红 → 红 · 否则任一黄 → 黄 · 否则全黑 → 黑 · 否则有黑有绿 → 黄(部分信号无) · 否则绿
"""
import time

GREEN, YELLOW, RED, BLACK = "green", "yellow", "red", "black"
COLOR_HEX = {GREEN: "#2ecc71", YELLOW: "#f1c40f", RED: "#e74c3c", BLACK: "#000000"}
# 黑灯在深色底上要看得见 ⇒ 描边
OUTLINE_HEX = {GREEN: "#1b7a45", YELLOW: "#8a6d0b", RED: "#8e2a22", BLACK: "#6b7684"}
LABEL = {GREEN: "正常", YELLOW: "报警", RED: "故障", BLACK: "无信号"}
RANK = {BLACK: 0, GREEN: 1, YELLOW: 2, RED: 3}


def topic_state(key, rec, designed_hz=None, allowed=True, now=None, stale_s=5.0):
    """单条话题的灯 → (state, reason)

    rec: live.json 里这条话题的实测记录(可为 None); allowed: 本档位白名单是否包含
    """
    if not allowed:
        return BLACK, "本档位不发(白名单外)"
    if not rec:
        return BLACK, "探针未订阅/无记录"
    n = rec.get("count") or 0
    if n == 0 or (rec.get("hz") or -1.0) <= 0:
        return BLACK, "窗口内 0 条(发布端没起?)"
    # 数据停了 = 无信号(黑), 不能一直挂着黄灯 —— 实测: 停发后旧样点还在窗口里, 会被误判成"报警"
    # ⚠ 探针落盘的是 age_s(不是 last_ts); 两种都认, 否则这一支永远不生效(实测踩到: 63s 无数据仍报黄)
    age = rec.get("age_s")
    if age is None and rec.get("last_ts") and now:
        age = now - float(rec["last_ts"])
    lim = max(stale_s, 3.0 / max(designed_hz or 0.2, 1e-6))
    if age is not None and float(age) > lim:
        return BLACK, "无信号: 最后一条 %.1fs 前" % float(age)
    # 故障级: 规则 violation/veto
    for r in (rec.get("rules") or []):
        if not r.get("ok") and str(r.get("level", "")).lower() in ("violation", "veto", "error", "fail"):
            return RED, "%s: %s" % (r.get("rule", ""), str(r.get("msg", ""))[:56])
    v = str(rec.get("verdict", "")).lower()
    if v in ("violation", "veto"):
        return RED, "裁决 %s" % v
    # 告警级
    for r in (rec.get("rules") or []):
        if not r.get("ok"):
            return YELLOW, "%s: %s" % (r.get("rule", ""), str(r.get("msg", ""))[:56])
    if v == "warn":
        return YELLOW, "裁决 warn"
    if designed_hz and (rec.get("hz") or 0) and (rec.get("hz") or 0) < designed_hz * 0.6:
        return YELLOW, "实测 %.2fHz < 设计 %.2fHz 的 60%%" % (rec["hz"], designed_hz)
    if (rec.get("matched_pubs") or 0) == 0:
        return YELLOW, "配对 0(有样点但订阅端刚起来?)"
    return GREEN, "正常"


def _st_of(states, topic):
    """容错取灯: 全名 zmax/xxx 与短键 xxx 都认(实测: 总线库存全名, live.json 存短键)"""
    if topic in states:
        return states[topic]
    short = topic.split("/", 1)[1] if topic.startswith("zmax/") else topic
    return states.get(short, states.get("zmax/" + short, BLACK))


def module_state(node_id, signals, topic_states, level_map=None):
    """模块灯 = 其输出信号所在话题的灯聚合 → (state, reason, n_in, n_out)"""
    outs = [s for s in signals if s.get("src") == node_id]
    ins = [s for s in signals if s.get("dst") == node_id]
    if not outs and not ins:
        return BLACK, "无输入/输出信号", len(ins), len(outs)
    sts = [_st_of(topic_states, s["topic"]) for s in outs] or \
          [_st_of(topic_states, s["topic"]) for s in ins]
    n_red = sts.count(RED)
    n_yel = sts.count(YELLOW)
    n_blk = sts.count(BLACK)
    n_grn = sts.count(GREEN)
    if n_red:
        return RED, "%d 路输出故障" % n_red, len(ins), len(outs)
    if n_yel:
        return YELLOW, "%d 路输出报警" % n_yel, len(ins), len(outs)
    if n_blk and not n_grn:
        return BLACK, "输出信号无数据(%d 路)" % n_blk, len(ins), len(outs)
    if n_blk:
        return YELLOW, "%d 路输出无信号 / %d 路正常" % (n_blk, n_grn), len(ins), len(outs)
    return GREEN, "%d 路输出正常" % n_grn, len(ins), len(outs)


def tally(states):
    """灯计数(总览条/看板用)"""
    t = {GREEN: 0, YELLOW: 0, RED: 0, BLACK: 0}
    for s in states:
        t[s] = t.get(s, 0) + 1
    return t


def count_by_lamp(items):
    """items: [(state, ...)] → {'green':n,...}"""
    return tally([x[0] for x in items])


def worst(states):
    """最差灯(用于整机总灯)"""
    return max(states, key=lambda s: RANK.get(s, 0)) if states else BLACK
