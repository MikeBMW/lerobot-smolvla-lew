#!/usr/bin/env python3
"""双脑 + 抓取点对位头 + 插入状态机 = 完整插拔流程
2026-08-10 老倪: 双脑(3-5/8) + 抓取点对位(loss 0.007) + 插入状态机

状态机:
  APPROACH  接近 (左脑MLP偏置, d_hp>0.10)
  ALIGN     水平对位 (抓握点, 水平差>0.02)
  DESCEND   垂直下降 (到抓握点, d_grasp<0.03)
  GRASP     夹持 (力控 0.3→0.6, d_grasp<0.015)
  LIFT      抬起 (peg z升高>0.02 → 升到孔高)
  TRANSFER  水平转移 (peg→hole 上方)
  INSERT    垂直插入 (下降, d_ph<0.05)
  DONE      完成

双脑:
  左脑 MLP: 39D→4D 动作 (偏置接近)
  右脑 WM:  next obs + contact判断 (acc 1.00)
  对位头: 39D→抓握点delta (loss 0.007)
"""
import os, sys, json
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("MUJOCO_GL", "glfw")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# 2026-08-23 老倪: 训练接 YOLO 感知 (真机同构) — 直载文件避开 lerobot 包 __init__
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "yolo_3d"))
_YOLO_WEIGHTS_CANDS = [
    "runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt",
    "runs/detect/outputs/yolo_peg/peg_full/weights/best.pt",
    "outputs/yolo_peg/peg_v1/weights/best.pt",
]
# 🎯 深度模型权重候选 (YOLO depth head, 正式训练优先)
_DEPTH_WEIGHTS_CANDS = [
    "outputs/yolo_peg_depth/peg_depth_v1-2/weights/best.pt",  # 08-24 GPU warm-start 训练产物(最新)
    "outputs/yolo_peg_depth/peg_depth_v1/weights/best.pt",    # 08-23 CPU 训练产物(旧)
    "outputs/yolo_peg_depth/peg_depth_smoke/weights/best.pt",
]
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
HIDDEN = 512

# 状态机
ST_APPROACH, ST_ALIGN, ST_DESCEND, ST_GRASP = 0, 1, 2, 3
ST_LIFT, ST_TRANSFER, ST_INSERT, ST_DONE = 4, 5, 6, 7
ST_NAMES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]

class LeftBrainMLP(nn.Module):
    """左脑: 39D obs → 4D 动作"""
    def __init__(self, obs_dim=39, act_dim=4):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(HIDDEN, HIDDEN), nn.ReLU(),
            nn.Linear(HIDDEN, act_dim))
    def forward(self, x):
        return self.net(x)

class RightBrainWM(nn.Module):
    """右脑: 39D obs + 4D action → next obs + contact判断 + 抓握点对位头"""
    def __init__(self, obs_dim=39, act_dim=4, hidden=256):
        super().__init__()
        self.enc = nn.Sequential(
            nn.Linear(obs_dim + act_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU())
        self.pred_next = nn.Linear(hidden, obs_dim)
        self.contact_head = nn.Linear(hidden, 1)
        self.align_head = nn.Linear(hidden, 3)  # 抓握点对位头 (delta xyz)
    def forward(self, obs, act):
        h = self.enc(torch.cat([obs, act], dim=-1))
        next_obs = self.pred_next(h)
        contact = torch.sigmoid(self.contact_head(h))
        align = self.align_head(h)
        return next_obs, contact, align

class AlignHead(nn.Module):
    """独立对位头: 39D obs → 抓握点delta (3D) — 训练时用, 评估融合"""
    def __init__(self, obs_dim=39, hidden=256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, 3))
    def forward(self, x):
        return self.net(x)

