#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bypass_sensor_source.py — 旁路真机感知数据源 (框架层, 无 Qt/torch 依赖)

用途: 状态空间画布的「📡 旁路真机传感器」节点 → 读 **真机** 感知流 (4060 侧远程只读采集),
      **不是** metaworld 仿真数据。数据来源 = ss_remote_tap 落盘的 state_*.jsonl + status.json。

铁律 (老倪红线 / 老倪目检口径):
  · 只读文件, 不发布/不写回 Orin, 不启动任何进程
  · 数据不新鲜 → 明确报 age 秒数并置 fresh=False, 绝不用旧帧冒充"实时"
  · 缺的通道 (力/夹爪/几何) 一律列入 gaps 显式报缺, 不填 0 冒充真值

对外接口:
    probe() -> dict                 # 数据源体检: 文件/新鲜度/频率/通道可用性
    read_latest() -> dict           # 最新一帧真机感知 (含 gaps / fresh / age_s)
    read_bypass_status() -> dict    # 旁路运行器心跳 (阶段/残差/接触p/零下行自证/缺口)
    tail_bypass(n) -> list[dict]    # 旁路逐帧记录最近 n 条 (画曲线用)
    tail_state(n) -> list[dict]     # 真机逐帧历史 (t/tcp/六维力, 增量读 → 位姿与插入力波形)
