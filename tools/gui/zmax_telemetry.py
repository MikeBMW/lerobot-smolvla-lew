#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔀 Z-MAX 遥测模式开关 —— DDS topic 只用于 测试/标定/诊断, 量产关闭

老倪 2026-09-25: "topic用于测试, 标定, 诊断, 量产时不用, 你来设计架构,
                 即我可以随时用topic, 但量产会关闭"

════════════════════════════════════════════════════════════════════
架构原则
════════════════════════════════════════════════════════════════════
① **协议统一**: 全局数据空间统一用 DDS 语义（话题名/字段/QoS 一套口径）
② **传输可关**: 「是否真的起 DDS 发布/订阅」是一个**模式**, 不是代码分支
③ **量产零开销**: prod 模式**根本不 import cyclonedds**、不起线程、不开端口
   → 量产环境不需要装 cyclonedds, 也不承担任何延迟/安全风险
④ **随时可开**: 一条命令/一个开关/一个环境变量即可切换, 业务代码**无需改动**
   → 现场诊断: 切 diag → 看完 → 切回 prod（不清场、不重编）

════════════════════════════════════════════════════════════════════
模式定义（按用途分档, 每档只开需要的话题子集）
════════════════════════════════════════════════════════════════════
  prod   量产      全关（默认档; 无 DDS, 零开销）
  diag   诊断      硬件/性能/延时/错误/心跳
  calib  标定      位姿/几何/力/流形（高频 + 高精度）
  test   测试      全量（含连线数据/动作/推理/画布节点）
  dev    开发      = test（开发时等同）

════════════════════════════════════════════════════════════════════
开关优先级（从高到低）
════════════════════════════════════════════════════════════════════
  ① 环境变量 ZMAX_TELEMETRY=diag          （进程级, 最优先）
  ② 运行时 set_mode()（GUI 开关/外部 agent 调用）
  ③ 模式文件 ~/.zmax_telemetry_mode       （跨进程共享, 随时改）
  ④ 默认 prod