def make_env(seed=0):
    import metaworld
    mt = metaworld.MT1("peg-insert-side-v3")
    env = mt.train_classes["peg-insert-side-v3"](render_mode="rgb_array", camera_name="corner2")
    env._freeze_rand_vec = False
    env.set_task(mt.train_tasks[0])
    env.reset(seed=seed)
    env._freeze_rand_vec = True
    return env

def get_obs(env):
    return np.asarray(env._get_obs(), dtype=np.float32).ravel()

def grasp_target(env, hand):
    """抓握点目标: pegGrasp + 上方2cm"""
    try:
        pg = env.data.site_xpos[env.model.site("pegGrasp").id]
    except Exception:
        pg = env.data.site_xpos[env.model.site("pegHead").id]
    return pg + np.array([0.0, 0.0, 0.02]), pg

def _build_aligner():
    """🎯 构建 YOLO 感知对齐器 (2026-08-23 老倪: 训练接 YOLO 感知, 真机同构)
    失败返回 None → 回退真值"""
    try:
        import yolo_state_aligner
        w = next((os.path.join(ROOT, c) for c in _YOLO_WEIGHTS_CANDS
                  if os.path.isfile(os.path.join(ROOT, c))), None)
        if not w:
            print("⚠️ YOLO 权重未找到, 训练回退真值 state")
            return None
        # 🎯 深度模型权重 (YOLO depth head)
        depth_w = os.environ.get("DEPTH_CKPT")
        if depth_w:
            depth_w = os.path.normpath(depth_w)
        else:
            depth_w = next((os.path.join(ROOT, c) for c in _DEPTH_WEIGHTS_CANDS
                            if os.path.isfile(os.path.join(ROOT, c))), None)
        env0 = make_env(0)  # corner2, 只读静态相机参数
        a = yolo_state_aligner.YoloStateAligner(w, env0, depth_weights=depth_w)
        tag = f"深度感知: {os.path.basename(depth_w)}" if depth_w else "⚠️深度回退写死z"
        print(f"🎯 YOLO 感知训练已启用: {os.path.basename(w)} ({tag})")
        return a
    except Exception as ex:
        print(f"⚠️ YOLO 感知构建失败 ({str(ex)[:60]}), 回退真值 state")
        return None


def _yolo_state(env, raw_obs, aligner):
    """YOLO 检测→解算→替换 hand/peg/hole 段 (与 gen_metaworld_data --yolo 同构)"""
    if aligner is None:
        return np.asarray(raw_obs, dtype=np.float32).ravel()[:39]
    try:
        det = aligner.detect_3d(env.render())
        return aligner.align(np.asarray(raw_obs, dtype=np.float32).ravel(), det).astype(np.float32)[:39]
    except Exception:
        return np.asarray(raw_obs, dtype=np.float32).ravel()[:39]