"""
import json
import os
import time

REMOTE_DIR = os.environ.get("SS_REMOTE_DIR", os.path.expanduser("~/zmax_ss_remote"))
BYPASS_DIR = os.environ.get("SS_BYPASS_DIR", os.path.expanduser("~/zmax_data/ss_bypass"))
STALE_S = float(os.environ.get("SS_SENSOR_STALE_S", "3.0"))   # 超过此秒数视为不新鲜
IMG_FRESH_S = float(os.environ.get("SS_IMG_FRESH_S", "5.0"))  # 图像帧新鲜窗口 (超时不显示, 防旧图冒充)


def _latest_file(d, prefix):
    try:
        cands = [os.path.join(d, f) for f in os.listdir(d) if f.startswith(prefix) and f.endswith(".jsonl")]
    except Exception:
        return None
    return max(cands, key=os.path.getmtime) if cands else None


def _tail_json(path, n=1, chunk=65536):
    """高效读尾部 n 行 JSON (只读末尾 chunk 字节, 不整文件扫)"""
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - chunk))
            raw = f.read().decode("utf-8", errors="replace").splitlines()
        out = []
        for ln in reversed(raw):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
            if len(out) >= n:
                break
        return list(reversed(out))
    except Exception:
        return []


def read_latest():
    """最新一帧真机感知 → dict (含 fresh/age_s/gaps)"""
    path = _latest_file(REMOTE_DIR, "state_")
    rows = _tail_json(path, n=12)
    if not rows:
        return {"ok": False, "reason": f"无真机感知数据 ({REMOTE_DIR}/state_*.jsonl)", "fresh": False,
                "gaps": {"数据源": True}, "file": path}
    r = dict(rows[-1])
    # 稀疏话题 (力/夹爪/机器人状态/图像 ~2-12Hz) 的最新值可能不在最后一帧 → 回看最近 12 帧取最近非空
    for _k in ("ft", "gripper", "robot_status", "prod_stage", "image"):
        if r.get(_k) is None:
            for _r in reversed(rows):
                if _r.get(_k) is not None:
                    r[_k] = _r[_k]
                    break
    age = max(0.0, time.time() - float(r.get("t", 0)))
    gaps = {k: True for k, v in (("夹爪开度", r.get("gripper")), ("六维力", r.get("ft")),
                                 ("关节速度", r.get("jvel")), ("场景几何 z7", r.get("z7")),
                                 ("机器人状态", r.get("robot_status"))) if v is None}
    pubs = r.get("pubs") or {}
    img = r.get("image") or {}
    imgs_by_topic = r.get("images_by_topic") or {}
    if img and img.get("t") is not None:
        _p = img.get("path") or os.path.join(REMOTE_DIR, "cam_latest.png")
        _age = round(time.time() - float(img["t"]), 2)
        # ⚠️ 只认新鲜帧 (age ≤ IMG_FRESH_S): 旧图/离线测试图绝不当作实时图
        img = dict(img, age=_age, png=(_p if (os.path.exists(_p) and _age <= IMG_FRESH_S) else None))
    if imgs_by_topic:
        _out = {}
        for _t, _v in imgs_by_topic.items():
            if not _v:
                continue
            _p = _v.get("path")
            _age = round(time.time() - float(_v.get("t", 0)), 2)
            _out[_t] = dict(_v, age=_age,
                            png=(_p if (_p and os.path.exists(_p) and _age <= IMG_FRESH_S) else None))
        imgs_by_topic = _out
    return {"ok": True, "file": path, "age_s": round(age, 2), "fresh": age <= STALE_S,
            "pubs": pubs, "image": (img or None), "images_by_topic": imgs_by_topic,
            "tcp": r.get("tcp"), "tcp_quat": r.get("tcp_quat"), "tcp_frame": r.get("tcp_frame"),
            "jnames": r.get("jnames") or [], "jpos": r.get("jpos"), "jvel": r.get("jvel"),
            "gripper": r.get("gripper"), "ft": r.get("ft"), "z7": r.get("z7"),
            "robot_status": r.get("robot_status"), "geom": r.get("geom"),
            "stage_prod": r.get("prod_stage"), "gaps": gaps}


def probe():
    """数据源体检 (画布节点日志用): 文件/新鲜度/采集频率/通道可用性"""
    p = read_latest()
    st = {}
    try:
        st = json.load(open(os.path.join(REMOTE_DIR, "status.json")))
    except Exception:
        pass
    recv = st.get("recv") or {}
    return {"file": p.get("file"), "fresh": p.get("fresh"), "age_s": p.get("age_s"),
            "samples": st.get("samples"), "recv": recv, "gaps": p.get("gaps", {}),
            "zero_uplink_selfreport": st.get("self_publishers"),
            "bypass_dir": BYPASS_DIR, "bypass_file": _latest_file(BYPASS_DIR, "bypass_")}


def read_bypass_status():
    """旁路运行器心跳: 当前阶段/残差/接触概率/六层调用/零下行自证/缺口"""
    try:
        d = json.load(open(os.path.join(BYPASS_DIR, "status.json")))
    except Exception as e:
        return {"ok": False, "reason": f"无旁路心跳 ({BYPASS_DIR}/status.json): {type(e).__name__}"}
    d["ok"] = True
    age = None
    try:
        age = round(time.time() - os.path.getmtime(os.path.join(BYPASS_DIR, "status.json")), 1)
    except Exception:
        pass
    d["age_s"] = age
    d["fresh"] = (age is not None and age <= max(STALE_S * 3, 10.0))
    return d


def tail_bypass(n=240):
    """旁路逐帧记录最近 n 条 (画残差/接触概率曲线)"""
    return _tail_json(_latest_file(BYPASS_DIR, "bypass_"), n=n, chunk=262144)


# ── 真机逐帧历史 (TCP xyz + 六维力) → 波形显示 ────────────────────────────────
# state_*.jsonl 每行 ~5KB (含图像元数据), 整段重读太贵 → 模块级增量缓存: 只吃新增字节。
# 跨天/轮转/截断自动重接 (旧文件丢了就重开新文件), 与 ss_remote_tap 的 Tailer 同一思路。
_STATE_CACHE = {"path": None, "off": 0, "rows": []}


def tail_state(n=300, max_bytes=768 * 1024, seek_back=2 * 1024 * 1024):
    """真机感知逐帧记录最近 n 条 (含 t / tcp[3] / ft[6]) —— 供波形显示, 增量只读新增字节"""
    path = _latest_file(REMOTE_DIR, "state_")
    if not path:
        return []
    c = _STATE_CACHE
    try:
        size = os.path.getsize(path)
    except Exception:
        return c["rows"]
    if c["path"] != path or size < c["off"]:          # 换文件 / 被轮转截断 → 重开
        c["path"], c["off"], c["rows"] = path, max(0, size - seek_back), []
    if size <= c["off"]:
        return c["rows"]
    try:
        with open(path, "rb") as f:
            f.seek(c["off"])
            raw = f.read(max_bytes)
    except Exception:
        return c["rows"]
    if not raw:
        return c["rows"]
    cut = raw.rfind(b"\n")                             # 字节级定位: 只消费到最后一个完整行
    if cut < 0:                                        # 还没有完整行 → 原地等下一拍
        return c["rows"]
    c["off"] += cut + 1
    for ln in raw[:cut].decode("utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            c["rows"].append(json.loads(ln))
        except Exception:                              # 半行/坏行 → 跳过, 不猜
            continue
    if len(c["rows"]) > n:
        c["rows"] = c["rows"][-n:]
    return c["rows"]


if __name__ == "__main__":       # 自检 (命令行直接跑)
    print(json.dumps(probe(), ensure_ascii=False, indent=1))
    print(json.dumps(read_latest(), ensure_ascii=False, indent=1)[:900])
    s = read_bypass_status()
    print(json.dumps({k: s.get(k) for k in ("ok", "steps", "stage_hist", "last", "zero_downlink",
                                            "gap", "age_s", "fresh")}, ensure_ascii=False, indent=1))
    rows = tail_bypass(5)
    print("tail:", len(rows), json.dumps(rows[-1], ensure_ascii=False)[:300] if rows else "空")
