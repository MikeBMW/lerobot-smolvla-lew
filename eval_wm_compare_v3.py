"""
MetaWorld ZmaxHybrid 20K — WM ON vs OFF: fixed version
predict_action returns [B,hdim] features; first chunk*act_dim elements = action
"""
import torch, numpy as np, imageio, math
from pathlib import Path
from PIL import Image, ImageDraw
from lerobot.policies.zmax_hybrid.modeling_zmax_hybrid import ZmaxHybridPolicy
from lerobot.datasets.lerobot_dataset import LeRobotDataset

CKPT = "outputs/zmax_hybrid_mw/checkpoints/020000/pretrained_model"
OUT_DIR = Path("outputs/zmax_hybrid_mw/eval_wm_compare_v3")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ACT_M = np.array([-0.00186553, 0.62268263, -0.4686827, 0.33541235])
ACT_S = np.array([0.36481458, 0.7014135, 0.5240296, 0.29790264])
ST_M  = np.array([-0.00189123, 0.6750963,  0.11855247, 0.78269297])
ST_S  = np.array([0.05006854, 0.06091989, 0.06489153, 0.23833112])

def ns(r): return (r-ST_M)/(ST_S+1e-8)
def ua(n): return n*ACT_S+ACT_M

print("Loading...")
policy = ZmaxHybridPolicy.from_pretrained(CKPT).cuda().eval()
ds = LeRobotDataset('lerobot/metaworld_mt50_push_v2_image')
model = policy.model

ep_map = {}
for i in range(ds.num_frames):
    ep = ds[i]['episode_index'].item()
    ep_map.setdefault(ep, [i,i])[1] = i+1
test_eps = sorted(ep_map.keys())
test_eps = test_eps[int(len(test_eps)*0.8):]

INSTR = "Push the puck to a goal"
C = policy.config.chunk_size  # 7
AD = policy.config.action_dim  # 4

@torch.no_grad()
def infer_wm_off(st, images):
    """Pure VLA → [B, hdim] fused features → slice first C*AD dims as action"""
    vlm_f = model._encode_vlm(images, [INSTR])
    vlm_g = vlm_f.mean(dim=1)
    x = model.vlm_to_hybrid(vlm_g).unsqueeze(1)
    se = model.state_proj(st).unsqueeze(1)
    x = torch.cat([x, se], dim=1)
    for layer in model.hybrid_layers:
        x = layer(x, None, gate=0.0)
    fused = x.mean(dim=1)  # [B, hdim]
    return fused[:, :C*AD].reshape(1, C, AD)

@torch.no_grad()
def infer_wm_on(st, images):
    """Hybrid: WM Z injection with real gates"""
    vlm_f = model._encode_vlm(images, [INSTR])
    vlm_g = vlm_f.mean(dim=1)
    x = model.vlm_to_hybrid(vlm_g).unsqueeze(1)
    se = model.state_proj(st).unsqueeze(1)
    x = torch.cat([x, se], dim=1)

    # WM: obs_seq from state + zero actions
    ctx = x.mean(dim=1)
    B = st.shape[0]
    T = model.config.num_video_frames
    zero_a = torch.zeros(B, AD, device=st.device)
    obs_parts = [torch.cat([st, zero_a], dim=-1) for _ in range(T)]
    obs_seq = torch.stack(obs_parts, dim=1)
    z_list, _ = model.world_model(obs_seq, ctx)

    # VLA with Z
    for i, layer in enumerate(model.hybrid_layers):
        z = z_list[i]
        gate = model.config.hybrid_gates[i]
        x = layer(x, z, gate)

    fused = x.mean(dim=1)
    return fused[:, :C*AD].reshape(1, C, AD)

# ----- Run -----
print(f"Running {len(test_eps)} episodes...")
results = {'on': [], 'off': [], 'mean': []}
frames = []

for ep in test_eps:
    s, e = ep_map[ep]; e = min(s+60, e)
    for i in range(s, e):
        item = ds[i]
        raw_act = item['action'].numpy()
        st_n = torch.from_numpy(ns(item['observation.state'].numpy())).float().unsqueeze(0).cuda()
        img_t = item['observation.image'].unsqueeze(0).cuda()
        images = policy._prepare_images({'observation.image': img_t})

        po = ua(infer_wm_on(st_n, images)[0,0].cpu().numpy())
        pf = ua(infer_wm_off(st_n, images)[0,0].cpu().numpy())

        mo = np.mean((po-raw_act)**2)
        mf = np.mean((pf-raw_act)**2)
        mm = np.mean((ACT_M-raw_act)**2)

        results['on'].append((mo, po))
        results['off'].append((mf, pf))
        results['mean'].append((mm, ACT_M))

        if (i-s)%3 == 0:
            frames.append({
                'img':(item['observation.image'].cpu().numpy()*255).astype(np.uint8).transpose(1,2,0),
                'true':raw_act, 'on':po, 'off':pf, 'mo':mo, 'mf':mf
            })

