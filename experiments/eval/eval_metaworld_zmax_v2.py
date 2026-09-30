"""
MetaWorld ZmaxHybrid 20K — Corrected evaluation with normalize/unnormalize
"""
import torch, numpy as np, imageio, math
from pathlib import Path
from PIL import Image, ImageDraw
from lerobot.policies.zmax_hybrid.modeling_zmax_hybrid import ZmaxHybridPolicy
from lerobot.datasets.lerobot_dataset import LeRobotDataset

CKPT = "outputs/zmax_hybrid_mw/checkpoints/020000/pretrained_model"
OUT_DIR = Path("outputs/zmax_hybrid_mw/eval_20k_v2")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Normalization stats from training
ACT_MEAN = np.array([-0.00186553, 0.62268263, -0.4686827, 0.33541235])
ACT_STD  = np.array([0.36481458, 0.7014135, 0.5240296, 0.29790264])
STATE_MEAN = np.array([-0.00189123, 0.6750963, 0.11855247, 0.78269297])
STATE_STD  = np.array([0.05006854, 0.06091989, 0.06489153, 0.23833112])

def normalize_action(raw):
    return (raw - ACT_MEAN) / (ACT_STD + 1e-8)

def unnormalize_action(norm):
    return norm * ACT_STD + ACT_MEAN

def normalize_state(raw):
    return (raw - STATE_MEAN) / (STATE_STD + 1e-8)

INSTRUCTION = "Push the puck to a goal"

print(f"=== MetaWorld ZmaxHybrid 20K — Corrected Eval ===")
print(f"Action mean: {ACT_MEAN}, std: {ACT_STD}")
print(f"State  mean: {STATE_MEAN}, std: {STATE_STD}")

# Load policy
print("Loading policy...")
policy = ZmaxHybridPolicy.from_pretrained(CKPT).cuda().eval()

# Load dataset
ds = LeRobotDataset('lerobot/metaworld_mt50_push_v2_image')
print(f"Dataset: {ds.num_episodes} eps, {ds.num_frames} frames")

# Episode boundaries
ep_boundaries = {}
for i in range(ds.num_frames):
    ep = ds[i]['episode_index'].item()
    if ep not in ep_boundaries:
        ep_boundaries[ep] = [i, i]
    ep_boundaries[ep][1] = i + 1
eps_sorted = sorted(ep_boundaries.keys())
test_eps = eps_sorted[int(len(eps_sorted) * 0.8):]

# --- Corrected inference ---
print(f"\nTest episodes: {len(test_eps)} ({test_eps[0]}-{test_eps[-1]})")
print("Running inference with normalize/unnormalize...")

all_ep_mse = []
all_frame_results = []

for ep_idx in test_eps:
    start, end = ep_boundaries[ep_idx]
    n_frames = min(end - start, 60)
    ep_mse = []

    for step, i in enumerate(range(start, min(start + n_frames, end))):
        item = ds[i]
        raw_state = item['observation.state'].numpy()          # [4]
        raw_image = item['observation.image'].unsqueeze(0).cuda()  # [1,3,480,480]
        raw_action = item['action'].numpy()                    # [4]

        # Normalize state
        norm_state = normalize_state(raw_state)
        norm_state_t = torch.from_numpy(norm_state).float().unsqueeze(0).cuda()

        # Handle instruction: ZmaxHybrid needs tokenized instruction
        # But predict_action_chunk internally creates instructions.
        # We need a raw forward pass with normalized input.
        # Strategy: modify batch to use normalized state, let the rest flow.
        images = policy._prepare_images({'observation.image': raw_image})
        
        # Manual forward with normalized state
        with torch.no_grad():
            # Quick hack: override predict_action_chunk's internal instruction
            features = policy.model.predict_action(images, [INSTRUCTION], norm_state_t)
            pred_norm = features[:, :policy.config.chunk_size * policy.config.action_dim]
            pred_norm = pred_norm.reshape(1, policy.config.chunk_size, policy.config.action_dim)

        pred_norm_action = pred_norm[0, 0].cpu().numpy()
        # Unnormalize prediction back to raw space
        pred_raw_action = unnormalize_action(pred_norm_action)

        # Compare in raw space
        mse = np.mean((pred_raw_action - raw_action) ** 2)
        ep_mse.append(mse)

        if step % 5 == 0:
            img_raw = item['observation.image'].cpu().numpy()
            img_raw = (img_raw * 255).astype(np.uint8).transpose(1, 2, 0)
            all_frame_results.append({
                'ep': ep_idx, 'frame': step,
                'img': img_raw, 'true': raw_action, 'pred': pred_raw_action, 'mse': mse
            })

    all_ep_mse.append(np.mean(ep_mse))

