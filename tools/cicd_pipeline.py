#!/usr/bin/env python3
"""
Z-MAX ACT 三阶段渐进式训练管线 (老倪策略 2026-08-02)
  仿真快速验证 → 零样本测试 → 真机保守微调

  Stage 1  MetaWorld 仿真训练    backbone 冻结(lr 0) · lr 1e-4 · kl 10 · chunk 100 · n_action 50
  Stage 2  Sim-to-Real 零样本测试  stage1 模型 → Orin 真实数据评估 (MSE/成功率/Reality Gap)
  Stage 3  Orin 真实数据微调      stage1 权重初始化 · lr 1e-5 · backbone lr 1e-6 · temporal_ensemble 0.01

用法:
  python3 tools/cicd_pipeline.py run    --steps1 300 --steps3 300   # 全流程自动 1→2→3
  python3 tools/cicd_pipeline.py stage 1 --steps 300                # 只跑单阶段
  python3 tools/cicd_pipeline.py status                             # 查看状态
  python3 tools/cicd_pipeline.py test --steps1 20 --steps3 20       # 最少迭代跑通链路

状态文件: docs/PIPELINE_STATE.json — GUI 三阶段面板读取显示
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = str(REPO / ".venv" / "bin" / "python")
STATE = REPO / "docs" / "PIPELINE_STATE.json"

# ── 三阶段定义 ──
STAGES = {
    1: {"name": "MetaWorld 仿真训练", "data": "data/metaworld_joint6_v2",
        "lr": 1e-4, "lr_backbone": 0.0, "kl": 10.0, "chunk": 100, "n_action": 50,
        "ensemble": None, "desc": "Sawyer 6关节(6D/6D) · backbone 冻结 · 仿真快速验证"},
    2: {"name": "Sim-to-Real 零样本测试", "data": "data/orin_real_v1",
        "desc": "stage1 模型 → Orin 真实数据 · 量化 Reality Gap"},
    3: {"name": "Orin 真实数据微调", "data": "data/orin_real_v1",
        "lr": 1e-5, "lr_backbone": 1e-6, "kl": 10.0, "chunk": 100, "n_action": 1,
        "ensemble": 0.01, "desc": "stage1 权重初始化 · 保守微调"},
}


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"stage": 1, "state": "pending", "steps1": 300, "steps3": 300,
            "ckpt1": None, "ckpt3": None, "stage2": None, "ts": None, "log": "",
            "stages": {}}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")


def _log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    st = load_state()
    st["log"] = (st.get("log", "") + line + "\n")[-3000:]
    save_state(st)


def _f(x):
    """浮点 → yaml 安全字符串 (yaml 把无小数点的 1e-05 解析为 str, 必须带小数点)"""
    s = f"{float(x):.6f}".rstrip('0').rstrip('.')
    return s + '.0' if '.' not in s else s


def gen_train_cfg(stage: int, data_root: str, steps: int, ts_dir: str,
                  pretrained: str | None = None) -> Path:
    """基于 config_act_metaworld.yaml 生成 runtime 配置 (stage 专属超参)"""
    tmpl = REPO / "config_act_metaworld.yaml"
    cfg = tmpl.read_text(encoding="utf-8")
    s = STAGES[stage]
    # 1. 顶层字段: 行锚定替换 (避免误匹配 n_obs_steps 等子串)
    cfg = re.sub(r"(?m)^output_dir:.*", f"output_dir: outputs/train/{ts_dir}", cfg)
    cfg = re.sub(r"(?m)^job_name:.*", f"job_name: {ts_dir}", cfg)
    cfg = re.sub(r"(?m)^steps:.*", f"steps: {steps}", cfg)
    cfg = re.sub(r"(?m)^(\s*)lr:.*", rf"\1lr: {_f(s['lr'])}", cfg)
    cfg = re.sub(r"(?m)^(\s*)root:.*", rf"\1root: {data_root}", cfg)
    # 2. 删 policy 段旧值 (缩进2空格的重复键), 避免覆盖新超参
    for k in ("n_obs_steps", "n_action_steps", "chunk_size"):
        cfg = re.sub(rf"(?m)^  {k}:.*\n", "", cfg)
    # 3. policy 段插入 stage 专属超参 (ACTConfig 字段)
    pol = (f"  optimizer_lr: {_f(s['lr'])}\n"
           f"  optimizer_lr_backbone: {_f(s['lr_backbone'])}\n"
           f"  kl_weight: {_f(s['kl'])}\n"
           f"  chunk_size: {s['chunk']}\n"
           f"  n_action_steps: {s['n_action']}\n"
           f"  n_obs_steps: 1\n")
    if s["ensemble"] is not None:
        pol += f"  temporal_ensemble_coeff: {_f(s['ensemble'])}\n"
    cfg = re.sub(r"(?m)^  type: act\n", "  type: act\n" + pol, cfg, count=1)
    tmp = REPO / f"config_pipeline_s{stage}.yaml"
    tmp.write_text(cfg, encoding="utf-8")
    return tmp


def latest_ckpt(out_dir: str) -> str | None:
    ck_dir = REPO / out_dir / "checkpoints"
    if not ck_dir.is_dir():
        return None
    cks = [d for d in ck_dir.iterdir() if d.is_dir() and d.name.isdigit()]
    if not cks:
        return None
    best = sorted(cks, key=lambda d: int(d.name))[-1]
    pm = best / "pretrained_model"
    return str(pm) if pm.is_dir() else None


def latest_s1_ckpt() -> str | None:
    """最新 Stage1 训练产物 (act_s1_* 目录, 真实 metaworld 4D 模型)"""
    base = REPO / "outputs" / "train"
    if not base.is_dir():
        return None
    dirs = sorted([d for d in base.iterdir() if d.name.startswith("act_s1_")],
                  key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs:
        ck = latest_ckpt(str(d.relative_to(REPO)))
        if ck:
            return ck
    return None


def run_train(stage: int, steps: int, pretrained: str | None = None) -> tuple[bool, str]:
    """后台子进程跑 lerobot_train, 流式输出, 返回 (ok, ckpt_path)"""
    ts_dir = f"act_s{stage}_{time.strftime('%Y%m%d_%H%M%S')}"
    data_root = STAGES[stage]["data"]
    cfg = gen_train_cfg(stage, data_root, steps, ts_dir, pretrained)
    _log(f"🏋️ Stage{stage} 训练启动: {data_root} · {steps}步 · 输出 outputs/train/{ts_dir}"
         + (" · 预训练初始化 " + pretrained if pretrained else ""))
    p = subprocess.Popen([PY, "-m", "lerobot.scripts.lerobot_train", "--config_path", str(cfg)]
                         + ([f"--policy.path={pretrained}"] if pretrained else []),
                         cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1, encoding="utf-8", errors="replace")
    for line in p.stdout:
        _log(line.rstrip()[:200])
    p.wait()
    try:
        cfg.unlink()
    except OSError:
        pass
    ckpt = latest_ckpt(f"outputs/train/{ts_dir}")
    if p.returncode != 0:
        return False, f"训练失败 rc={p.returncode}"
    if not ckpt:
        return False, "训练结束但未找到 checkpoint"
    return True, ckpt


def run_stage2(ckpt1: str) -> tuple[bool, dict]:
    """零样本测试: ① 仿真内验证 (stage1 模型在 metaworld 测试集, 必有数字)
    ② Sim-to-Real 尝试 (Orin 真实数据; 维度不匹配则如实提示, 不阻塞)"""
    _log(f"🎯 Stage2: {ckpt1} → 仿真验证 + Sim-to-Real 测试")
    script = r'''
import json, os, sys, time
import numpy as np
import torch
torch.set_grad_enabled(False)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies import make_pre_post_processors

ckpt = sys.argv[1]
policy = ACTPolicy.from_pretrained(ckpt).cuda().eval()
pre, post = make_pre_post_processors(policy_cfg=policy.config, pretrained_path=ckpt)

def eval_ds(root, max_frames=300, test_ratio=0.2):
    """用 LeRobotDataset 加载 (遵守 meta features) · 测试集 = 尾部 test_ratio 帧
    (训练用前 80%, 评估用后 20% 帧, 避免"同分布全量"过拟合假象)"""
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds = LeRobotDataset("lerobot/pusht", root=root)
    n = len(ds)
    start = max(0, int(n * (1 - test_ratio)))
    test_n = n - start
    step = max(1, test_n // max_frames)
    idxs = list(range(start, n, step))[:max_frames]
    if not idxs:
        idxs = [n - 1]
    states, actions, imgs = [], [], []
    for i in idxs:
        item = ds[i]
        states.append(item["observation.state"].numpy().astype(np.float32))
        actions.append(item["action"].numpy().astype(np.float32))
        if "observation.image" in item:
            imgs.append(item["observation.image"].numpy().astype(np.float32))
    states = np.stack(states); actions = np.stack(actions)
    imgs = np.stack(imgs) if imgs else None
    has_img = bool(imgs is not None and policy.config.input_features and
                   any("image" in k for k in policy.config.input_features))
    mses, lats, hits = [], [], 0
    for i in range(len(states)):
        batch = {"observation.state": torch.from_numpy(states[i]).float().cuda().unsqueeze(0)}
        if has_img:
            batch["observation.image"] = torch.from_numpy(imgs[i]).float().cuda().unsqueeze(0)
        gt = actions[i]
        try:
            t0 = time.time()
            out = post(policy.select_action(batch))
            lat = (time.time() - t0) * 1000
            pred = out[0].cpu().numpy() if isinstance(out, (list, tuple)) else out.cpu().numpy()
            pred = np.asarray(pred).flatten()[: len(gt)]
            mse = float(np.mean((pred - gt) ** 2))
            mses.append(mse); lats.append(lat)
            if mse < 0.05:
                hits += 1
        except Exception as ex:
            return {"dim_mismatch": True, "detail": f"{type(ex).__name__}: {str(ex)[:140]}"}
    return {"frames": len(mses), "action_mse": float(np.mean(mses)), "mse_std": float(np.std(mses)),
            "success_rate": hits / max(len(mses), 1), "latency_ms": float(np.mean(lats)), "has_img": has_img}

sim = eval_ds(sys.argv[2])   # metaworld 训练集目录 (同分布, 必有结果)
real = eval_ds(sys.argv[3])  # Orin 真实数据目录 (可能维度不匹配)
print(json.dumps({"sim": sim, "sim2real": real}))
'''
    tmp = REPO / "tools" / "_pipeline_stage2_eval.py"
    tmp.write_text(script, encoding="utf-8")
    p = subprocess.run([PY, str(tmp), ckpt1,
                        str(REPO / STAGES[1]["data"]),
                        str(REPO / STAGES[2]["data"])],
                       capture_output=True, text=True, cwd=str(REPO), timeout=600)
    tmp.unlink(missing_ok=True)
    if p.returncode != 0:
        _log("❌ Stage2 评估失败: " + p.stderr[-400:])
        return False, {}
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        _log("❌ Stage2 输出解析失败: " + p.stdout[-300:])
        return False, {}
    sim, real = res.get("sim", {}), res.get("sim2real", {})
    if sim.get("dim_mismatch"):
        _log(f"❌ Stage2 仿真验证也失败: {sim.get('detail','')[:120]}")
        return False, {}
    if real.get("dim_mismatch"):
        res["verdict"] = f"仿真 MSE={sim['action_mse']:.4f} · Sim2Real 维度不匹配 → 必须微调 S3"
        _log(f"📊 Stage2 仿真验证: MSE={sim['action_mse']:.4f}±{sim['mse_std']:.4f} "
             f"| 成功率={sim['success_rate']*100:.1f}% | 延迟={sim['latency_ms']:.1f}ms")
        _log(f"⚠️ Stage2 Sim-to-Real: {real.get('detail','')[:120]} — 维度不匹配, 无法零样本, 进入 S3 微调")
        return True, res
    gap = "✅ 零样本直接可用" if real["action_mse"] < 0.05 else \
          ("⚠️ 零样本需微调" if real["action_mse"] < 0.3 else "❌ Reality Gap 大, 必须微调")
    res["verdict"] = gap
    _log(f"📊 Stage2 仿真验证: MSE={sim['action_mse']:.4f}±{sim['mse_std']:.4f} | 成功率={sim['success_rate']*100:.1f}%")
    _log(f"📊 Stage2 Sim-to-Real: MSE={real['action_mse']:.4f}±{real['mse_std']:.4f} "
         f"| 成功率={real['success_rate']*100:.1f}% | {gap}")
    return True, res


def run_stage(stage: int, steps: int) -> bool:
    st = load_state()
    stages = st.setdefault("stages", {})
    cur = stages.setdefault(str(stage), {"state": "pending"})
    cur["state"] = "running"
    st["stage"] = stage
    st["state"] = "running"
    st["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(st)
    ok = False
    try:
        if stage == 1:
            ok, ckpt = run_train(1, steps)
            if ok:
                cur["ckpt"] = ckpt
                cur["steps"] = steps
        elif stage == 2:
            ckpt1 = st.get("ckpt1") or stages.get("1", {}).get("ckpt") or latest_s1_ckpt()
            if not ckpt1:
                _log("❌ Stage2 需要 Stage1 的 checkpoint (先跑 stage 1)")
                return False
            ok, res = run_stage2(ckpt1)
            if ok:
                cur["result"] = res
        elif stage == 3:
            ckpt1 = st.get("ckpt1") or stages.get("1", {}).get("ckpt") or latest_s1_ckpt()
            if not ckpt1:
                _log("❌ Stage3 需要 Stage1 的 checkpoint")
                return False
            ok, ckpt = run_train(3, steps, pretrained=ckpt1)
            if not ok:
                # 维度不匹配 (metaworld 4D vs Orin 7D) → 权重迁移失败 → 降级从零训练
                _log("⚠️ stage1 权重迁移失败 (可能维度不匹配) → 降级从零训练")
                ok, ckpt = run_train(3, steps, pretrained=None)
            if ok:
                cur["ckpt"] = ckpt
                cur["steps"] = steps
    except Exception as ex:
        _log(f"❌ Stage{stage} 异常: {ex}")
        ok = False
    # 每阶段独立状态 (历史阶段保持 success, 不被后续阶段覆盖)
    cur["state"] = "success" if ok else "failed"
    cur["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    st["stage"] = stage
    st["state"] = cur["state"]
    st["ts"] = cur["ts"]
    save_state(st)
    return ok


def cmd_run(args):
    _log("🚀 三阶段管线启动 (自动流转 1→2→3)")
    for stage in (1, 2, 3):
        steps = args.steps1 if stage == 1 else (args.steps3 if stage == 3 else 0)
        ok = run_stage(stage, steps)
        if not ok:
            _log(f"⛔ 管线在 Stage{stage} 中止")
            sys.exit(1)
    _log("🎉 三阶段管线全部完成")


def cmd_status():
    st = load_state()
    print(json.dumps(st, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Z-MAX ACT 三阶段渐进式训练管线")
    sub = ap.add_subparsers(dest="cmd")
    p_run = sub.add_parser("run", help="全流程自动 1→2→3")
    p_run.add_argument("--steps1", type=int, default=300)
    p_run.add_argument("--steps3", type=int, default=300)
    p_stage = sub.add_parser("stage", help="单阶段")
    p_stage.add_argument("stage", type=int, choices=[1, 2, 3])
    p_stage.add_argument("--steps", type=int, default=300)
    sub.add_parser("status")
    p_test = sub.add_parser("test", help="最少迭代跑通链路")
    p_test.add_argument("--steps1", type=int, default=20)
    p_test.add_argument("--steps3", type=int, default=20)
    args = ap.parse_args()

    if args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "stage":
        sys.exit(0 if run_stage(args.stage, args.steps) else 1)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd == "test":
        _log("🧪 管线链路测试 (最少迭代)")
        for stage in (1, 2, 3):
            steps = args.steps1 if stage == 1 else args.steps3
            if not run_stage(stage, steps):
                sys.exit(1)
        _log("🧪 链路测试通过")
    else:
        ap.print_help()
