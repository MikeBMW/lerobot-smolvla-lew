"""
MetaWorld ZmaxHybrid 20K — More examples: multi-episode rollouts, large grid
"""
import torch, numpy as np, imageio, math
from pathlib import Path
from PIL import Image, ImageDraw
from lerobot.policies.zmax_hybrid.modeling_zmax_hybrid import ZmaxHybridPolicy
from lerobot.datasets.lerobot_dataset import LeRobotDataset

CKPT = "outputs/zmax_hybrid_mw/checkpoints/020000/pretrained_model"
OUT_DIR = Path("outputs/zmax_hybrid_mw/eval_more")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ACT_M  = np.array([-0.00186553, 0.62268263, -0.4686827, 0.33541235])
ACT_S  = np.array([0.36481458, 0.7014135, 0.5240296, 0.29790264])
ST_M   = np.array([-0.00189123, 0.6750963, 0.11855247, 0.78269297])
ST_S   = np.array([0.05006854, 0.06091989, 0.06489153, 0.23833112])
INSTR  = "Push the puck to a goal"

def norm_state(r): return (r - ST_M) / (ST_S + 1e-8)
def unnorm_act(n):  return n * ACT_S + ACT_M

print("Loading model + dataset...")
policy = ZmaxHybridPolicy.from_pretrained(CKPT).cuda().eval()
ds = LeRobotDataset('lerobot/metaworld_mt50_push_v2_image')

# Episode boundaries
ep_map = {}
for i in range(ds.num_frames):
    ep = ds[i]['episode_index'].item()
    if ep not in ep_map: ep_map[ep] = [i, i]
    ep_map[ep][1] = i + 1
eps = sorted(ep_map.keys())
test_eps = eps[int(len(eps)*0.8):]

# ----- Helper: draw arrows on image -----
def draw_arrows(img, true_act, pred_act, mse):
    h, w = img.shape[:2]
    cx, cy = w//2, h-60
    scale = 120.0
    td = (true_act[0]*scale, -true_act[1]*scale)
    pd = (pred_act[0]*scale, -pred_act[1]*scale)
    pil = Image.fromarray(img)
    d = ImageDraw.Draw(pil)
    d.line([cx, cy, cx+td[0], cy+td[1]], fill=(0,255,0), width=14)
    d.line([cx, cy, cx+pd[0], cy+pd[1]], fill=(255,50,50), width=14)
    for dx, dy, c in [(td[0],td[1],(0,255,0)), (pd[0],pd[1],(255,50,50))]:
        ang = math.atan2(dy, dx); hl=24; ha=math.pi/6
        x2, y2 = cx+dx, cy+dy
        d.line([x2,y2, x2-hl*math.cos(ang-ha), y2-hl*math.sin(ang-ha)], fill=c, width=10)
        d.line([x2,y2, x2-hl*math.cos(ang+ha), y2-hl*math.sin(ang+ha)], fill=c, width=10)
    d.text((10,10), f"MSE={mse:.4f}", fill=(255,255,0))
    return np.array(pil)

# ----- Collect all test frames with predictions -----
print(f"Running {len(test_eps)} test episodes...")
all_frames = []
ep_rollouts = {}  # ep_idx -> [(img, true, pred, mse)]

for ep_idx in test_eps:
    s, e = ep_map[ep_idx]
    e = min(s+60, e)
    frames = []
    for i in range(s, e):
        item = ds[i]
        ns = norm_state(item['observation.state'].numpy())
        ns_t = torch.from_numpy(ns).float().unsqueeze(0).cuda()
        img_t = item['observation.image'].unsqueeze(0).cuda()
        raw_act = item['action'].numpy()
        images = policy._prepare_images({'observation.image': img_t})
        with torch.no_grad():
            feats = policy.model.predict_action(images, [INSTR], ns_t)
            pred_n = feats[:, :policy.config.chunk_size * policy.config.action_dim]
            pred_n = pred_n.reshape(1, policy.config.chunk_size, policy.config.action_dim)
        pred_raw = unnorm_act(pred_n[0,0].cpu().numpy())
        mse = np.mean((pred_raw - raw_act)**2)
        img_raw = (item['observation.image'].cpu().numpy()*255).astype(np.uint8).transpose(1,2,0)
        frames.append((img_raw, raw_act, pred_raw, mse))
    ep_rollouts[ep_idx] = frames
    all_frames.extend(frames)

all_frames.sort(key=lambda x: x[3])

# ===== 1. More best/worst GIF (15 frames each) =====
print("Generating: best15.gif, worst15.gif")
best15  = all_frames[:15]
worst15 = all_frames[-15:]
imageio.mimsave(str(OUT_DIR/'best15.gif'),  [draw_arrows(*f) for f in best15],  duration=300, loop=0)
imageio.mimsave(str(OUT_DIR/'worst15.gif'), [draw_arrows(*f) for f in worst15], duration=300, loop=0)

