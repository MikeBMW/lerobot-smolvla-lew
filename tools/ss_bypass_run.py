#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 状态空间 · 旁路(影子)运行器 — 4060 侧, 吃真机感知, 绝不接管

老倪 2026-09-16: 「状态空间，开始旁路运行」(红线: Orin 零程序, 只转发感知信号)

位置与铁律:
  · 跑在 **4060 本机** (~/lerobot-venv), Orin 侧不装不跑任何东西
  · **零下行**: 本进程不 import rclpy, 不建任何 socket, 不发布/不调用任何 Orin 侧话题或服务
    (输入 = ss_remote_tap 采集到的真机感知 jsonl; 输出 = 本机 jsonl + 心跳, 仅记录)
  · 每次采样真调 **状态空间六层真实源码**:
      perception.fuse_sensors → 43D obs
      dynamics.PriorDynamicsPredictor.predict → 先验
      cognition.state_correction → 校正 + 残差 ; contact_probability → 接触概率
      cognition.ActionModulator.advance → 阶段推进 (证据驱动)
      cognition.ActionModulator.decide  → 否决/融合/按阶段限速 → would-be 动作
      safety.saturate → 物理限幅
    模型侧 u_ff = 本机推理服务对真机帧的真输出 (与 proposal_*.jsonl 对齐, 记录 input_map)
  · 诚实缺口 (显式标注, 不编造): 现场几何未示教 ⇒ 手-光模块/孔口距离、插入深度等**几何证据不可得**
    → 状态机只能停在「接近」(记住 reason), z7 保持 null; ft/gripper 无发布者时同样记 gap 而不是填 0。

用法:
  ~/lerobot-venv/bin/python tools/ss_bypass_run.py                    # 常驻旁路
  ~/lerobot-venv/bin/python tools/ss_bypass_run.py --duration 60      # 自检 60s 退出
