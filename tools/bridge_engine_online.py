#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在线桥接: 引擎真轨迹 -> 统一主干 -> 预测, 对比真值与平凡基线 (跨 venv 两阶段)

阶段1 (gui-venv311, 有 mujoco/引擎):  PHASE=collect -> 写 /tmp/bridge_engine_smpl.npz
阶段2 (INTACT venv, 有 torch):        PHASE=eval    -> 读 npz, 跑统一模型, 报 MAE
"""
import os
import sys
import numpy as np

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, ROOT + "/src")
sys.path.insert(0, ROOT + "/tools/gui")
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("LOCAL_DATASET_DIR", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")

NPZ = "/tmp/bridge_engine_smpl.npz"
CKPT = "/home/ubuntu/stable-wm-cache/checkpoints/backbone_cont/unified.pt"
IMGSZ, CHUNK = 224, 7


def collect(n_traj, steps):
    from state_space_sim_real import RealStateSpaceSim
    rec_obs, rec_px, rec_act = [], [], []
    for k in range(n_traj):
        sim = RealStateSpaceSim(seed=500 + k, vision=True, log=lambda *a: None)
        rec_hook = []          # ★ 每步 fuse_sensors 调 1 次 → env 原生 obs 序列 (与步对齐)
        orig = sim.perception.fuse_sensors

        def patched(visual39, force, tactile4, _s=sim, _r=rec_hook, _o=orig):
            _r.append(np.asarray(_s.env._get_obs(), dtype=np.float64).ravel()[:39].copy())
            return _o(visual39, force, tactile4)

        sim.perception.fuse_sensors = patched
        try:
            tr = sim.run(max_steps=steps)
        except Exception as e:
            print(f"  轨迹{k} 失败: {str(e)[:70]}", flush=True)
            continue
        n = len(tr["obs"])
        if len(rec_hook) < n:      # 长度不齐时补齐
            rec_hook += [rec_hook[-1] if rec_hook else np.zeros(39)] * (n - len(rec_hook))
        obs_l = [np.asarray(x, dtype=np.float32).ravel()[:39] for x in rec_hook[:n]]   # ★ env 原生
        act_l = [np.asarray(x, dtype=np.float32).ravel()[:4] for x in tr["u_sat_vec"]]
        n = len(obs_l)
        kf = list(sim._key_frames.values())
        blank = np.zeros((IMGSZ, IMGSZ, 3), np.uint8)
        for i in range(n):
            rec_obs.append(obs_l[i])
            rec_act.append(act_l[i])
            rec_px.append(np.asarray(kf[min(i * len(kf) // max(1, n), len(kf) - 1)]) if kf else blank)
        print(f"  轨迹{k}: {n} 步 · 关键帧{len(kf)} · env_obs_hook={len(rec_hook)}", flush=True)
    if not rec_obs:
        print("X 无样本")
        return 1
    np.savez_compressed(NPZ, O=np.stack(rec_obs), A=np.stack(rec_act), P=np.stack(rec_px))
    print(f"OK 样本已存 {NPZ} · {len(rec_obs)} 步")
    return 0


def evaluate():
    import torch
    import torch.nn.functional as F
    from transformers import AutoModel
    from joint_unified_backbone import Unified, MODEL

    full = AutoModel.from_pretrained(MODEL, dtype=torch.float32)
    net = Unified(full.vision_model, freeze=True)
    sd = torch.load(CKPT, map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "trunk.embeddings.patch_embedding.weight" not in sd and "model" in sd:
        sd = sd["model"]
    net.load_state_dict(sd, strict=True)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = net.eval().to(dev)

    d = np.load(NPZ)
    O, A, P = d["O"], d["A"], d["P"]
    N = len(O)
    print(f"在线样本: {N} 步 · obs{O.shape} act{A.shape} px{P.shape} · 像素非零率 {(P > 0).mean():.3f}")

    def to_img(px):
        x = torch.from_numpy(np.asarray(px)).float() / 255.0
        x = x.permute(0, 3, 1, 2)
        return F.interpolate(x, size=(IMGSZ, IMGSZ), mode="bilinear", align_corners=False)

    mu_o, mu_a = O.mean(0), A.mean(0)
    b_o = float(np.abs(O - mu_o).mean())
    b_a = float(np.abs(A - mu_a).mean())
    b_a0 = float(np.abs(A).mean())

    nxt = np.arange(1, N)
    jc = np.minimum(nxt[:, None] + np.arange(CHUNK)[None, :], N - 1)
    lo, la = [], []
    with torch.no_grad():
        for s in range(0, len(nxt), 64):
            ii = nxt[s:s + 64]
            out = net(to_img(P[ii]).to(dev), torch.from_numpy(O[ii]).to(dev),
                      torch.from_numpy(A[jc[s:s + 64]]).to(dev),
                      torch.zeros(len(ii), 13, device=dev))
            on = torch.from_numpy(O[np.minimum(ii + 1, N - 1)]).to(dev)
            lo.append(float((out["obs_hat"] - on).abs().mean()))
            la.append(float((out["u"] - torch.from_numpy(A[jc[s:s + 64]][:, :out["u"].shape[1], :]).to(dev)).abs().mean()))
    mo, ma = float(np.mean(lo)), float(np.mean(la))

    print("=" * 76)
    print("  在线(引擎真轨迹) vs 离线留出 vs 平凡基线")
    print("=" * 76)
    print(f"  L4认知预测 MAE : 在线 {mo:.4f} | 离线 0.008 | 基线 {b_o:.4f}  -> {'优' if mo < b_o else '差'}")
    print(f"  动作预测   MAE : 在线 {ma:.4f} | 离线 0.056 | 基线 {b_a:.4f} -> {'优' if ma < b_a else '差'}")
    return 0


def main():
    phase = os.environ.get("PHASE", "collect")
    if phase == "collect":
        return collect(int(os.environ.get("N_TRAJ", "4")), int(os.environ.get("STEPS", "200")))
    return evaluate()


if __name__ == "__main__":
    sys.exit(main())