# ===== 2. 3-episode rollout GIF =====
print("Generating: 3ep_rollout.gif")
sel_eps = test_eps[:3]
rollout_imgs = []
for ep in sel_eps:
    for img, ta, pa, ms in ep_rollouts[ep]:
        rollout_imgs.append(draw_arrows(img, ta, pa, ms))
    # Blank separator between episodes
    sep = Image.new('RGB', (480,480), (20,20,20))
    d = ImageDraw.Draw(sep)
    d.text((200,230), f"--- Ep {ep} End ---", fill=(255,255,255))
    rollout_imgs.append(np.array(sep))
imageio.mimsave(str(OUT_DIR/'3ep_rollout.gif'), rollout_imgs, duration=120, loop=0)

# ===== 3. Big comparison grid: 4 episodes x 10 frames =====
print("Generating: big_grid.png")
N_EP = 4
N_FR = 10
sel_eps = test_eps[:N_EP]
thumb_w, thumb_h = 200, 200
pad = 4
gw = thumb_w * N_FR + pad*(N_FR+1)
gh = thumb_h * N_EP + pad*(N_EP+1) + 30
grid = Image.new('RGB', (gw, gh), (20,20,20))
d = ImageDraw.Draw(grid)
d.text((10, 8), "MetaWorld ZmaxHybrid 20K — Green=GT  Red=Pred", fill=(255,255,255))

for ei, ep in enumerate(sel_eps):
    frames = ep_rollouts[ep]
    step = max(1, len(frames)//N_FR)
    for fi in range(N_FR):
        idx = min(fi*step, len(frames)-1)
        img, ta, pa, ms = frames[idx]
        annotated = draw_arrows(img, ta, pa, ms)
        pil = Image.fromarray(annotated).resize((thumb_w, thumb_h))
        x = pad + fi*(thumb_w+pad)
        y = pad + 30 + ei*(thumb_h+pad)
        grid.paste(pil, (x, y))
grid.save(OUT_DIR/'big_grid.png')

# ===== 4. Per-dimension scatter plot as image =====
print("Generating: scatter.png")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

all_true = np.array([f[1] for f in all_frames])
all_pred = np.array([f[2] for f in all_frames])

fig, axes = plt.subplots(2, 2, figsize=(12, 10))
fig.suptitle('MetaWorld ZmaxHybrid 20K — Predicted vs True Actions', fontsize=14)
dim_names = ['dx', 'dy', 'dz', 'gripper']
for d, ax in enumerate(axes.flat):
    ax.scatter(all_true[:,d], all_pred[:,d], alpha=0.5, s=8, c='steelblue', edgecolors='none')
    lo = min(all_true[:,d].min(), all_pred[:,d].min())
    hi = max(all_true[:,d].max(), all_pred[:,d].max())
    ax.plot([lo, hi], [lo, hi], 'r--', linewidth=1, alpha=0.5)
    ax.set_xlabel(f'True {dim_names[d]}')
    ax.set_ylabel(f'Pred {dim_names[d]}')
    corr = np.corrcoef(all_true[:,d], all_pred[:,d])[0,1]
    mae = np.abs(all_true[:,d] - all_pred[:,d]).mean()
    ax.set_title(f'{dim_names[d]}  corr={corr:.3f}  MAE={mae:.3f}')
    ax.set_xlim(lo-0.1, hi+0.1)
    ax.set_ylim(lo-0.1, hi+0.1)
plt.tight_layout()
fig.savefig(OUT_DIR/'scatter.png', dpi=100)
plt.close()

# ===== Summary stats =====
all_mse = [f[3] for f in all_frames]
print(f"\n=== Summary ({len(all_frames)} frames) ===")
print(f"MSE:    {np.mean(all_mse):.4f} ± {np.std(all_mse):.4f}")
print(f"P25/P75: {np.percentile(all_mse,25):.4f} / {np.percentile(all_mse,75):.4f}")
# Per-dim MAE
all_true_a = np.array([f[1] for f in all_frames])
all_pred_a = np.array([f[2] for f in all_frames])
for d, name in enumerate(dim_names):
    mae = np.abs(all_true_a[:,d] - all_pred_a[:,d]).mean()
    corr = np.corrcoef(all_true_a[:,d], all_pred_a[:,d])[0,1]
    print(f"  {name}: MAE={mae:.4f}  corr={corr:.3f}")

print(f"\n=== Done! {OUT_DIR}/ ===")
for f in sorted(OUT_DIR.iterdir()):
    print(f"  {f.name}  ({f.stat().st_size/1024:.0f} KB)")

del policy; torch.cuda.empty_cache()
