#!/usr/bin/env python3
"""Z-MAX 自动迭代 CICD · 训练→对比→判断→改进重训
流程:
  1. 训练增强模型 (当前 config)
  2. 与基线对比 (act_compare.py)
  3. 判断: MSE 提升 > 阈值? → 部署+版本号 | 否则 → 调整超参重训
用法:
  python3 tools/auto_iterate.py                # 单轮迭代
  python3 tools/auto_iterate.py --max-rounds 3 # 最多3轮
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

HOME = Path.home() / "lerobot-smolvla-lew"
BASELINE = "outputs/train/act_metaworld/checkpoints/000300/pretrained_model"
CANDIDATE = "outputs/train/act_mw_v111/checkpoints/002000/pretrained_model"
DATASET = "data/metaworld_act"
THRESHOLD = 5.0  # MSE 提升阈值 (%) · 低于则改进重训


def run(cmd, cwd=HOME):
    r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=1800)
    return r


def compare():
    """跑对比, 返回 (mse_improve_pct, success)"""
    r = run(f"PYTHONPATH=src .venv/bin/python tools/act_compare.py "
            f"--baseline {BASELINE} --candidate {CANDIDATE} --dataset {DATASET} "
            f"--report docs/CICD_COMPARE_auto.json --n-eps 10")
    if r.returncode != 0:
        print(f"❌ 对比失败: {r.stderr[-300:]}")
        return None, False
    try:
        d = json.load(open(HOME / "docs" / "CICD_COMPARE_auto.json"))
        return d.get("mse_improve_pct", 0), True
    except Exception:
        return None, False


def improve_config(round_num):
    """未达标: 调整超参 (lr 衰减 / batch 增大 / 步数增加)"""
    cfg = HOME / "config_act_mw_v111.yaml"
    text = cfg.read_text()
    steps = 2000 + round_num * 1000
    lr = 1e-4 * (0.8 ** round_num)  # lr 逐轮衰减
    import re
    text = re.sub(r"steps: \d+", f"steps: {steps}", text)
    text = re.sub(r"lr: [\d.e-]+", f"lr: {lr:.2e}", text)
    cfg.write_text(text)
    print(f"🔧 改进方案 v{round_num+1}: steps={steps} lr={lr:.2e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rounds", type=int, default=1)
    args = ap.parse_args()

    for rnd in range(args.max_rounds):
        print(f"\n{'='*50}\n🔄 迭代轮 {rnd+1}/{args.max_rounds}\n{'='*50}")
        # 1. 训练
        print("🏋️ 训练增强模型...")
        rr = run("rm -rf outputs/train/act_mw_v111 && "
                 "PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train "
                 "--config_path config_act_mw_v111.yaml 2>&1 | tail -3")
        if rr.returncode != 0:
            print(f"❌ 训练失败: {rr.stderr[-200:]}")
            return 1
        # 2. 对比
        print("🔬 对比基线...")
        imp, ok = compare()
        if not ok or imp is None:
            print("❌ 对比失败")
            return 1
        print(f"📊 MSE 提升: {imp:+.2f}%")
        # 3. 判断
        if imp >= THRESHOLD:
            print(f"✅ 达标 (≥{THRESHOLD}%) → 部署 + 版本号")
            return 0
        else:
            print(f"⚠️ 未达标 (<{THRESHOLD}%) → 改进方案重训")
            improve_config(rnd + 1)
    print(f"⏹ 达到最大轮数 {args.max_rounds}，最终 MSE 提升 {imp:+.2f}%")
    return 0 if imp >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
