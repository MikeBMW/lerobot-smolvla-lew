#!/usr/bin/env python3
"""SmolVLA实时推理 — 真实相机图像 + 关节 → 动作预测 → 飞书"""
import os, sys, torch, time, json, subprocess, io, base64
import numpy as np
from PIL import Image, ImageDraw, ImageFont

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["WANDB_MODE"] = "disabled"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

GATEWAY = "http://localhost:8080"
OUT = os.path.expanduser("~/vla_output.png")

def get_joints():
    import urllib.request
    try:
        with urllib.request.urlopen(f"{GATEWAY}/joints", timeout=3) as r:
            data = json.loads(r.read())
        j = data.get("joints", {})
        if j:
            return list(j.keys()), [j[n] for n in j]
    except: pass
    return None, None

def get_camera_image():
    """从Orin拉取最新相机图像"""
    try:
        r = subprocess.run(
            ["ssh","-o","ConnectTimeout=3","-o","StrictHostKeyChecking=no",
             "nvidia@192.168.23.10","cat /tmp/camera.jpg"],
            capture_output=True, timeout=5)
        if r.returncode == 0 and r.stdout:
            img = Image.open(io.BytesIO(r.stdout))
            return img
    except: pass
    return None

def create_output_image(cam_img, joints, action, ts):
    """创建输出图：相机 + 关节 + 预测动作"""
    w, h = 640, 480 + 180
    out = Image.new('RGB', (w, h), (20, 20, 30))
    
    # 上方：相机图像
    if cam_img:
        cam_img = cam_img.resize((640, 480))
        out.paste(cam_img, (0, 0))
    
    # 下方：信息面板
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
    except:
        font = font_sm = ImageFont.load_default()
    
    y = 488
    draw.text((10, y), f"🕐 {ts}", fill=(180,180,180), font=font_sm)
    y += 20
    draw.text((10, y), "🦾 JOINTS:", fill=(100,200,255), font=font_sm)
    y += 16
    
    if joints:
        for i, (name, pos) in enumerate(zip(joints[0], joints[1])):
            col = (100,255,100) if abs(pos) < 1.0 else (255,200,100)
            short = name.split('_')[-1]
            draw.text((10 + (i%3)*210, y + (i//3)*18), f"{short}: {pos:+.4f}", fill=col, font=font_sm)
    
    y += 40
    draw.text((10, y), "🎯 SmolVLA ACTION:", fill=(255,200,100), font=font_sm)
    y += 16
    if action is not None:
        for i, v in enumerate(action):
            col = (255,150,150) if abs(v) > 0.5 else (150,255,150)
            draw.text((10 + (i%3)*210, y + (i//3)*18), f"dim_{i}: {v:+.4f}", fill=col, font=font_sm)
    
    return out

def main():
    print("🚀 SmolVLA 真实相机推理")
    
    # 加载模型
    print("🧠 加载模型...")
    from lerobot.policies.smolvla import SmolVLAPolicy
    policy = SmolVLAPolicy.from_pretrained("lerobot/smolvla_base", local_files_only=True)
    policy.eval()
    DEV = next(policy.parameters()).device
    print(f"   450M params on {DEV}")
    
    cfg = policy.config
    
    print("\n🔄 开始循环推理...")
    
    for step in range(5):
        ts = time.strftime("%H:%M:%S")
        
        # 获取相机图像
        cam_img = get_camera_image()
        has_cam = cam_img is not None
        
        # 获取关节
        names, positions = get_joints()
        has_joints = names is not None
        
        if not has_joints:
            print(f"  [{ts}] ⚠️ 无关节数据")
            time.sleep(1)
            continue
        
        # 构建batch
        batch = {}
        img_tensor = None
        if has_cam:
            img_resized = cam_img.resize((64, 64))
            img_tensor = torch.from_numpy(np.array(img_resized)).float().permute(2,0,1) / 255.0
        
        for n, f in cfg.input_features.items():
            if f.type.value == "VISUAL":
                if img_tensor is not None:
                    batch[n] = img_tensor.unsqueeze(0).to(DEV)
                else:
                    batch[n] = torch.zeros(1, *f.shape, device=DEV)
            elif f.type.value == "STATE":
                val = torch.tensor(positions, dtype=torch.float32, device=DEV)
                if val.shape[0] > f.shape[0]:
                    val = val[:f.shape[0]]
                elif val.shape[0] < f.shape[0]:
                    val = torch.cat([val, torch.zeros(f.shape[0]-val.shape[0], device=DEV)])
                batch[n] = val.unsqueeze(0)
            else:
                batch[n] = torch.randn(1, *f.shape, device=DEV)
        
        batch["observation.language.tokens"] = torch.zeros(1, 64, dtype=torch.long, device=DEV)
        batch["observation.language.attention_mask"] = torch.zeros(1, 64, dtype=torch.bool, device=DEV)
        
        # 推理
        t0 = time.time()
        with torch.no_grad():
            action = policy.select_action(batch)
        dt = time.time() - t0
        act = action[0].cpu().tolist()
        
        print(f"  [{ts}] {'📸' if has_cam else '⬛'} 推理{dt:.1f}s 动作:{[f'{v:+.3f}' for v in act[:3]]}...")
        
        # 生成输出图
        out_img = create_output_image(cam_img, (names, positions), act, ts)
        out_img.save(OUT)
        
        if step < 4:
            time.sleep(1.5)
    
    print(f"\n✅ 完成! 输出: {OUT}")
    return OUT

if __name__ == "__main__":
    main()
