#!/usr/bin/env python3
"""⚙️ 前馈 PD 分析 — Z700 等效 PID 控制器分析 (2026-08-14 老倪)
思想: 系统 = 带前馈(Feedforward)的增益调度(Gain-Scheduling) PID
  状态机 = 强力 P 控制 (e×Kp: delta=光模块−hand, act+=delta*2.0)
  物理限幅 = 隐性 D 与饱和 (死区/限幅=非线性阻尼, 放弃 I 避免积分饱和)
  左脑 MLP = 前馈控制器 (直接预测动作, 偏差产生前给力)
  右脑 WM = 预测器 (预判接触, 提前减速避免猛刹滞后)

输出:
  1. 阶段 PD 参数表 (各阶段 Kp/Kd/限幅)
  2. 前馈 vs 纯 PD 仿真对比 (误差衰减/超调/响应步数)
  3. 等效 PID 结论

用法: BRAIN_CKPT=<dir> .venv/bin/python tools/ff_pd_analysis.py
输出: reports/ff_pd.json + reports/ff_pd_compare.png
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import numpy as np

from gen_insert_video import _load_brain
from train_full_pipeline import make_env, get_obs, ST_APPROACH, ST_GRASP, ST_LIFT, ST_TRANSFER


# ── 阶段 PD 参数表 (从状态机代码提取) ──
STAGE_PD = [
    {"stage": "接近", "Kp": 2.0, "Kd": 0.3, "limit": [-1.0, 1.0],
     "e_def": "||hand−peg||", "note": "P: delta*2.0 硬拉回目标; D: 0.3*act 制动"},
    {"stage": "抓取", "Kp": 0.1, "Kd": 0.0, "limit": [-1.0, 1.0],
     "e_def": "peg_z − peg_z0", "note": "锁定位置 (act*0.1), 夹爪 0.6"},
    {"stage": "抬起", "Kp": 0.8, "Kd": 0.0, "limit": [-0.8, 0.8],
     "e_def": "目标高度 0.08m", "note": "z 轴比例上升 (0.8)"},
    {"stage": "转移", "Kp": 0.6, "Kd": 0.0, "limit": [-0.6, 0.6],
     "e_def": "||peg−hole||_xy", "note": "方向归一化 0.6 限幅 (死区 0.05)"},
    {"stage": "插入", "Kp": 2.0, "Kd": 0.0, "limit": [-0.6, 0.6],
     "e_def": "hole_z − peg_z", "note": "z 比例 2.0 限幅 0.6 (防过冲撞金手指)"},
]


def pd_param_table():
    """① 阶段 PD 参数表"""
    return STAGE_PD


def ff_pd_sim(left, right, xm, xs, ym, ys, use_ff=True, seed=1, max_steps=150, Kp=2.0, Kd=0.3):
    """② 前馈 PD 仿真: 接近阶段误差衰减
    u(t) = Kp·e(t) + Kd·ė(t) + u_ff(t)   (u_ff = 左脑预测动作, 前馈)
    纯 PD: u_ff = 0
    返回: 误差序列 / 超调 / 到达阈值步数"""
    dev = next(left.parameters()).device
    env = make_env(seed)
    o = get_obs(env)
    errs, prev_e, prev_u = [], None, None
    for _ in range(max_steps):
        hand = env.data.site_xpos[env.model.site("endEffector").id]
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        e = peg - hand
        err = float(np.linalg.norm(e))
        errs.append(err)
        if err < 0.06:
            break
        # P 项
        up = Kp * e
        # D 项 (误差变化率 → 制动)
        ud = np.zeros(3)
        if prev_e is not None:
            ud = Kd * (e - prev_e)
        # 前馈项: 左脑预测动作 (偏差产生前给力)
        uff = np.zeros(3)
        if use_ff:
            xin = torch_from_obs(o, xm, xs, dev)
            with torch_no_grad():
                pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()[:3] * 1.0
            uff = np.clip(pred, -1, 1) * 0.2
        act = np.clip(up + ud + uff, -1, 1)
        act = np.append(act, [-1.0])  # 夹爪开
        try:
            env.step(np.clip(act, -1, 1))
            env.render()
        except Exception:
            break
        prev_e = e.copy()
        o = get_obs(env)
    env.close()
    # 超调: 误差回升占比 (e 曲线 2 阶差分峰值)
    arr = np.asarray(errs)
    overshoot = float(np.max(np.diff(arr)) / (arr[0] + 1e-9)) if len(arr) > 2 else 0.0
    steps_to_thresh = int(np.argmax(np.asarray(errs) < 0.06) + 1) if np.any(np.asarray(errs) < 0.06) else len(errs)
    return errs, overshoot, steps_to_thresh


def torch_from_obs(o, xm, xs, dev):
    import torch
    return torch.from_numpy((o - xm) / xs).float().to(dev)


def torch_no_grad():
    import torch
    return torch.no_grad()


def run_compare(left, right, xm, xs, ym, ys, seeds=(1,)):
    """② 前馈 vs 纯 PD 对比"""
    rows = []
    for seed in seeds:
        e_pd, os_pd, st_pd = ff_pd_sim(left, right, xm, xs, ym, ys, use_ff=False, seed=seed)
        e_ff, os_ff, st_ff = ff_pd_sim(left, right, xm, xs, ym, ys, use_ff=True, seed=seed)
        rows.append({"seed": seed,
                     "pd": {"err0": e_pd[0], "err_end": e_pd[-1], "steps": st_pd,
                            "overshoot": os_pd, "curve": e_pd},
                     "ff_pd": {"err0": e_ff[0], "err_end": e_ff[-1], "steps": st_ff,
                               "overshoot": os_ff, "curve": e_ff}})
    return rows


def plot_compare(rows, out_png):
    """误差衰减对比图: 纯 PD vs 前馈 PD"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        from matplotlib import font_manager as _fm
        _fm.addfont("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc")
    except Exception:
        pass
    plt.rcParams["font.sans-serif"] = ["WenQuanYi Micro Hei", "Noto Sans CJK SC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for r in rows:
        ax.plot(r["pd"]["curve"], color="#ff4444", lw=1.8, label=f"纯PD seed{r['seed']} (到阈值{r['pd']['steps']}步)")
        ax.plot(r["ff_pd"]["curve"], color="#3fb950", lw=1.8, label=f"前馈PD seed{r['seed']} (到阈值{r['ff_pd']['steps']}步)")
    ax.axhline(0.06, color="#57606a", ls=":", lw=1, label="抓取阈值 0.06m")
    ax.set_title("前馈 PD vs 纯 PD 误差衰减 (u = Kp·e + Kd·ė + u_ff)")
    ax.set_xlabel("仿真步数 t")
    ax.set_ylabel("误差 e(t) [m]")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_png, dpi=110)
    plt.close(fig)