# ----- Report -----
print(f"\n{'='*65}")
print(f"{'Mode':<25} {'MSE':>10} {'±Std':>10} {'P25':>10} {'P75':>10}")
print(f"{'='*65}")
for k, label in [('on','WM ON (Hybrid)'), ('off','WM OFF (VLA only)'), ('mean','Mean Baseline')]:
    mses = [r[0] for r in results[k]]
    print(f"{label:<25} {np.mean(mses):10.5f} {np.std(mses):10.5f} "
          f"{np.percentile(mses,25):10.5f} {np.percentile(mses,75):10.5f}")

dim_names = ['dx', 'dy', 'dz', 'gripper']
print(f"\n{'Mode':<20}", end='')
for d in dim_names: print(f"{d:>10}", end='')
print("  (MAE)")
for mk, pk, lb in [('on','on','WM ON'), ('off','off','WM OFF')]:
    preds = np.array([f[pk] for f in frames])
    errs = preds - np.array([f['true'] for f in frames])
    print(f"{lb:<20}", end='')
    for d in range(4):
        print(f"{np.abs(errs[:,d]).mean():10.4f}", end='')
    print()

deltas = np.array([f['on']-f['off'] for f in frames])
print(f"\n=== WM DELTA (ON - OFF) ===")
for d, name in enumerate(dim_names):
    print(f"  {name}: mean={deltas[:,d].mean():+.4f}  rms={np.sqrt(np.mean(deltas[:,d]**2)):.4f}")

# Win rate
om = [r[0] for r in results['on']]
fm = [r[0] for r in results['off']]
wins = sum(1 for a,b in zip(om,fm) if a<b)
print(f"\nWM ON wins vs OFF: {wins}/{len(om)} ({100*wins/len(om):.1f}%)")
ties = sum(1 for a,b in zip(om,fm) if abs(a-b)<1e-6)
print(f"Ties: {ties}/{len(om)}")

# ----- Viz -----
def draw_3arrow(img, true_act, pred_on, pred_off, mo, mf):
    h,w=img.shape[:2]; cx,cy=w//2,h-60; sc=120.
    pil=Image.fromarray(img); d=ImageDraw.Draw(pil)
    for act,color in [(true_act,(0,255,0)),(pred_on,(50,150,255)),(pred_off,(255,50,50))]:
        dx=act[0]*sc; dy=-act[1]*sc
        d.line([cx,cy,cx+dx,cy+dy],fill=color,width=12)
        ang=math.atan2(dy,dx); hl=20; ha=math.pi/6
        x2,y2=cx+dx,cy+dy
        d.line([x2,y2,x2-hl*math.cos(ang-ha),y2-hl*math.sin(ang-ha)],fill=color,width=8)
        d.line([x2,y2,x2-hl*math.cos(ang+ha),y2-hl*math.sin(ang+ha)],fill=color,width=8)
    d.text((10,10),"Grn=GT Blu=ON Red=OFF",fill=(255,255,255))
    d.text((10,25),f"ON={mo:.3f} OFF={mf:.3f}",fill=(200,200,200))
    return np.array(pil)

frames.sort(key=lambda x: x['mo'])
best10=frames[:10]; worst10=frames[-10:]

print("\nGenerating...")
imageio.mimsave(str(OUT_DIR/'wm_best.gif'),[draw_3arrow(**f) for f in best10],duration=500,loop=0)
imageio.mimsave(str(OUT_DIR/'wm_worst.gif'),[draw_3arrow(**f) for f in worst10],duration=500,loop=0)

import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
modes_l = ['WM ON\n(Hybrid)','WM OFF\n(VLA only)','Mean\nBaseline']
ms = [np.mean([r[0] for r in results[k]]) for k in ['on','off','mean']]
ss = [np.std([r[0] for r in results[k]]) for k in ['on','off','mean']]
fig,ax=plt.subplots(figsize=(7,5))
bars=ax.bar(modes_l,ms,yerr=ss,color=['#3498db','#e74c3c','#95a5a6'],capsize=10,width=0.5)
for b,v in zip(bars,ms): ax.text(b.get_x()+b.get_width()/2,b.get_height()+0.005,f'{v:.4f}',ha='center',fontweight='bold')
ax.set_ylabel('MSE'); ax.set_title('MetaWorld 20K: WM ON vs OFF'); ax.set_ylim(0,max(ms)*1.3)
plt.tight_layout(); fig.savefig(OUT_DIR/'bar.png',dpi=100); plt.close()

print(f"\nDone! {OUT_DIR}/ =")
for f in sorted(OUT_DIR.iterdir()):
    print(f"  {f.name}  ({f.stat().st_size/1024:.0f} KB)")
del policy; torch.cuda.empty_cache()
