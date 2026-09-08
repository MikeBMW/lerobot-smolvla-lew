"""5模型对比视频生成器 — 每个模型 rollout 片段 + 距离趋势 + 抓起标注 (2026-08-08)
老倪反复要"对比视频" → 直接跑本脚本, 别每次现写。
用法: DISPLAY=:0 MUJOCO_GL=glfw .venv/bin/python tools/gen_compare_video.py
前置: reports/train_curve_<policy>.json 存在且 ckpt 指向有效目录 (见 SKILL.md 评估前置)。
输出: reports/compare_container_5model.mp4 (1080x480, 双列: 画面 | 距离趋势)
"""
import sys, os, numpy as np, torch, cv2
sys.path.insert(0, '/home/xspace/lerobot-smolvla-lew/tools')
os.chdir('/home/xspace/lerobot-smolvla-lew')
from eval_insert import load_policy
import metaworld
from PIL import Image as _PIL

MODELS = [
    ('act', 'ACT', '#58a6ff'),
    ('smolvla', 'SmolVLA', '#3fb950'),
    ('smolvla_lew', 'SmolVLA+LEW', '#f0a030'),
    ('vla_touch', 'VLA-Touch', '#d4a800'),
    ('awe_zflow', 'AWE', '#f85149'),
]
# 评估结果 (容器版 8 seed) — 每次重训后更新
EVAL = {'act': (0, 8), 'smolvla': (0, 8), 'smolvla_lew': (0, 8), 'vla_touch': (0, 8), 'awe_zflow': (0, 8)}

def rollout_clip(name, seed=1, n_steps=120):
    from eval_insert import _load_stats
    pol, _ = load_policy(name)
    stats = _load_stats(name)
    sm = np.array(stats['observation.state']['mean'], dtype=np.float32)[:45]
    ss = np.array(stats['observation.state']['std'], dtype=np.float32)[:45] + 1e-6
    am = np.array(stats['action']['mean'], dtype=np.float32)[:4]
    asd = np.array(stats['action']['std'], dtype=np.float32)[:4] + 1e-6
    mt = metaworld.MT1('peg-insert-side-v3')
    env = mt.train_classes['peg-insert-side-v3'](render_mode='rgb_array', camera_name='corner2')
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    obs, _ = env.reset(seed=seed)
    env._freeze_rand_vec = True
    frames, dists = [], []
    for i in range(n_steps):
        hand = env.data.site_xpos[env.model.site('endEffector').id]
        peg = env.data.site_xpos[env.model.site('pegGrasp').id]
        d = float(np.linalg.norm(hand - peg))
        dists.append(d)
        rgb = np.asarray(env.render())
        frames.append(rgb)
        st_raw = np.asarray(obs, dtype=np.float32)[:39]
        hp = env.data.site_xpos[env.model.site("endEffector").id].astype(np.float32)
        pp = env.data.site_xpos[env.model.site("pegGrasp").id].astype(np.float32)
        h2 = env.data.site_xpos[env.model.site("hole").id].astype(np.float32)
        rel = np.concatenate([pp - hp, h2 - pp]).astype(np.float32)
        st_n = (np.concatenate([st_raw, rel]) - sm) / ss
        rgb128 = np.asarray(_PIL.fromarray(rgb).resize((128,128), _PIL.LANCZOS)).transpose(2,0,1)/255.0
        batch = {'observation.image': torch.from_numpy(rgb128).float().to('cuda').unsqueeze(0),
                 'observation.state': torch.from_numpy(st_n).float().to('cuda').unsqueeze(0)}
        with torch.no_grad():
            pred = pol.select_action(batch)
        act = np.asarray(pred.detach().cpu()).ravel() * asd + am
        if d < 0.08: act[3] = -1.0   # 夹爪辅助 (评估铁律)
        else: act[3] = 0.0
        obs, r, term, trunc, _ = env.step(act)
        if term or trunc: break
    env.close()
    return frames, dists

print('生成各模型 rollout 片段...', flush=True)
clips = []
for name, label, color in MODELS:
    try:
        frames, dists = rollout_clip(name)
        lifts, n = EVAL[name]
        clips.append((label, color, frames, dists, lifts, n))
        print(f'  {label}: {len(frames)}帧 距孔 {dists[0]:.3f}->{dists[-1]:.3f}', flush=True)
    except Exception as e:
        print(f'  {label}: 失败 {str(e)[:60]}', flush=True)

if not clips:
    print('❌ 无有效片段'); sys.exit(1)

max_frames = max(len(c[2]) for c in clips)
W, H = 480, 480
PAD = 40
out = []
for t in range(max_frames):
    row = np.zeros((H, W * 2 + PAD * 3, 3), dtype=np.uint8)
    for i, (label, color, frames, dists, lifts, n) in enumerate(clips):
        img = frames[min(t, len(frames)-1)] if frames else np.zeros((W, H//3, 3), dtype=np.uint8)
        x = (i % 2) * (W + PAD) + PAD
        y = (i // 2) * (H // 3)
        img = cv2.resize(img, (W, H // 3))
        row[y:y+img.shape[0], x:x+W] = img
        cv2.putText(row, f'{label} (抓起 {lifts}/{n})', (x+8, y+22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 2)
        px, py = x, y + img.shape[0] + 5
        hist_w = W - 20
        for j in range(1, min(t+1, len(dists))):
            x0 = px + 10 + (j-1) * hist_w // max(1, len(dists)-1)
            y0 = py + 25 + int(min(dists[j-1], 0.5)/0.5 * 55)
            x1 = px + 10 + j * hist_w // max(1, len(dists)-1)
            y1 = py + 25 + int(min(dists[j], 0.5)/0.5 * 55)
            cv2.line(row, (x0, y0), (x1, y1), (255,255,255), 1)
    out.append(row)
h, w = out[0].shape[:2]
writer = cv2.VideoWriter('/home/xspace/lerobot-smolvla-lew/reports/compare_container_5model.mp4', cv2.VideoWriter_fourcc(*'mp4v'), 10, (w, h))
for f in out: writer.write(f)
writer.release()
print(f'✅ 对比视频: {len(out)}帧 {w}x{h}', flush=True)
# 转码 (libx264 + yuv420p 兼容播放), 用户默认要 180° 旋转版本 (corner2 源)
os.system('ffmpeg -y -i reports/compare_container_5model.mp4 -c:v libx264 -pix_fmt yuv420p -crf 23 -loglevel error /tmp/compare_container.mp4')
