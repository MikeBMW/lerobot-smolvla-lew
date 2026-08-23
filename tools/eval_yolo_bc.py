#!/usr/bin/env python3
"""YOLO 同构评估 — BC policy + 真实 YOLO 感知插拔评估 (2026-08-23 老倪)
完整同构闭环:
  训练: data/metaworld_peg (gen_metaworld_data --yolo 生成, YOLO检测→解算→39D带噪声state)
  评估: 真实 YOLO 权重 best.pt 检测 → 2D→3D 解算 → 替换 hand/peg/hole 段 → 39D state → BC policy
指标: ①peg抬起率(>5cm) ②插入率(peg距hole<5cm) ③平均距孔
用法:
  DISPLAY=:0 MUJOCO_GL=glfw gui-venv311/bin/python tools/eval_yolo_bc.py --epochs 400 --seeds 10
  (加 --skip-train 复用 outputs/bc_yolo/model.pt)
"""
import os, sys, json, argparse
import numpy as np
import torch
import torch.nn as nn

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
HIDDEN = 512
CKPT = os.path.join(ROOT, "outputs", "bc_yolo", "model.pt")

WEIGHTS_CANDS = [
    "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt",
    "runs/detect/outputs/yolo_peg/peg_full/weights/best.pt",
    "outputs/yolo_peg/peg_v1/weights/best.pt",
]


class BCMLP(nn.Module):
    def __init__(self, obs_dim=39, act_dim=4, hidden=HIDDEN):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, act_dim))

    def forward(self, x):
        return self.net(x)


def load_stats():
    s = json.load(open(os.path.join(ROOT, "data", "metaworld_peg", "meta", "stats.json")))
    sm = np.array(s["observation.state"]["mean"], dtype=np.float32)
    ss = np.array(s["observation.state"]["std"], dtype=np.float32) + 1e-6
    am = np.array(s["action"]["mean"], dtype=np.float32)
    asd = np.array(s["action"]["std"], dtype=np.float32) + 1e-6
    return sm, ss, am, asd


def train_bc(epochs=400, lr=1e-3):
    import pandas as pd
    df = pd.read_parquet(os.path.join(ROOT, "data", "metaworld_peg", "data",
                                      "chunk-000", "file-000.parquet"))
    X = np.stack(df["observation.state"].values).astype(np.float32)   # (N,39)
    Y = np.stack(df["action"].values).astype(np.float32)              # (N,4)
    sm, ss, am, asd = load_stats()
    Xn = (X - sm) / ss
    Yn = (Y - am) / asd
    Xt = torch.from_numpy(Xn).to(DEVICE)
    Yt = torch.from_numpy(Yn).to(DEVICE)
    print(f"[train] 数据 {Xt.shape[0]} 帧 (state 39D→action 4D), {X.shape[0]//180} episodes, device={DEVICE}")
    model = BCMLP().to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    mse = nn.MSELoss()
    model.train()
    for ep in range(epochs):
        opt.zero_grad()
        pred = model(Xt)
        loss = mse(pred, Yt)
        loss.backward()
        opt.step()
        if (ep + 1) % 50 == 0 or ep == 0:
            print(f"  [train] epoch {ep+1}/{epochs} loss={loss.item():.6f}")
    model.eval()
    os.makedirs(os.path.dirname(CKPT), exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "stats": {"s_mean": sm, "s_std": ss,
                                                             "a_mean": am, "a_std": asd}}, CKPT)
    print(f"[train] 已存权重: {CKPT}")
    return model


def build_aligner():
    import yolo_state_aligner
    WEIGHTS = next((c for c in WEIGHTS_CANDS if os.path.isfile(os.path.join(ROOT, c))), None)
    if not WEIGHTS:
        print("⚠️ YOLO 权重未找到, 无法评估")
        return None, None
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env0 = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env0._freeze_rand_vec = False
    env0.set_task(mt.train_tasks[0])
    env0.reset(seed=0)
    return yolo_state_aligner.YoloStateAligner(WEIGHTS, env0), WEIGHTS


