"""SmolVLA vs ACT 性能对比"""
import torch, time, json
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.policies.act import ACTPolicy
from lerobot.datasets import LeRobotDataset
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from transformers import AutoTokenizer
from torch.utils.data import DataLoader

ds = LeRobotDataset('lerobot/pusht', episodes=[0])
batch = next(iter(DataLoader(ds, batch_size=1)))
batch = {k: v.to('cuda') if isinstance(v, torch.Tensor) else v for k, v in batch.items()}
results = {}

def bench(name, fn):
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(20):
        fn()
    torch.cuda.synchronize()
    return (time.perf_counter() - t0) / 20

# === SmolVLA ===
print('SmolVLA...')
m = SmolVLAPolicy.from_pretrained('lerobot/smolvla_base').to('cuda').eval()
tok = AutoTokenizer.from_pretrained(m.config.vlm_model_name)
enc = tok('push the block', return_tensors='pt', padding='max_length', max_length=48, truncation=True)
ib = {
    'observation.images.camera1': batch['observation.image'],
    'observation.images.camera2': batch['observation.image'],
    'observation.images.camera3': batch['observation.image'],
    'observation.state': batch['observation.state'],
    OBS_LANGUAGE_TOKENS: enc['input_ids'].to('cuda'),
    OBS_LANGUAGE_ATTENTION_MASK: enc['attention_mask'].to(torch.bool).to('cuda'),
}
for _ in range(5):
    with torch.no_grad(): m.predict_action_chunk(ib)
torch.cuda.reset_peak_memory_stats()
t = bench('SmolVLA', lambda: m.predict_action_chunk(ib))
results['SmolVLA'] = {
    'params': sum(p.numel() for p in m.parameters())/1e6,
    'trainable': sum(p.numel() for p in m.parameters() if p.requires_grad)/1e6,
    'gpu_load': torch.cuda.memory_allocated()/1e9,
    'gpu_peak': torch.cuda.max_memory_allocated()/1e9,
    'latency_ms': t*1000, 'fps': 1/t,
}
del m; torch.cuda.empty_cache()

# === ACT ===
print('ACT...')
m = ACTPolicy.from_pretrained('lerobot/act_aloha_sim_transfer_cube_human').to('cuda').eval()

# ACT用对应数据集
act_ds = LeRobotDataset('lerobot/aloha_sim_transfer_cube_human', episodes=[0])
act_batch = next(iter(DataLoader(act_ds, batch_size=1)))
act_batch = {k: v.to('cuda') if isinstance(v, torch.Tensor) else v for k, v in act_batch.items()}
for _ in range(5):
    with torch.no_grad(): m.predict_action_chunk(act_batch)
torch.cuda.reset_peak_memory_stats()
t = bench('ACT', lambda: m.predict_action_chunk(act_batch))
results['ACT'] = {
    'params': sum(p.numel() for p in m.parameters())/1e6,
    'trainable': sum(p.numel() for p in m.parameters() if p.requires_grad)/1e6,
    'gpu_load': torch.cuda.memory_allocated()/1e9,
    'gpu_peak': torch.cuda.max_memory_allocated()/1e9,
    'latency_ms': t*1000, 'fps': 1/t,
}
del m; torch.cuda.empty_cache()

# === 报告 ===
print('\n' + '='*65)
print('  SmolVLA vs ACT 性能对比报告')
print('='*65)
hdr = f'  {"指标":<16} {"SmolVLA":>14} {"ACT":>14}  {"比值":>8}'
print(hdr); print('  ' + '-'*57)
rows = [
    ('参数量', 'params', 'M', '{:.0f}'),
    ('可训练参数', 'trainable', 'M', '{:.0f}'),
    ('GPU显存(加载)', 'gpu_load', 'GB', '{:.2f}'),
    ('GPU显存(峰值)', 'gpu_peak', 'GB', '{:.2f}'),
    ('推理延迟', 'latency_ms', 'ms', '{:.1f}'),
    ('帧率(FPS)', 'fps', '', '{:.1f}'),
]
for label, key, unit, fmt in rows:
    s = results['SmolVLA'][key]
    a = results['ACT'][key]
    ratio = s/a if a > 0 else 0
    print(f'  {label:<16} {fmt.format(s)+unit:>14} {fmt.format(a)+unit:>14}  {ratio:>7.1f}x')

print('\n  总结:')
if results['SmolVLA']['latency_ms'] < results['ACT']['latency_ms']:
    print(f'    ACT 快 {results["ACT"]["latency_ms"]/results["SmolVLA"]["latency_ms"]:.1f}x')
else:
    print(f'    SmolVLA 快 {results["SmolVLA"]["latency_ms"]/results["ACT"]["latency_ms"]:.1f}x')
print(f'    SmolVLA 多 {results["SmolVLA"]["params"]/results["ACT"]["params"]:.1f}x 参数')
print('='*65)
json.dump(results, open('/tmp/benchmark.json','w'), indent=2)
print('\n✅ 报告: /tmp/benchmark.json')