print(f"\n=== Corrected Results ===")
print(f"MSE mean: {np.mean(all_ep_mse):.6f}  std: {np.std(all_ep_mse):.6f}")
print(f"MSE min:  {np.min(all_ep_mse):.6f}  max:  {np.max(all_ep_mse):.6f}")
print(f"MSE median: {np.median(all_ep_mse):.6f}")

# Compare to baseline (predicting mean)
baseline_mse = np.mean((ACT_MEAN - np.array([
    ds[i]['action'].numpy() for ep in test_eps
    for i in range(ep_boundaries[ep][0], min(ep_boundaries[ep][0]+60, ep_boundaries[ep][1]))
])) ** 2)
print(f"Mean-predictor baseline MSE: {baseline_mse:.6f}")

# --- Per-dimension analysis ---
print("\n=== Per-Dimension Analysis ===")
dim_names = ['dx', 'dy', 'dz', 'gripper']
all_errors = []
for ep_idx in test_eps:
    start, end = ep_boundaries[ep_idx]
    n = min(end - start, 60)
    for i in range(start, min(start + n, end)):
        item = ds[i]
        raw_state = item['observation.state'].numpy()
        raw_action = item['action'].numpy()
        norm_state = normalize_state(raw_state)
        norm_state_t = torch.from_numpy(norm_state).float().unsqueeze(0).cuda()
        raw_image = item['observation.image'].unsqueeze(0).cuda()
        images = policy._prepare_images({'observation.image': raw_image})

        with torch.no_grad():
            features = policy.model.predict_action(images, [INSTRUCTION], norm_state_t)
            pred_norm = features[:, :policy.config.chunk_size * policy.config.action_dim]
            pred_norm = pred_norm.reshape(1, policy.config.chunk_size, policy.config.action_dim)
        pred_raw = unnormalize_action(pred_norm[0, 0].cpu().numpy())
        all_errors.append(pred_raw - raw_action)

errors = np.array(all_errors)
for d, name in enumerate(dim_names):
    print(f"  {name}: bias={errors[:,d].mean():+.4f}  MAE={np.abs(errors[:,d]).mean():.4f}")

# --- Visualization ---
def draw_arrows(img, true_act, pred_act, mse):
    h, w = img.shape[:2]
    cx, cy = w // 2, h - 60
    scale = 120.0

    true_dx = true_act[0] * scale
    true_dy = -true_act[1] * scale
    pred_dx = pred_act[0] * scale
    pred_dy = -pred_act[1] * scale

    pil = Image.fromarray(img)
    draw = ImageDraw.Draw(pil)

    # Green = GT, Red = Pred
    draw.line([cx, cy, cx + true_dx, cy + true_dy], fill=(0, 255, 0), width=14)
    draw.line([cx, cy, cx + pred_dx, cy + pred_dy], fill=(255, 50, 50), width=14)

    for dx, dy, color in [(true_dx, true_dy, (0, 255, 0)), (pred_dx, pred_dy, (255, 50, 50))]:
        angle = math.atan2(dy, dx)
        hlen = 24
        ha = math.pi / 6
        x2, y2 = cx + dx, cy + dy
        draw.line([x2, y2, x2 - hlen*math.cos(angle-ha), y2 - hlen*math.sin(angle-ha)], fill=color, width=10)
        draw.line([x2, y2, x2 - hlen*math.cos(angle+ha), y2 - hlen*math.sin(angle+ha)], fill=color, width=10)

    draw.text((10, 10), f"Grn=GT Red=Pred  MSE={mse:.4f}", fill=(255, 255, 0))
    return np.array(pil)

