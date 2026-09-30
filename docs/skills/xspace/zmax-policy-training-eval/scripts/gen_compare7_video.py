"""7模型对比视频 — 容器训练版 (2026-08-08 老倪: 七个视频对比 + Scope)
用法: cd /home/xspace/lerobot-smolvla-lew && DISPLAY=:0 MUJOCO_GL=glfw \
      .venv/bin/python tools/gen_compare7_video.py
输出: reports/compare_7model_container.mp4 (4列2行 1440x480)
坑: EVAL 必须用 label 做 key (dict(MODELS) 对三元组崩); 官方专家分支用 get_action
"""
import sys, os, numpy as np, torch, cv2
sys.path.insert(0, '/home/xspace/lerobot-smolvla-lew/tools')
os.chdir('/home/xspace/lerobot-smolvla-lew')
import metaworld
from PIL import Image as _PIL

# 7 模型: (key, label, color)
MODELS = [
    ('act', 'ACT', '#58a6ff'),
    ('smolvla', 'SmolVLA', '#3fb950'),
    ('smolvla_lew', 'SmolVLA+LEW', '#f0a030'),
    ('vla_touch', 'VLA-Touch', '#d4a800'),
    ('awe_zflow', 'AWE', '#f85149'),
    ('expert_mlp', 'MLP蒸馏', '#bc8cff'),
    ('expert_policy', '官方专家', '#ffd700'),
]
# ⚠️ key 用 label 不用模型 key (否则 dict(MODELS) 崩)
EVAL = {'ACT': '0/8', 'SmolVLA': '0/8', 'SmolVLA+LEW': '0/8',
        'VLA-Touch': '0/8', 'AWE': '0/8',
        'MLP蒸馏': '6/10', '官方专家': '19/20'}

def make_env(seed=1):
    mt = metaworld.MT1('peg-insert-side-v3')
    env = mt.train_classes['peg-insert-side-v3'](render_mode='rgb_array', camera_name='corner2')
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    return env

def rollout(policy_fn, seed=1, n_steps=100):
    env = make_env(seed)
    obs = None
    frames, dists = [], []
    for i in range(n_steps):
        hand = env.data.site_xpos[env.model.site('endEffector').id]
        peg = env.data.site_xpos[env.model.site('pegGrasp').id]
        d = float(np.linalg.norm(hand - peg))
        dists.append(d)
        frames.append(np.asarray(env.render()))
        act = policy_fn(env, obs)
        obs, r, term, trunc, _ = env.step(act)
        if term or trunc: break
    env.close()
    return frames, dists

def load_policy_fn(name):
    """返回 policy_fn(env, obs)->action"""
    from eval_insert import load_policy, _load_stats
    if name == 'expert_policy':
        from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
        expert = SawyerPegInsertionSideV3Policy()
        def fn(env, obs):
            o = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            return np.asarray(expert.get_action(o), dtype=np.float32)[:4]
        return fn
    pol, _ = load_policy(name)
    stats = _load_stats(name)
    sm = np.array(stats['observation.state']['mean'], dtype=np.float32)[:45]
    ss = np.array(stats['observation.state']['std'], dtype=np.float32)[:45] + 1e-6
    am = np.array(stats['action']['mean'], dtype=np.float32)[:4]
    asd = np.array(stats['action']['std'], dtype=np.float32)[:4] + 1e-6
    def fn(env, obs):
        rgb = np.asarray(env.render())
        st_raw = np.asarray(env._get_obs(), dtype=np.float32).ravel()[:39]
        hp = env.data.site_xpos[env.model.site("endEffector").id].astype(np.float32)
        pp = env.data.site_xpos[env.model.site("pegGrasp").id].astype(np.float32)
        h2 = env.data.site_xpos[env.model.site("hole").id].astype(np.float32)
        rel = np.concatenate([pp - hp, h2 - pp]).astype(np.float32)
        st_n = (np.concatenate([st_raw, rel]) - sm) / ss
        rgb128 = np.asarray(_PIL.fromarray(rgb).resize((128, 128), _PIL.LANCZOS)).transpose(2, 0, 1) / 255.0
        batch = {'observation.image': torch.from_numpy(rgb128).float().to('cuda').unsqueeze(0),
                 'observation.state': torch.from_numpy(st_n).float().to('cuda').unsqueeze(0)}
        with torch.no_grad():
            pred = pol.select_action(batch)
        act = np.asarray(pred.detach().cpu()).ravel() * asd + am
        return act[:4]
    return fn

print('生成 7 模型 rollout...', flush=True)
clips = []
for name, label, color in MODELS:
    try:
        fn = load_policy_fn(name)
        frames, dists = rollout(fn)
        clips.append((label, color, frames, dists))
        print(f'  {label}: {len(frames)}帧 距孔 {dists[0]:.3f}->{dists[-1]:.3f}', flush=True)
    except Exception as e:
        print(f'  {label}: 失败 {str(e)[:70]}', flush=True)

if not clips:
    print('❌ 无片段'); sys.exit(1)

max_frames = max(len(c[2]) for c in clips)
CW, CH = 360, 240
COLS, ROWS = 4, 2
W = COLS * CW; H = ROWS * CH
out = []
for t in range(max_frames):
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    for i, (label, color, frames, dists) in enumerate(clips):
        r, c = i // COLS, i % COLS
        x0, y0 = c * CW, r * CH
        img = frames[min(t, len(frames) - 1)]
        img = cv2.resize(img, (CW, CH - 40))
        frame[y0:y0 + img.shape[0], x0:x0 + CW] = img
        cv2.putText(frame, f'{label} ({EVAL[label]})', (x0 + 6, y0 + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2)
        py = y0 + img.shape[0] + 8
        hist_w = CW - 16
        for j in range(1, min(t + 1, len(dists))):
            x1 = x0 + 8 + (j - 1) * hist_w // max(1, len(dists) - 1)
            y1 = py + 8 + int(min(dists[j - 1], 0.5) / 0.5 * 12)
            x2 = x0 + 8 + j * hist_w // max(1, len(dists) - 1)
            y2 = py + 8 + int(min(dists[j], 0.5) / 0.5 * 12)
            cv2.line(frame, (x1, y1), (x2, y2), (0, 255, 255), 1)
    out.append(frame)
h, w = out[0].shape[:2]
writer = cv2.VideoWriter('/home/xspace/lerobot-smolvla-lew/reports/compare_7model_container.mp4',
                         cv2.VideoWriter_fourcc(*'mp4v'), 10, (w, h))
for f in out: writer.write(f)
writer.release()
print(f'✅ 7模型对比视频: {len(out)}帧 {w}x{h}', flush=True)
