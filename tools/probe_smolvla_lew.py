#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v9 (smolvla_lew) 接入探针 — 在引擎真实运行轨迹上跑模型推理, 输出动作一致度
= "模型接入实际流程" 的第一步实证: 模型能看到真实观测并给出动作, 与专家动作差多少。
用法: MUJOCO_GL=egl gui-venv311/bin/python /tmp/v9_probe.py
"""
import os, sys, json
import numpy as np
os.environ.setdefault('MUJOCO_GL', 'egl')
os.environ.setdefault('DISPLAY', ':0')
R = '/home/ubuntu/lerobot-smolvla-lew'
sys.path.insert(0, R)
sys.path.insert(0, os.path.join(R, 'src'))
sys.path.insert(0, os.path.join(R, 'tools', 'gui'))
from PIL import Image
from state_space_sim_real import RealStateSpaceSim

# ── 1) 引擎真实轨迹采集 (图像 + obs39 + 专家动作) ──
frames = []
def sink(sim, act, o):
    try:
        img = np.asarray(Image.fromarray(np.asarray(sim.env.render())).resize((128, 128), Image.LANCZOS))
        frames.append((img, np.asarray(o[:39], dtype=np.float32), np.asarray(act, dtype=np.float32).ravel()[:4]))
    except Exception:
        pass

sim = RealStateSpaceSim(seed=104, vision=False, mode='insert', log=lambda *a: None)
sim._frame_sink = sink
tr = sim.run(max_steps=900)
done = bool(tr['done'][-1]) if tr.get('done') else False
print(f"① 引擎轨迹: {len(frames)} 帧 · done={done}")

# ── 2) 加载 v9 (030000) ──
import torch
from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
from lerobot.policies.smolvla_lew.configuration_smolvla_lew import SmolVLALewConfig
from lerobot.processor.pipeline import PolicyProcessorPipeline

CK = os.path.join(R, 'outputs/train/smolvla_lew_v8/checkpoints/030000/pretrained_model')
import tempfile, draccus
_cd = json.load(open(os.path.join(CK, 'config.json')))
_cd.pop('type', None)                      # 🐛 type 字段 draccus 不接受 (checkpoint 带, 配置类无)
_tf = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8')
json.dump(_cd, _tf, ensure_ascii=False)
_tf.close()
cfg = draccus.parse(SmolVLALewConfig, config_path=_tf.name)   # 正确反序列化 FeatureType 等嵌套
policy = SmolVLALewPolicy(cfg)
from safetensors.torch import load_file as _lf
_miss, _unexp = policy.load_state_dict(_lf(os.path.join(CK, 'model.safetensors')), strict=False)
dev = 'cuda' if torch.cuda.is_available() else 'cpu'
policy.to(dev).eval()
pre = PolicyProcessorPipeline.from_pretrained(CK, config_filename='policy_preprocessor.json')
post = PolicyProcessorPipeline.from_pretrained(CK, config_filename='policy_postprocessor.json')
print(f"② v9 加载: device={dev} | 权重 missing={len(_miss)} unexpected={len(_unexp)} | "
      f"输入={list(cfg.input_features.keys())} 动作={list(cfg.output_features.keys()) if cfg.output_features else None}")

# ── 3) 逐帧推理 (取前 40 帧 + 后 40 帧, 覆盖接近与插入) ──
N = len(frames)
idx = list(range(0, min(40, N))) + list(range(max(0, N - 40), N))


def _extract_action(x):
    """从 tensor / dict(EnvTransition) 里取出动作向量"""
    if isinstance(x, dict):
        for k in ('action', 'actions', 'Action'):
            if k in x:
                x = x[k]
                break
        else:
            for v in x.values():
                if hasattr(v, 'detach'):
                    x = v
                    break
    if hasattr(x, 'detach'):
        x = x.detach().cpu().numpy()
    return np.asarray(x, dtype=float).ravel()[:4]


maes, g_maes, samples = [], [], []
for i in idx:
    img, st, act = frames[i]
    bt = torch.from_numpy(img).permute(2, 0, 1).float().unsqueeze(0) / 255.0
    bs = torch.from_numpy(st).float().unsqueeze(0)
    batch = {"observation.image": bt, "observation.state": bs}
    try:
        pin = pre(batch)
        with torch.no_grad():
            pred = policy.select_action(pin)
        try:
            pred = post(pred) if not isinstance(pred, dict) else post(pred)
        except Exception:
            pass
        p = _extract_action(pred)
    except Exception as e:
        print(f"   推理失败 @frame{i}: {str(e)[:110]}")
        continue
    d = np.abs(p[:3] - act[:3])
    maes.append(float(np.mean(d)))
    g_maes.append(float(abs(p[3] - act[3])))
    if len(samples) < 3:
        samples.append((i, act.tolist(), p.tolist()))

print(f"③ 模型 vs 专家动作 (n={len(maes)} 帧):")
if maes:
    print(f"   xyz MAE 均值 {np.mean(maes):.4f} (最大 {np.max(maes):.4f})")
    print(f"   gripper MAE 均值 {np.mean(g_maes):.4f} (最大 {np.max(g_maes):.4f})")
    for i, a, p in samples:
        print(f"   帧{i}: 专家={np.round(a,3).tolist()} 模型={np.round(p,3).tolist()}")
json.dump({"frames": N, "done": done, "n_eval": len(maes),
           "xyz_mae": float(np.mean(maes)) if maes else None,
           "gripper_mae": float(np.mean(g_maes)) if g_maes else None},
          open('/tmp/v9_probe.json', 'w'), ensure_ascii=False, indent=1)