def run_episode(model, sm, ss, am, asd, aligner, seed, steps=200):
    """单次插拔: 真实 YOLO 检测→解算→state→BC policy→env.step, 返回是否抬起+插入"""
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3", seed=seed)
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=seed)
    peg_z0 = env.data.site_xpos[env.model.site("pegGrasp").id][2]
    hole = env.data.site_xpos[env.model.site("hole").id]
    lifted = False
    det_hist = []
    for i in range(steps):
        peg = env.data.site_xpos[env.model.site("pegGrasp").id]
        if peg[2] - peg_z0 > 0.05:
            lifted = True
        st_raw = np.asarray(obs, dtype=np.float32)[:39]
        # 真实 YOLO 检测 → 2D→3D 解算 → 替换 hand/peg/hole 段 (与训练 gen_metaworld_data --yolo 同构)
        det3d = aligner.detect_3d(np.asarray(env.render()))
        st = aligner.align(st_raw, det3d).astype(np.float32)[:39]
        det_hist.append(len(det3d))
        st_n = (st - sm) / ss
        with torch.no_grad():
            act = model(torch.from_numpy(st_n).float().to(DEVICE).unsqueeze(0)).cpu().numpy().ravel()
        act = act * asd + am          # 反归一化 (训练管道)
        act = np.clip(act, -1.0, 1.0)
        obs, _, term, trunc, _ = env.step(act)
        if term or trunc:
            break
    peg_final = env.data.site_xpos[env.model.site("pegGrasp").id]
    dist_hole = float(np.linalg.norm(peg_final - hole))
    inserted = lifted and dist_hole < 0.05
    return {"lifted": lifted, "inserted": inserted, "dist_hole": round(dist_hole, 3),
            "peg_rise": round(float(peg_final[2] - peg_z0), 3),
            "avg_det_per_frame": round(float(np.mean(det_hist)), 2) if det_hist else 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=400)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--skip-train", action="store_true", help="复用 outputs/bc_yolo/model.pt")
    args = ap.parse_args()

    print("=" * 60)
    print("🔬 YOLO 同构插拔评估 · BC policy · 真实 YOLO 感知")
    print("=" * 60)
    sm, ss, am, asd = load_stats()
    if args.skip_train and os.path.isfile(CKPT):
        ck = torch.load(CKPT, map_location=DEVICE)
        model = BCMLP().to(DEVICE)
        model.load_state_dict(ck["state_dict"])
        model.eval()
        print(f"[train] 复用已训练权重: {CKPT}")
    else:
        model = train_bc(epochs=args.epochs)

    aligner, weights = build_aligner()
    if aligner is None:
        print("❌ 无法构建 YOLO aligner, 退出")
        return
    print(f"[eval] YOLO 权重: {weights}")

    lifts = ins = 0
    dists, rises, dets = [], [], []
    for seed in range(args.seeds):
        r = run_episode(model, sm, ss, am, asd, aligner, seed, steps=args.steps)
        lifts += int(r["lifted"]); ins += int(r["inserted"])
        dists.append(r["dist_hole"]); rises.append(r["peg_rise"]); dets.append(r["avg_det_per_frame"])
        print(f"  seed={seed:2d}  抬起={'✅' if r['lifted'] else '❌'}  插入={'✅' if r['inserted'] else '❌'}  "
              f"距孔={r['dist_hole']:.3f}m  peg升高={r['peg_rise']:+.3f}m  每帧检出={r['avg_det_per_frame']}类")

    results = {
        "policy": "bc_yolo", "seeds": args.seeds, "steps": args.steps,
        "lift_rate": lifts / args.seeds,
        "insert_rate": ins / args.seeds,
        "avg_dist_hole": round(float(np.mean(dists)), 3),
        "avg_peg_rise": round(float(np.mean(rises)), 3),
        "avg_det_per_frame": round(float(np.mean(dets)), 2),
    }
    print("-" * 60)
    print(f"  抓取率: {results['lift_rate']:.0%}  插入率: {results['insert_rate']:.0%}  "
          f"平均距孔: {results['avg_dist_hole']:.3f}m  peg平均升高: {results['avg_peg_rise']:+.3f}m")
    print(f"  每帧平均检出 {results['avg_det_per_frame']} 类 (YOLO 真推理)")
    out = os.path.join(ROOT, "reports", "eval_yolo_bc.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(results, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"✅ 结果已存: {out}")


if __name__ == "__main__":
    main()
