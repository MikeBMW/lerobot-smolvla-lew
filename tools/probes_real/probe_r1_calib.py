#!/usr/bin/env python3
"""R1 定标探针: YOLO hand/peg/hole 3D ↔ metaworld 物理锚对应关系
夹爪走 5 个关键位形, 每处: 真值锚 (obs hand / endEffector site / claw geom / 销 / 孔)
vs YOLO detect_3d 输出. 回答: R1 控制锚该用 YOLO 的哪个量、偏差多大、是否稳定.
用法: gui-venv311/bin/python tools/probes_real/probe_r1_calib.py
"""
import os, sys, time
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                "src", "lerobot", "policies", "yolo_3d"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "gui"))
import yolo_state_aligner
import metaworld as _mt

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
W_DET = os.path.join(REPO, "runs", "detect", "outputs", "yolo_peg", "peg_v1", "weights", "best.pt")
W_DEP = os.path.join(REPO, "outputs", "yolo_peg_depth", "peg_depth_v1-2", "weights", "best.pt")

mt = _mt.MT1("peg-insert-side-v3")
env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
env.set_task(mt.train_tasks[0])
env.reset(seed=0)
env._freeze_rand_vec = True
m, d = env.model, env.data
S = {n: m.site(n).id for n in ["endEffector", "leftEndEffector", "rightEndEffector",
                               "pegGrasp", "pegHead", "hole", "goal"]}
def SP(n): return d.site_xpos[S[n]].copy()
def GP(n): return d.geom_xpos[m.geom(n).id].copy()

print(f"加载 YOLO 检测: {os.path.basename(W_DET)}", flush=True)
t0 = time.time()
aligner = yolo_state_aligner.YoloStateAligner(W_DET, env, depth_weights=W_DEP)
print(f"加载完成 {time.time()-t0:.0f}s", flush=True)

def anchors(label):
    o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
    print(f"--- {label} ---", flush=True)
    print(f"  obs hand(claw)={np.round(o[0:3],4)}", flush=True)
    print(f"  site endEffector={np.round(SP('endEffector'),4)}", flush=True)
    print(f"  site 指L/R       ={np.round(SP('leftEndEffector'),4)} / {np.round(SP('rightEndEffector'),4)}", flush=True)
    print(f"  obs peg          ={np.round(o[4:7],4)}  site pegGrasp={np.round(SP('pegGrasp'),4)}", flush=True)
    print(f"  site hole        ={np.round(SP('hole'),4)}  site goal={np.round(SP('goal'),4)}", flush=True)

def yolo_shot():
    img = env.render()
    det3d = aligner.detect_3d(img)
    out = {}
    for k in ("hand", "peg", "hole"):
        out[k] = np.round(det3d[k], 4) if k in det3d else None
    print(f"  YOLO det3d: hand={out['hand']} peg={out['peg']} hole={out['hole']}", flush=True)
    return out

# 位形 1: 初始 (不动)
anchors("位形1 初始")
yolo_shot()

def move_hand_to(tgt_xyz, steps=90, approach_z=None):
    """把 obs hand 移到目标 (悬停逼近, 防撞)"""
    o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
    if approach_z is not None:
        for k in range(steps):
            o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            h = o[0:3]
            dv = np.zeros(4)
            dv[:2] = tgt_xyz[:2] - h[:2]
            dv[2] = (approach_z - h[2]) * 3
            dv[:3] = np.clip(dv[:3] / 0.04, -1, 1); dv[3] = -1.0
            e.step(dv) if False else env.step(dv)
            if np.linalg.norm(h[:2]-tgt_xyz[:2]) < 0.004 and abs(h[2]-approach_z) < 0.008:
                break
    for k in range(steps):
        o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
        h = o[0:3]
        dv = np.zeros(4)
        dv[:3] = np.clip((tgt_xyz - h) / 0.03, -1, 1); dv[3] = -1.0
        env.step(dv)
        if np.linalg.norm(h - tgt_xyz) < 0.006:
            break

o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
peg = o[4:7].copy()
hole = SP("hole").copy()

# 位形 2: peg 正上方悬停 (hand z = peg z + 0.09)
move_hand_to(np.array([peg[0], peg[1], peg[2] + 0.09]), approach_z=peg[2] + 0.12)
anchors("位形2 peg上方悬停")
yolo_shot()

# 位形 3: 下降抓握位 (hand 降到销身, 被销顶住 ~peg+0.02)
move_hand_to(np.array([peg[0], peg[1], peg[2] + 0.005]), approach_z=peg[2] + 0.05)
anchors("位形3 抓握位(被销顶)")
yolo_shot()

# 位形 4: 抬起 (hand 升到 peg+0.12)
move_hand_to(np.array([peg[0], peg[1], peg[2] + 0.12]), approach_z=None)
anchors("位形4 抬起中")
yolo_shot()

# 位形 5: 孔口附近 (hand 移到 hole 上方 +0.15)
move_hand_to(np.array([hole[0], hole[1], hole[2] + 0.18]), approach_z=hole[2] + 0.25)
anchors("位形5 孔口附近")
yolo_shot()
print("[calib] done", flush=True)
