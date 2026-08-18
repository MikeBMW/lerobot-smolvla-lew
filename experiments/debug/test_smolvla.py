import torch
from lerobot.policies.smolvla import SmolVLAPolicy
from lerobot.datasets import LeRobotDataset
from torch.utils.data import DataLoader
from lerobot.utils.constants import OBS_LANGUAGE_TOKENS, OBS_LANGUAGE_ATTENTION_MASK
from transformers import AutoTokenizer

m=SmolVLAPolicy.from_pretrained('lerobot/smolvla_base').cuda().eval()
tok=AutoTokenizer.from_pretrained(m.config.vlm_model_name)

ds=LeRobotDataset('lerobot/pusht',episodes=[0])
b=next(iter(DataLoader(ds,batch_size=1)))
b={k:v.cuda() if isinstance(v,torch.Tensor) else v for k,v in b.items()}
gt=b['action'][:7].squeeze(0)

enc=tok('push the block',return_tensors='pt',padding='max_length',max_length=48,truncation=True)
ib={
    'observation.images.camera1':b['observation.image'],
    'observation.images.camera2':b['observation.image'],
    'observation.images.camera3':b['observation.image'],
    'observation.state':b['observation.state'],
    OBS_LANGUAGE_TOKENS:enc['input_ids'].cuda(),
    OBS_LANGUAGE_ATTENTION_MASK:enc['attention_mask'].to(torch.bool).cuda(),
}

with torch.no_grad(): a=m.predict_action_chunk(ib)
a7=a.squeeze(0)[:7]

print(f'pred: [{a7.min().item():.0f},{a7.max().item():.0f}]')
print(f'GT:   [{gt.min().item():.0f},{gt.max().item():.0f}]')
print(f'MSE:  {torch.nn.functional.mse_loss(a7,gt).item():.0f}')
del m;torch.cuda.empty_cache()