all_frame_results.sort(key=lambda x: x['mse'])
best5, worst5 = all_frame_results[:5], all_frame_results[-5:]

print("\nCreating visualizations...")
# Best
best_imgs = [draw_arrows(f['img'], f['true'], f['pred'], f['mse']) for f in best5]
imageio.mimsave(str(OUT_DIR / 'best_predictions.gif'), best_imgs, duration=400, loop=0)
print(f"  best_predictions.gif ({len(best_imgs)} frames)")

# Worst
worst_imgs = [draw_arrows(f['img'], f['true'], f['pred'], f['mse']) for f in worst5]
imageio.mimsave(str(OUT_DIR / 'worst_predictions.gif'), worst_imgs, duration=400, loop=0)
print(f"  worst_predictions.gif ({len(worst_imgs)} frames)")

# Episode rollout
ep = test_eps[0]
start, end = ep_boundaries[ep]
end = min(start + 50, end)
rollout = []
for i in range(start, end):
    item = ds[i]
    raw_state = item['observation.state'].numpy()
    raw_action = item['action'].numpy()
    norm_state = normalize_state(raw_state)
    norm_state_t = torch.from_numpy(norm_state).float().unsqueeze(0).cuda()
    raw_image = item['observation.image'].unsqueeze(0).cuda()
    images = policy._prepare_images({'observation.image': raw_image})

    with torch.no_grad():
        features = policy.model.predict_action(images, [INSTRUCTION], norm_state_t)
        pred_norm = features[:, :policy.config.chunk_size * policy.config.action_dim]
        pred_norm = pred_norm.reshape(1, policy.config.chunk_size, policy.config.action_dim)
    pred_raw = unnormalize_action(pred_norm[0, 0].cpu().numpy())
    mse = np.mean((pred_raw - raw_action) ** 2)

    img_raw = item['observation.image'].cpu().numpy()
    img_raw = (img_raw * 255).astype(np.uint8).transpose(1, 2, 0)
    rollout.append(draw_arrows(img_raw, raw_action, pred_raw, mse))

imageio.mimsave(str(OUT_DIR / 'episode_rollout.gif'), rollout, duration=150, loop=0)
print(f"  episode_rollout.gif ({len(rollout)} frames)")

# Comparison grid
grid = Image.new('RGB', (480*2+10, 480*5+50), (30, 30, 30))
draw = ImageDraw.Draw(grid)
draw.text((10, 5), "BEST (low MSE)", fill=(0, 255, 0))
draw.text((500, 5), "WORST (high MSE)", fill=(255, 50, 50))
for i in range(5):
    y = 25 + i*480
    b = Image.fromarray(draw_arrows(best5[i]['img'], best5[i]['true'], best5[i]['pred'], best5[i]['mse']))
    w = Image.fromarray(draw_arrows(worst5[i]['img'], worst5[i]['true'], worst5[i]['pred'], worst5[i]['mse']))
    grid.paste(b.resize((480, 480)), (0, y))
    grid.paste(w.resize((480, 480)), (490, y))
grid.save(OUT_DIR / 'comparison_grid.png')
print(f"  comparison_grid.png")

print(f"\n=== Done! {OUT_DIR}/ ===")
for f in sorted(OUT_DIR.iterdir()):
    print(f"  {f.name}  ({f.stat().st_size/1024:.0f} KB)")

del policy; torch.cuda.empty_cache()
