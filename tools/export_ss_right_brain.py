#!/usr/bin/env python3
"""export_ss_right_brain.py — 导出训练好的状态空间右脑 WorldModel 为 numpy npz
供 GUI (gui-venv311 无 torch) 用 numpy 推理加载。对齐 export_ss_left_brain.py。

右脑 RightBrainWM (modeling_left_right.py): obs(39 raw) + act(4 raw) → next_obs + contact
  - enc: Linear(43,256)+ReLU + Linear(256,256)+ReLU   (obs+act 拼接输入, raw 量纲)
  - pred_next: Linear(256,39)     next_obs 预测
  - contact_head: Linear(256,1) + sigmoid  (抓取时机, acc 1.00)
用法: ~/lerobot-venv/bin/python tools/export_ss_right_brain.py [ckpt_dir]
     默认从 reports/train_curve_state_space.json 读最新 ckpt (同左脑)。
"""
import os
import sys
import json
import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "models", "ss_right_brain.npz")


def resolve_ckpt():
    curve = os.path.join(ROOT, "reports", "train_curve_state_space.json")
    if os.path.exists(curve):
        d = json.load(open(curve, encoding="utf-8"))
        ckpt = d.get("ckpt")
        if ckpt:
            return os.path.join(ROOT, ckpt)
    return None


def main(ckpt_dir=None):
    ckpt_dir = ckpt_dir or resolve_ckpt()
    if not ckpt_dir:
        print("❌ 未找到训练模型 — 先训练或指定 ckpt 目录")
        return 1
    pt = os.path.join(ckpt_dir, "pretrained_model", "model.pt")
    if not os.path.isfile(pt):
        pt2 = os.path.join(ckpt_dir, "last", "pretrained_model", "model.pt")
        if os.path.isfile(pt2):
            pt = pt2
        else:
            print(f"❌ model.pt 不存在: {pt} 或 {pt2}")
            return 1
    sd = torch.load(pt, map_location="cpu", weights_only=False)
    right = sd["right"]
    # 键: enc.0.weight/bias, enc.2.weight/bias, pred_next.weight/bias, contact_head.weight/bias
    def _g(suffix):
        return {k: v.numpy().astype(np.float32) for k, v in right.items() if k.endswith(suffix)}
    W = {}
    for key, out_name in [("enc.0.weight", "W_e0"), ("enc.0.bias", "b_e0"),
                          ("enc.2.weight", "W_e1"), ("enc.2.bias", "b_e1"),
                          ("pred_next.weight", "W_p"), ("pred_next.bias", "b_p"),
                          ("contact_head.weight", "W_c"), ("contact_head.bias", "b_c")]:
        if key not in right:
            print(f"❌ right 缺键 {key} (实际: {list(right.keys())[:6]}...)")
            return 1
        W[out_name] = right[key].numpy().astype(np.float32)
    # 输入输出语义自测定 (pred_next 输出量纲): 喂训练数据对比 next 真值
    #   右脑输入 = raw obs + raw act (select_action 官方推理语义)
    import pandas as pd
    parquet = os.path.join(ROOT, "data", "ss_insert_lerobot", "data", "chunk-000", "file-000.parquet")
    df = pd.read_parquet(parquet)
    S = np.stack(df["observation.state"].values[:64]).astype(np.float32)
    A = np.stack(df["action"].values[:64]).astype(np.float32)
    nxt = S[1:]  # 真值 next (第 t 行 obs+act → t+1 obs)
    obs_in, act_in, tgt = S[:-1], A[:-1], nxt

    # torch 参考前向
    import sys as _sys
    _sys.path.insert(0, ROOT)
    _sys.path.insert(0, os.path.join(ROOT, "src"))
    from lerobot.policies.left_right.modeling_left_right import RightBrainWM
    rb = RightBrainWM(39, 4, 256)
    rb.load_state_dict(right)
    rb.eval()
    with torch.no_grad():
        pred_next_t, pred_cont_t = rb(torch.from_numpy(obs_in), torch.from_numpy(act_in))
    pred_next_t = pred_next_t.numpy()
    # 语义判断: raw 误差 vs 归一化反算误差
    stats_path = os.path.join(ROOT, "data", "ss_insert_lerobot", "meta", "stats.json")
    st = json.load(open(stats_path, encoding="utf-8"))
    m = np.array(st["observation.state"]["mean"], dtype=np.float32)
    s = np.array(st["observation.state"]["std"], dtype=np.float32) + 1e-8
    err_raw = float(np.abs(pred_next_t - tgt).mean())
    err_denorm = float(np.abs(pred_next_t * s + m - tgt).mean())
    next_raw = err_raw <= err_denorm   # True: 输出已是 raw 物理量纲
    print(f"  📐 pred_next 语义测定: raw 误差={err_raw:.5f} | 归一化反算误差={err_denorm:.5f} "
          f"→ {'RAW 量纲' if next_raw else '归一化量纲(需反归一化)'}")

    # 纯 numpy 自检 (验证导出正确性, 与 torch 逐位对照)
    def np_forward(o, a):
        x = np.concatenate([o, a], axis=-1).astype(np.float32)
        h = np.maximum(0.0, x @ W["W_e0"].T + W["b_e0"])
        h = np.maximum(0.0, h @ W["W_e1"].T + W["b_e1"])
        return h @ W["W_p"].T + W["b_p"], 1.0 / (1.0 + np.exp(-(h @ W["W_c"].T + W["b_c"])))
    pn, pc = np_forward(obs_in, act_in)
    mae_n = float(np.abs(pn - pred_next_t).max())
    mae_c = float(np.abs(pc - pred_cont_t.numpy()).max())
    print(f"  ✅ numpy vs torch 对照: next MAE={mae_n:.2e} contact MAE={mae_c:.2e}")
    if mae_n > 1e-3 or mae_c > 1e-3:
        print("❌ numpy 前向与 torch 不一致 — 中止导出")
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    np.savez(OUT, **W, next_raw=bool(next_raw),
             sm=m, ss=s,   # pred_next 反归一化用 (输出=归一化空间时: raw = pred*ss+sm)
             obs_dim=int(39), act_dim=int(4), contact_acc=1.00,
             contact_th=0.5)
    print(f"✅ 导出完成: {OUT}")
    print(f"   右脑: obs39+act4 → enc(256) → pred_next39 + contact(acc 1.00)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