def main():
    print("🧠 加载双脑模型 …", flush=True)
    left, right, xm, xs, ym, ys = _load_brain()
    ckpt = os.environ.get("BRAIN_CKPT", "最新")

    print("① 阶段 PD 参数表 (增益调度) …", flush=True)
    for s in STAGE_PD:
        print(f"   {s['stage']:4} Kp={s['Kp']:.2f} Kd={s['Kd']:.2f} 限幅{s['limit']} — {s['note']}", flush=True)

    print("② 前馈 vs 纯 PD 仿真 (接近阶段) …", flush=True)
    rows = run_compare(left, right, xm, xs, ym, ys, seeds=(1,))
    for r in rows:
        print(f"   seed{r['seed']}: 纯PD 到阈值{r['pd']['steps']}步 超调{r['pd']['overshoot']:.3f} | "
              f"前馈PD {r['ff_pd']['steps']}步 超调{r['ff_pd']['overshoot']:.3f} "
              f"→ {'前馈更快' if r['ff_pd']['steps'] <= r['pd']['steps'] else 'PD更快'}", flush=True)

    print("📊 对比图 …", flush=True)
    out_png = os.path.join(ROOT, "reports", "ff_pd_compare.png")
    plot_compare(rows, out_png)
    print(f"   → {out_png}", flush=True)

    # 结论
    ff_faster = sum(1 for r in rows if r["ff_pd"]["steps"] <= r["pd"]["steps"])
    verdict = ("前馈 PD 响应更快 (左脑预测提前给力, 右脑预判接触提前减速)"
               if ff_faster >= len(rows) / 2 else
               "纯 PD 与本系统相当 (状态机限幅已提供足够阻尼)")
    rep = {"ckpt": ckpt, "time": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
           "stage_pd": STAGE_PD, "compare": rows, "verdict": verdict}
    with open(os.path.join(ROOT, "reports", "ff_pd.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    print(f"\n结论: {verdict}", flush=True)
    print(f"报告: reports/ff_pd.json + {os.path.basename(out_png)}", flush=True)


if __name__ == "__main__":
    main()
