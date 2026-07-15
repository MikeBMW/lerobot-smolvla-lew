# 模型训练验收清单 · 小芳检查项

> 等待 web 训练报告后逐项验证

## 检查流程

```python
# 1. 加载训练后模型
model = load_model(weights_path)

# 2. 标准输入测试
batch = {
    "observation.state": torch.randn(1, 14),
    "observation.images.top": torch.randn(1, 3, 480, 640),
}

# 3. 推理验证
action = model.select_action(batch)
assert action.shape == (1, 1, 7)  # ACT/SmolVLA/LeWorld
assert isinstance(action, torch.Tensor)

# 4. 部署到 Orin
rsync -avz weights/ nvidia@192.168.23.10:~/models/
```

## 各模型验收标准

| 模型 | 输入 | 输出 | 验收工具 |
|:---:|:---|:---|:---:|
| ACT 51.6M | 14D关节+3×480×640 | 7D动作 | Mac MPS 42ms |
| SmolVLA 450M | 14D关节+3×480×640 | 7D动作 | Mac MPS 300ms |
| GR00T 1.5B | 14D关节+多视角图像 | 7D动作+轨迹 | 4090 |
| VLA Touch | 14D+图像+触觉4×4 | 7D动作+力控 | Orin |
| LeWorldModel | 当前状态+动作 | 预测下一状态 | Mac 186ms |