def collect_data(n_eps=60, aug=False, aligner=None):
    """专家轨迹 → (obs, action, next_obs, contact, 抓握点delta)
    2026-08-10: aug=True 时种子随机化 (0-499 大范围), 数据增强降波动"""
    from metaworld.policies.sawyer_peg_insertion_side_v3_policy import SawyerPegInsertionSideV3Policy
    expert = SawyerPegInsertionSideV3Policy()
    obs_l, act_l, next_l, cont_l, align_l = [], [], [], [], []
    for ep in range(n_eps):
        # 2026-08-10: 数据增强 — 种子大范围随机 (原 0-49 固定, 评估新扰动泛化差)
        seed = np.random.randint(0, 500) if aug else ep
        env = make_env(seed)
        o = get_obs(env)
        o_yolo = _yolo_state(env, o, aligner)  # 🎯 YOLO 噪声 state
        for _ in range(300):
            o_expert = np.asarray(env._get_obs(), dtype=np.float64).ravel()
            a = np.asarray(expert.get_action(o_expert), dtype=np.float32)[:4]
            # 🐛 2026-08-24 静静: metaworld scripted policy 会输出超 [-1,1] 的动作(靠 env 内部 clip),
            #   直接存进 act_t → ys 超范围(实测 ys=[3.55,0.76,2.43,0.69]) → 左脑学超范围动作,
            #   评估时又被 np.clip 到 [-1,1] → 训练/评估动作分布不匹配 → 0/8 卡"接近"
            a = np.clip(a, -1.0, 1.0)
            hand = env.data.site_xpos[env.model.site("endEffector").id]
            target, pg = grasp_target(env, hand)
            d_hp = float(np.linalg.norm(hand - pg))
            contact = 1.0 if d_hp < 0.06 else 0.0
            align = target - hand
            o2, _, term, trunc, _ = env.step(a)
            next_raw = get_obs(env)
            next_yolo = _yolo_state(env, next_raw, aligner)  # 🎯 YOLO 噪声 next state
            obs_l.append(o_yolo); act_l.append(a); next_l.append(next_yolo)
            cont_l.append(contact); align_l.append(align)
            o = next_raw; o_yolo = next_yolo
            if np.linalg.norm(env.data.site_xpos[env.model.site("pegGrasp").id] - env.data.site_xpos[env.model.site("hole").id]) < 0.05:
                break
        env.close()
    return (np.stack(obs_l), np.stack(act_l), np.stack(next_l),
            np.array(cont_l, dtype=np.float32), np.stack(align_l))

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--eps", type=int, default=30, help="专家轨迹数 (默认30, CPU+YOLO检测较慢)")
    ap.add_argument("--epochs", type=int, default=800)
    ap.add_argument("--no-yolo", action="store_true", help="禁用 YOLO 感知, 用真值 state")
    args = ap.parse_args()

    torch.manual_seed(42)
    np.random.seed(42)
    aligner = None if args.no_yolo else _build_aligner()
    print(f"🧠 双脑 + 对位头 + 插入状态机 · {DEVICE} · YOLO感知={'关' if args.no_yolo else '开'}", flush=True)
    obs_t, act_t, next_t, cont_t, align_t = collect_data(n_eps=args.eps, aug=True, aligner=aligner)
    n = len(obs_t)
    print(f"  📦 数据: {n}帧 · contact正例: {cont_t.sum():.0f}", flush=True)
    # 归一化
    xm, xs = obs_t.mean(0), obs_t.std(0) + 1e-6
    ym, ys = act_t.mean(0), act_t.std(0) + 1e-6
    am, a_s = align_t.mean(0), align_t.std(0) + 1e-6
    left = LeftBrainMLP(39, 4).to(DEVICE)
    right = RightBrainWM(39, 4).to(DEVICE)
    align_h = AlignHead(39, 256).to(DEVICE)
    opt_l = optim.Adam(left.parameters(), lr=1e-3)
    opt_r = optim.Adam(right.parameters(), lr=1e-3)
    opt_a = optim.Adam(align_h.parameters(), lr=1e-3)
    obs_n = torch.from_numpy((obs_t - xm) / xs).float().to(DEVICE)
    act_n = torch.from_numpy((act_t - ym) / ys).float().to(DEVICE)
    obs_r = torch.from_numpy(obs_t).float().to(DEVICE)
    act_r = torch.from_numpy(act_t).float().to(DEVICE)
    next_r = torch.from_numpy(next_t).float().to(DEVICE)
    cont_r = torch.from_numpy(cont_t).float().to(DEVICE).unsqueeze(1)
    align_r = torch.from_numpy((align_t - am) / a_s).float().to(DEVICE)
    for ep in range(args.epochs):
        idx = torch.randperm(n, device=DEVICE)[:256]
        pred_a = left(obs_n[idx])
        loss_l = nn.functional.mse_loss(pred_a, act_n[idx])
        opt_l.zero_grad(); loss_l.backward(); opt_l.step()
        pred_next, pred_cont, _ = right(obs_r[idx], act_r[idx])
        loss_r = (nn.functional.mse_loss(pred_next, next_r[idx])
                  + 0.5 * nn.functional.binary_cross_entropy(pred_cont, cont_r[idx]))
        opt_r.zero_grad(); loss_r.backward(); opt_r.step()
        pred_align = align_h(obs_n[idx])
        loss_a = nn.functional.mse_loss(pred_align, align_r[idx])
        opt_a.zero_grad(); loss_a.backward(); opt_a.step()
        if ep % 200 == 0:
            print(f"  iter{ep}: 左脑={loss_l.item():.4f} 右脑={loss_r.item():.4f} 对位={loss_a.item():.4f}", flush=True)
    print(f"  ✅ 训练完成 (左脑={loss_l.item():.4f} 右脑contact_acc={((pred_cont>0.5).float()==cont_r[idx]).float().mean().item():.2f} 对位={loss_a.item():.4f})", flush=True)
    os.makedirs(os.path.join(ROOT, "outputs", "rl_peg"), exist_ok=True)
    torch.save({"left": left.state_dict(), "right": right.state_dict(), "align": align_h.state_dict(),
                "xm": xm, "xs": xs, "ym": ym, "ys": ys, "am": am, "a_s": a_s},
               os.path.join(ROOT, "outputs", "rl_peg", "full_pipeline.pt"))
    print(f"  💾 保存: outputs/rl_peg/full_pipeline.pt", flush=True)

    # 评估: 双脑抓取 + 状态机插入 (2026-08-10: 双脑5/8抓取验证 + 状态机插入验证 融合)
    print("\n🧪 评估: 双脑抓取 + 状态机插入 (8 seed)", flush=True)
    left.eval(); right.eval(); align_h.eval()
    lifts = ins = 0
    for seed in range(8):
        env = make_env(seed)
        o = get_obs(env)
        o_yolo = _yolo_state(env, o, aligner)  # 🎯 YOLO 解算 state (含深度反投影)
        peg_z0 = float(o_yolo[6])  # 🎯 真闭环: peg z 来自深度反投影 (非真值)
        state = ST_APPROACH
        grasp_force = -1.0
        peg_lifted = False
        for step in range(500):
            hand = o_yolo[0:3]    # 🎯 真闭环: hand 来自深度反投影
            peg = o_yolo[4:7]     # 🎯 真闭环: peg 来自深度反投影
            hole = o_yolo[36:39]  # 🎯 真闭环: hole 来自深度反投影
            d_hp = float(np.linalg.norm(hand - peg))
            d_ph = float(np.linalg.norm(peg - hole))
            target, pg = grasp_target(env, hand)
            d_grasp = float(np.linalg.norm(target - hand))
            # 左脑动作 (吃 YOLO 解算 state)
            xin = torch.from_numpy((o_yolo - xm) / xs).float().to(DEVICE)
            with torch.no_grad():
                pred = left(xin.unsqueeze(0)).squeeze(0).cpu().numpy()
            act = pred * ys + ym
            # 右脑 contact (吃 YOLO 解算 state)
            o_r = torch.from_numpy(o_yolo).float().to(DEVICE)
            a_r = torch.from_numpy(act).float().to(DEVICE)
            with torch.no_grad():
                _, pred_cont, _ = right(o_r.unsqueeze(0), a_r.unsqueeze(0))
            contact_p = pred_cont.item()
            # 状态转移 (2026-08-24 静静: 接近拆 水平对位→垂直下降, 修 hand 卡 z 降不下去)
            d_xy = float(np.linalg.norm(hand[:2] - peg[:2]))  # 水平距离
            if state == ST_APPROACH:
                if d_xy < 0.06: state = ST_ALIGN  # 水平接近到 6cm → 精确对位
            elif state == ST_ALIGN:
                if d_xy < 0.03: state = ST_DESCEND  # 水平对齐 3cm → 垂直下降
            elif state == ST_DESCEND:
                if contact_p > 0.5: state = ST_GRASP  # 接触即抓取 (检测 d_hp 在 hand/peg 靠近时失真, 用 contact 判断)
            elif state == ST_GRASP:
                if peg[2] - peg_z0 > 0.02:
                    state = ST_LIFT; peg_lifted = True
            elif state == ST_LIFT:
                if peg[2] > peg_z0 + 0.08: state = ST_TRANSFER  # 2026-08-10: 抬8cm避开台面, 防转移卡住
            elif state == ST_TRANSFER:
                if abs(peg[0] - hole[0]) < 0.05 and abs(peg[1] - hole[1]) < 0.05: state = ST_INSERT  # 2026-08-10: 容差5cm (peg有导向)
            elif state == ST_INSERT:
                if d_ph < 0.05:
                    state = ST_DONE; ins += 1; break
            # 动作执行 (2026-08-24 静静: 接近拆 水平对位→垂直下降, z 硬编码绕开左脑朝上偏置)
            if state == ST_APPROACH:
                # 先水平接近 (z 保持, 不依赖左脑 z 输出)
                delta_xy = peg[:2] - hand[:2]
                act[:2] = np.clip(delta_xy * 2.0, -1, 1)
                act[2] = 0.0
                act[3] = -1.0
            elif state == ST_ALIGN:
                # 精确水平对位 (z 保持)
                delta_xy = peg[:2] - hand[:2]
                act[:2] = np.clip(delta_xy * 3.0, -1, 1)
                act[2] = 0.0
                act[3] = -1.0
            elif state == ST_DESCEND:
                # 垂直下降 (x/y 锁定, z 硬编码下降)
                act[:2] = 0.0
                act[2] = -0.8
                act[3] = -1.0
            elif state == ST_GRASP:
                # 双脑: contact判断 → 夹持0.6 + 锁定
                act[:3] = act[:3] * 0.1
                act[3] = 0.6
                grasp_force = 0.6
            elif state == ST_LIFT:
                act[:3] = [0.0, 0.0, 0.8]  # 2026-08-10: 抬升力0.5→0.8 (更快到8cm)
                act[3] = 0.6
            elif state == ST_TRANSFER:
                d_xy = np.array([hole[0] - peg[0], hole[1] - peg[1]])
                d_xy_n = np.linalg.norm(d_xy)
                if d_xy_n > 1e-4:
                    # 2026-08-10: 转移速度自适应 — 距离越近越慢 (防过冲卡顿)
                    # 远(>0.2): 0.6 快移; 中(0.05-0.2): 0.35; 近(<0.05): 0.15 慢调
                    if d_xy_n > 0.2:
                        vel = 0.6
                    elif d_xy_n > 0.05:
                        vel = 0.35
                    else:
                        vel = 0.15
                    act[:3] = np.clip((d_xy / d_xy_n) * vel, -1, 1).tolist() + [0.0]
                act[3] = 0.6
            elif state == ST_INSERT:
                act[:3] = [0.0, 0.0, np.clip((hole[2] - peg[2]) * 2.0, -0.6, 0.6)]
                act[3] = 0.6
            else:
                act[:3] = [0.0, 0.0, 0.0]
                act[3] = 0.6
            _mx = float(np.abs(act).max()) if len(act) else 1.0
            if _mx > 1.0: act = act / _mx
            env.step(np.clip(act, -1, 1))
            o = get_obs(env)
            o_yolo = _yolo_state(env, o, aligner)  # 🎯 下一轮 YOLO state
            if step >= 499: break
        if peg_lifted: lifts += 1
        env.close()
        print(f"  seed{seed}: 状态={ST_NAMES[state]} 抓起={'✅' if peg_lifted else '❌'} 插入={'✅' if ins > 0 else '❌'}", flush=True)
    print(f"== 双脑+状态机: 抓起={lifts}/8 插入={ins}/8", flush=True)

if __name__ == "__main__":
    main()
