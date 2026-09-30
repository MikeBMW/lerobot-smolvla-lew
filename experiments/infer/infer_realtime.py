#!/usr/bin/env python3
"""SmolVLA实时推理 — 读Gateway关节数据 → 模型预测动作"""
import os, sys, torch, time, json, urllib.request

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["WANDB_MODE"] = "disabled"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

GATEWAY = "http://localhost:8080"

def get_joint_state():
    """从Gateway API获取当前关节状态"""
    try:
        with urllib.request.urlopen(f"{GATEWAY}/joints", timeout=3) as r:
            data = json.loads(r.read())
        joints = data.get("joints", {})
        if not joints:
            return None
        names = list(joints.keys())
        positions = [joints[n] for n in names]
        return {"names": names, "positions": positions}
    except Exception as e:
        print(f"  ⚠️ API error: {e}")
        return None

def main():
    print("🚀 SmolVLA 实时推理")
    print(f"   数据源: {GATEWAY}")
    
    # 加载模型
    print("🧠 加载预训练模型...")
    from lerobot.policies.smolvla import SmolVLAPolicy
    policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base", local_files_only=True)
    policy.eval()
    DEV = next(policy.parameters()).device
    total = sum(p.numel() for p in policy.parameters())
    print(f"   参数: {total:,} | 设备: {DEV}")
    
    cfg = policy.config
    print(f"   输入: {dict((n, f.type.value) for n, f in cfg.input_features.items())}")
    print(f"   输出: {dict((n, f.type.value) for n, f in cfg.output_features.items())}")
    
    # 获取当前关节状态
    print("\n📡 读取机器人状态...")
    state = get_joint_state()
    if not state:
        print("❌ 无法获取关节数据! Gateway运行中?")
        return
    
    print(f"   关节: {state['names']}")
    print(f"   位置: {[f'{p:.4f}' for p in state['positions']]}")
    
    # 构建推理batch
    print("\n🔮 推理...")
    batch = {}
    for n, f in cfg.input_features.items():
        shape = list(f.shape)
        if f.type.value == "VISUAL":
            batch[n] = torch.zeros(1, *shape, device=DEV)  # 占位图像
        elif f.type.value == "STATE":
            val = torch.tensor(state["positions"], dtype=torch.float32, device=DEV)
            if val.shape[0] != shape[0]:
                val = val[:shape[0]] if val.shape[0] > shape[0] else torch.cat([val, torch.zeros(shape[0]-val.shape[0], device=DEV)])
            batch[n] = val.unsqueeze(0)
        else:
            batch[n] = torch.randn(1, *shape, device=DEV)
    
    # 语言token (模型需要, 不管config怎么说都加)
    batch["observation.language.tokens"] = torch.zeros(1, 64, dtype=torch.long, device=DEV)
    batch["observation.language.attention_mask"] = torch.zeros(1, 64, dtype=torch.bool, device=DEV)
    
    t0 = time.time()
    with torch.no_grad():
        action = policy.select_action(batch)
    dt = time.time() - t0
    
    print(f"   耗时: {dt:.2f}s")
    print(f"\n🎯 预测动作 ({action.shape[1]}维):")
    for i, v in enumerate(action[0].tolist()):
        print(f"   dim_{i}: {v:+.4f}")
    
    # 持续推理循环
    print(f"\n{'='*50}")
    print("🔄 持续推理 (Ctrl+C 停止)")
    print(f"{'='*50}")
    
    try:
        while True:
            state = get_joint_state()
            if state:
                for n, f in cfg.input_features.items():
                    if f.type.value == "STATE":
                        val = torch.tensor(state["positions"], dtype=torch.float32, device=DEV)
                        if val.shape[0] != f.shape[0]:
                            val = val[:f.shape[0]] if val.shape[0] > f.shape[0] else torch.cat([val, torch.zeros(f.shape[0]-val.shape[0], device=DEV)])
                        batch[n] = val.unsqueeze(0)
                
                with torch.no_grad():
                    action = policy.select_action(batch)
                
                acts = [f"{v:+.4f}" for v in action[0].tolist()]
                print(f"  [{time.strftime('%H:%M:%S')}] 动作: {acts}")
            
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n👋 停止")

if __name__ == "__main__":
    main()