"""
import os
import threading
import time

MODE_FILE = os.path.expanduser("~/.zmax_telemetry_mode")
MODES = ("prod", "diag", "calib", "test", "dev")

# 每档开启的话题（★ prod 为空 = 全关）
MODE_TOPICS = {
    "prod":  [],
    "diag":  ["hw_state", "heartbeat", "ss_infer", "train_prog"],
    "calib": ["ss_state", "ss_action", "link_value", "hw_state", "heartbeat"],
    "test":  ["hw_state", "heartbeat", "train_prog", "deploy_cmd",
              "link_value", "ss_state", "ss_action", "ss_infer",
              "ss_canvas", "ss_macro", "ss_nodes"],
    "dev":   ["hw_state", "heartbeat", "train_prog", "deploy_cmd",
              "link_value", "ss_state", "ss_action", "ss_infer",
              "ss_canvas", "ss_macro", "ss_nodes"],
}

_LOCK = threading.Lock()
_MODE = None          # 运行时覆盖（内存）
_LAST_READ = 0.0


def _read_file_mode():
    try:
        if os.path.isfile(MODE_FILE):
            m = open(MODE_FILE, encoding="utf-8").read().strip().lower()
            if m in MODES:
                return m
    except Exception:                                                           # noqa: BLE001
        pass
    return None


def mode(refresh=True):
    """当前模式（优先级: env > 运行时 > 文件 > prod）"""
    global _MODE
    env = (os.environ.get("ZMAX_TELEMETRY") or "").strip().lower()
    if env in MODES:
        return env
    if _MODE is not None and refresh:
        return _MODE
    fm = _read_file_mode()
    if fm:
        return fm
    return "prod"


def is_enabled(refresh=True):
    """是否启用 DDS 遥测（prod = False → 调用方**不应 import cyclonedds**）"""
    return mode(refresh) != "prod"


def topics():
    """当前模式允许的话题子集（prod = 空列表）"""
    return list(MODE_TOPICS.get(mode(), []))


def allow(topic):
    """某话题在当前模式下是否允许发布/订阅"""
    return topic in MODE_TOPICS.get(mode(), [])


def set_mode(m, persist=True):
    """★ 切换模式（随时可用）: 写文件持久 + 立即生效; 返回 (旧, 新)"""
    global _MODE
    m = (m or "").strip().lower()
    if m not in MODES:
        raise ValueError("模式必须是 %s 之一, 收到 %r" % ("/".join(MODES), m))
    with _LOCK:
        old = mode(refresh=False)
        _MODE = m
        if persist:
            try:
                with open(MODE_FILE, "w", encoding="utf-8") as f:
                    f.write(m + "\n")
            except Exception:                                                   # noqa: BLE001
                pass
    return old, m


def toggle():
    """一键在 prod ⇄ diag 间切换（现场最常用: 诊断开/关）"""
    cur = mode()
    return set_mode("diag" if cur == "prod" else "prod")


def status_text():
    m = mode()
    t = topics()
    if m == "prod":
        return "遥测: 🔴 量产关闭（无 DDS, 零开销）"
    return "遥测: 🟢 %s（%d 个话题: %s）" % (m, len(t), ",".join(sorted(t)[:6]) + ("…" if len(t) > 6 else ""))


def summary():
    return {"mode": mode(), "enabled": is_enabled(), "topics": topics(),
            "mode_file": MODE_FILE, "env": os.environ.get("ZMAX_TELEMETRY", ""),
            "allowed_modes": list(MODES)}


# ══════════════════════════════════════════════════════════════════
# 受模式约束的 DDS 总线工厂（业务代码只调这里, 不看模式）
# ══════════════════════════════════════════════════════════════════
_BUS = None
_BUS_LOCK = threading.Lock()


def telemetry_bus():
    """★ 遥测总线: 非 prod 返回 DdsLinkBus, prod 返回 None

    - **prod**: 直接返回 None → 调用方零分支地跳过（且本函数**不 import cyclonedds**）
    - 其他模式: 懒加载总线; 加载失败返回 None（零回退, 不打断业务）
    """
    global _BUS
    if not is_enabled():
        return None                       # ★ 量产: 这里就 return, 连 import 都不发生
    if _BUS is not None:
        return _BUS
    with _BUS_LOCK:
        if _BUS is not None:
            return _BUS
        try:
            import sys
            _d = os.path.dirname(os.path.abspath(__file__))
            for c in ("/home/ubuntu/zmax_dds", _d):
                if os.path.isdir(c) and c not in sys.path:
                    sys.path.insert(0, c)
            from dds_link_bus import get_bus
            _BUS = get_bus()
            print("[遥测] 已启用:", status_text())
        except Exception as e:                                                  # noqa: BLE001
            print("[遥测] 总线不可用(回落本地):", str(e)[:110])
            _BUS = None
    return _BUS


def drop_bus():
    """关闭遥测时释放总线引用（下次开启会重建）"""
    global _BUS
    _BUS = None


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Z-MAX 遥测模式开关（DDS 只用于测试/标定/诊断）")
    ap.add_argument("--mode", choices=MODES, help="切换模式")
    ap.add_argument("--toggle", action="store_true", help="prod ⇄ diag 一键切换")
    ap.add_argument("--status", action="store_true", help="显示当前状态(JSON)")
    a = ap.parse_args()
    if a.mode:
        old, new = set_mode(a.mode)
        print("  ✅ 遥测模式: %s → %s" % (old, new))
    elif a.toggle:
        old, new = toggle()
        print("  ✅ 遥测模式: %s → %s" % (old, new))
    if a.status or not (a.mode or a.toggle):
        import json
        print(json.dumps(summary(), ensure_ascii=False, indent=1))
    print(" ", status_text())