"""
import argparse
import importlib.util
import json
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SS_DIR = os.path.join(REPO, "src", "lerobot", "policies", "left_right", "state_space")
IN_DIR = os.environ.get("SS_REMOTE_DIR", os.path.expanduser("~/zmax_ss_remote"))
OUT_DIR = os.environ.get("SS_BYPASS_DIR", os.path.expanduser("~/zmax_data/ss_bypass"))
K_OBS = 1.0


def load_mod(name):
    """按文件路径加载六层真实源码 (不经包 __init__, 保证与引擎同源)"""
    path = os.path.join(SS_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"ss_{name}", path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"ss_{name}"] = m
    spec.loader.exec_module(m)
    return m


class Tailer:
    """跟随一个持续追加的 jsonl (从当前末尾开始), 逐行产出 dict"""

    def __init__(self, path):
        self.path = path
        self.fh = None
        self.ino = None

    def _open(self):
        self.fh = open(self.path, "r", encoding="utf-8", errors="replace")
        self.fh.seek(0, os.SEEK_END)
        self.ino = os.stat(self.path).st_ino

    def poll(self):
        if self.fh is None or not os.path.exists(self.path) or os.stat(self.path).st_ino != self.ino:
            self._open()
        out = []
        for ln in self.fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=0, help="0=常驻")
    ap.add_argument("--rate", type=float, default=10.0, help="旁路步频上限 (与采集同频)")
    ap.add_argument("--gain", type=float, default=1.0, help="接触概率增益")
    ap.add_argument("--K", type=float, default=0.5, help="状态校正卡尔曼增益")
    a = ap.parse_args()

    perception = load_mod("perception")
    cognition = load_mod("cognition")
    dynamics = load_mod("dynamics")
    safety = load_mod("safety")

    os.makedirs(OUT_DIR, exist_ok=True)
    day = time.strftime("%Y%m%d")
    day_in = day
    fout = open(os.path.join(OUT_DIR, f"bypass_{day}.jsonl"), "a", buffering=1)
    T_st = Tailer(os.path.join(IN_DIR, f"state_{day_in}.jsonl"))
    T_pr = Tailer(os.path.join(IN_DIR, f"proposal_{day_in}.jsonl"))

    prior_dyn = dynamics.PriorDynamicsPredictor(A=1.0, B=0.02, use_wm=False)   # 与引擎同参; 先验走线性 (引擎实际路径)
    mod = cognition.ActionModulator()          # 引擎默认参数 (与 L2/L3 档同源)

    props = {}                                  # t(取整到 0.1s) → 最近一条模型建议 (窗口内最近邻匹配)
    st = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"), "samples": 0, "steps": 0,
        "layer_calls": {"perception": 0, "dynamics": 0, "cognition": 0, "action_mod": 0, "safety": 0},
        "stage_hist": {}, "veto": 0, "anomaly": 0, "err": 0, "gap": {},
        "last": None, "zero_downlink": {"rclpy_imported": False, "publishers": 0,
                                        "sockets_opened": 0, "writes_to_orin": 0},
        "input_maps": {}, "u_ff_norm": [], "note": "旁路(影子): 只记录不接管; 几何未示教 ⇒ 几何类证据不可得",
    }

    def bump(k, n=1):
        st["gap"][k] = st["gap"].get(k, 0) + n

    def heartbeat():
        json.dump(st, open(os.path.join(OUT_DIR, "status.json"), "w"), ensure_ascii=False, indent=1)

    t_start = time.time()
    last_step = 0.0
    print(f"[bypass] 状态空间旁路启动 · 输入={IN_DIR} · 输出={OUT_DIR} · 零下行(rclpy={('rclpy' in sys.modules)})", flush=True)
    while True:
        if a.duration and time.time() - t_start >= a.duration:
            break
        for p in T_pr.poll():
            props[round(float(p.get("t", 0)), 1)] = p
            _pkeys = sorted(props)[-40:]
            for _k in [k for k in props if k not in _pkeys]:
                props.pop(_k, None)
        rows = T_st.poll()
        for r in rows:
            st["samples"] += 1
            now = time.time()
            if now - last_step < 1.0 / a.rate:
                continue
            last_step = now
            try:
                x = r.get("tcp")
                if x is None:
                    bump("缺 tcp_pose")
                    continue
                x = np.asarray(x, dtype=float)
                # 真机位移速率 (由相邻真实帧差分; 机器静止≈0, 产线一动立刻有值)
                _prev = st.get("_prev_x")
                _pt = st.get("_prev_t")
                _rt = float(r.get("t", 0))
                dx_real = (float(np.linalg.norm(x - np.asarray(_prev, dtype=float))) / max(1e-6, _rt - _pt)
                           if (_prev is not None and _pt is not None and _rt > _pt) else 0.0)
                st["_prev_x"], st["_prev_t"] = x.tolist(), _rt
                jv = r.get("jvel")
                if jv is None:
                    bump("缺关节速度(jvel)")
                    v = np.zeros(3)
                else:
                    v = np.asarray(jv[:3], dtype=float)
                grip = r.get("gripper")
                if grip is None:
                    bump("缺夹爪开度(gripper 无发布者)")
                ft = r.get("ft")
                if ft is None:
                    bump("缺六维力(force_torque 无发布者)")
                if r.get("z7") is None:
                    bump("缺 z7(现场几何未示教)")

                # ── ① 模型侧 u_ff: 本机推理服务对真机帧的真输出 (input_map 原样记录) ──
                _rt = float(r.get("t", 0))
                _cand = min(props, key=lambda k: abs(k - _rt)) if props else None
                pr = props.get(_cand) if (_cand is not None and abs(_cand - _rt) <= 0.25) else None
                u_ff = np.asarray(pr["action"], dtype=float)[:4] if (pr and pr.get("action")) else np.zeros(4)
                if pr and pr.get("input_map"):
                    st["input_maps"][pr["input_map"]] = st["input_maps"].get(pr["input_map"], 0) + 1
                else:
                    bump("无对齐的模型建议")

                # ── ① 感知层: 真实信号融合 (几何槽位缺失 → 显式记 gap, 不用假值冒充) ──
                vis39 = np.zeros(39)
                vis39[0:3] = x                                    # 手/末端位置 (真机 TCP)
                vis39[3] = float(grip) if grip is not None else 0.0
                vis39[4:7] = v                                    # 速度 (真机关节速度前 3 维)
                # vis39[7:10]=_pc 光模块位置 · [10:13]=goal 目标点 → 需现场几何, 保持 0 并记 gap
                tact4 = np.array([1.0 if (grip is not None and grip < 500.0) else 0.0,
                                  1.0 if (ft is not None and abs(ft[2]) > 0.5) else 0.0, 0.0, 0.0])
                obs43 = perception.fuse_sensors(vis39, ft, tact4, K_OBS)
                st["layer_calls"]["perception"] += 1

                # ── ② 动力学层: 先验预测 ──
                #   口径与引擎逐字一致 (state_space_sim_real.py:765/2770-2772):
                #     latent = [x(3), 0.0] · act4 = [u_prev[:3], 0.0] · dyn = PriorDynamicsPredictor(A=1.0, B=0.02)
                #     prior = A·latent + B·act4 = 位置保持 + 小步位移; 模型未提案时 act4=0 (记 gap)
                latent4 = np.concatenate([x, [0.0]])
                act4 = np.concatenate([u_ff[:3], [0.0]])
                z_k = latent4.copy()
                prior = np.asarray(prior_dyn.predict(latent4, act4), dtype=float)
                if prior.shape != z_k.shape:
                    bump("先验维度不一致(已对齐)")
                    prior = z_k.copy()
                st["layer_calls"]["dynamics"] += 1

                # ── ③ 认知层: 状态校正 + 残差 + 接触概率 ──
                corrected, residual = cognition.state_correction(prior, z_k, K=a.K)
                r_scalar = float(np.linalg.norm(np.asarray(residual, dtype=float)))
                contact_p = float(cognition.contact_probability(r_scalar, gain=a.gain))
                st["layer_calls"]["cognition"] += 1

                # ── ⑤ 动作调制器: 阶段推进(证据驱动) + 否决/融合/按阶段限速 ──
                #    几何类证据 (手-光模块距离/插入深度/孔口高度) 未示教 → 传 None (不编造), 状态机据此停在「接近」
                stage = mod.advance(contact_p=contact_p, dist_h=None, gripper=grip, depth=None,
                                    d_xy=None, lifted=None, at_grasp_pose=False, grasp_force=None)
                u, tag = mod.decide(u_ff, np.zeros(4), contact_p, r_scalar)
                g_cmd = mod.gripper_cmd()
                st["layer_calls"]["action_mod"] += 1

                # ── ⑥ 安全层: 物理限幅 (旁路只算不下发) ──
                u_sat = safety.saturate(u)
                st["layer_calls"]["safety"] += 1

                if "否决" in tag or "异常" in tag:
                    st["veto"] += 1
                    if "异常" in tag:
                        st["anomaly"] += 1
                st["stage_hist"][stage] = st["stage_hist"].get(stage, 0) + 1
                st["steps"] += 1
                un = float(np.linalg.norm(u_sat[:3]))
                st["u_ff_norm"].append(round(un, 5))
                st["u_ff_norm"] = st["u_ff_norm"][-200:]
                st["last"] = {"t": r.get("t"), "x": [round(float(q), 5) for q in x],
                              "dx_real": round(dx_real, 5),
                              "v_norm": round(float(np.linalg.norm(v)), 4),
                              "residual": round(r_scalar, 5), "contact_p": round(contact_p, 4),
                              "stage": stage, "decide": tag, "gripper_cmd": g_cmd,
                              "u_ff": [round(float(q), 4) for q in u_ff],
                              "u_sat": [round(float(q), 4) for q in u_sat],
                              "input_map": pr.get("input_map") if pr else None}

                fout.write(json.dumps({
                    "t": r.get("t"), "src": "ss_bypass", "stage": stage, "decide": tag,
                    "contact_p": round(contact_p, 4), "residual": round(r_scalar, 5),
                    "corrected": [round(float(q), 6) for q in corrected],
                    "prior": [round(float(q), 6) for q in prior],
                    "u_ff": [round(float(q), 4) for q in u_ff],
                    "u_sat": [round(float(q), 4) for q in u_sat], "gripper_cmd": g_cmd,
                    "x_real": [round(float(q), 5) for q in x], "dx_real": round(dx_real, 5),
                    "input_map": (pr.get("input_map") if pr else None),
                    "gaps": {k: v for k, v in (("gripper", grip is None), ("ft", ft is None),
                                               ("geometry", r.get("z7") is None)) if v},
                    "executed": False, "scope": "bypass-readonly",
                }, ensure_ascii=False) + "\n")
            except Exception as e:          # 单步异常不许静默吞掉 (静默降级 = 白做)
                st["err"] += 1
                bump(f"步内异常:{type(e).__name__}")
                if st["err"] <= 3:
                    import traceback
                    traceback.print_exc()
            if st["steps"] and st["steps"] % 50 == 0:
                st["zero_downlink"]["rclpy_imported"] = "rclpy" in sys.modules
                heartbeat()
                print(f"[bypass] {st['steps']} 步 · 阶段={st['last']['stage']} · 残差={st['last']['residual']} "
                      f"· 接触p={st['last']['contact_p']} · u_sat范数={round(np.linalg.norm(st['last']['u_sat'][:3]),4)} "
                      f"· 否决={st['veto']} · rclpy={'rclpy' in sys.modules}", flush=True)
        time.sleep(0.05)

    st["stopped"] = time.strftime("%Y-%m-%d %H:%M:%S")
    heartbeat()
    print(f"[bypass] 结束: 采样 {st['samples']} · 旁路步 {st['steps']} · 阶段分布 {st['stage_hist']} · "
          f"缺口 {st['gap']} · 零下行 {st['zero_downlink']}", flush=True)


if __name__ == "__main__":
    main()
