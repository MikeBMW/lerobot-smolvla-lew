# lerobot 标准自定义 Policy 封装模板 (left_right 双脑架构, 2026-08-10 实测)

把 Z-MAX 自研模型 (双脑: 左脑MLP动作 + 右脑WM判断) 封装成 lerobot 标准 policy 的完整骨架。
复制此模板 + 改模型名/结构即可。已实测通过 (提交 8ed1c9e8, src/lerobot/policies/left_right/)。

## 目录结构

```
src/lerobot/policies/<name>/
├── __init__.py                        # 导出三件
├── configuration_<name>.py            # config dataclass (注册 "name")
└── modeling_<name>.py                 # Policy 类 + 子模块
```

factory.py 两处注册 (缺 config import 会 `Unknown policy name`):
```python
# ① 顶部 import 触发 register_subclass
from .left_right.configuration_left_right import LeftRightConfig
# ② policy 分支
elif name == "left_right":
    from .left_right.modeling_left_right import LeftRightPolicy
    return LeftRightPolicy
```

## configuration_<name>.py (必须带 fallback)

```python
"""Z-MAX <name> 配置"""
from __future__ import annotations
from dataclasses import dataclass, field

try:
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.configs.types import NormalizationMode
    _HAS_LEROBOT = True
except ImportError:
    _HAS_LEROBOT = False
    from enum import Enum
    class NormalizationMode(Enum):
        IDENTITY = "identity"; MEAN_STD = "mean_std"; MIN_MAX = "min_max"
    @dataclass
    class PreTrainedConfig:
        n_obs_steps: int = 1; chunk_size: int = 7; n_action_steps: int = 7
        normalization_mapping: dict = field(default_factory=dict)
        @classmethod
        def register_subclass(cls, name):
            def deco(c): return c
            return deco
        def __post_init__(self): pass

@PreTrainedConfig.register_subclass("left_right")
@dataclass
class LeftRightConfig(PreTrainedConfig):
    n_obs_steps: int = 1
    chunk_size: int = 1
    n_action_steps: int = 1
    left_hidden: int = 512
    right_hidden: int = 256
    normalization_mapping: dict = field(default_factory=lambda: {
        "observation.state": NormalizationMode.MEAN_STD,
        "action": NormalizationMode.MEAN_STD})
    input_features: dict = field(default_factory=dict)
    output_features: dict = field(default_factory=dict)

    # ── lerobot PreTrainedConfig 抽象方法实现 (5+2个, 缺1个即抽象类无法实例化) ──
    @property
    def action_delta_indices(self) -> list[int]:
        return list(range(self.n_action_steps))
    @property
    def observation_delta_indices(self) -> list[int]:
        return list(range(self.n_obs_steps))
    @property
    def reward_delta_indices(self) -> list[int]:
        return [0]
    def validate_features(self, input_features, output_features):
        return input_features, output_features
    def get_optimizer_preset(self):
        return {"optimizer_cls": "torch.optim.AdamW", "lr": 1e-4}
    def get_scheduler_preset(self):
        return {"scheduler_cls": None, "kwargs": {}}
```

## modeling_<name>.py 要点

```python
class LeftRightPolicy(PreTrainedPolicy):
    config_class = LeftRightConfig   # ① 缺 → TypeError "must define 'config_class'"
    name = "left_right"              # ② 缺 → TypeError "must define 'name'"

    def __init__(self, config=None):
        config = config or LeftRightConfig()
        self.config = config
        super().__init__(config)     # ③ ⚠️ 必须先 super 再赋模块!
        obs_dim = 39; act_dim = 4    # 从 config.input_features/output_features 读
        self.left = LeftBrainMLP(obs_dim, act_dim, config.left_hidden)
        self.right = RightBrainWM(obs_dim, act_dim, config.right_hidden)

    # ④ 3 个抽象方法 (缺1个 → TypeError "abstract methods")
    def reset(self): pass
    def get_optim_params(self):
        return {"params": list(self.left.parameters()) + list(self.right.parameters())}
    def predict_action_chunk(self, observation, **kwargs):
        obs = observation["observation.state"].float()
        if obs.ndim == 3: obs = obs[:, -1]
        with torch.no_grad():
            return self.left(obs).unsqueeze(1)  # [B, 1, act_dim]

    def forward(self, batch, **kwargs):
        obs = batch["observation.state"].float()
        if obs.ndim == 3: obs = obs[:, -1]
        act = batch["action"].float()
        if act.ndim == 3: act = act[:, -1]
        pred_act = self.left(obs)
        if self.training and "next_state" in batch:
            pred_next, pred_cont = self.right(obs, act)
            self._right_loss = nn.functional.mse_loss(pred_next, batch["next_state"].float()[:, -1])
        return {"action": pred_act.unsqueeze(1)}

    def compute_loss(self, batch, **kwargs):
        out = self.forward(batch, **kwargs)
        act = batch["action"].float()
        if act.ndim == 3: act = act[:, -1]
        loss = nn.functional.mse_loss(out["action"].squeeze(1), act)
        rl = getattr(self, "_right_loss", None)
        if rl is not None: loss = loss + 0.5 * rl
        return {"loss": loss}

    # save/from_pretrained: config.json + model.pt
    def save_pretrained(self, save_directory, **kwargs):
        os.makedirs(save_directory, exist_ok=True)
        json.dump({"type": "left_right", "left_hidden": self.config.left_hidden, ...},
                  open(os.path.join(save_directory, "config.json"), "w"), indent=2)
        torch.save({"left": self.left.state_dict(), "right": self.right.state_dict(),
                    "obs_dim": self.left.obs_dim, "act_dim": self.left.act_dim},
                   os.path.join(save_directory, "model.pt"))
    @classmethod
    def from_pretrained(cls, pretrained_path, **kwargs):
        cfg = json.load(open(os.path.join(pretrained_path, "config.json")))
        policy = cls(LeftRightConfig(left_hidden=cfg.get("left_hidden", 512), ...))
        data = torch.load(os.path.join(pretrained_path, "model.pt"), map_location="cpu",
                          weights_only=False)  # ⑤ 含 numpy → 必须 weights_only=False
        policy.left.load_state_dict(data["left"]); policy.right.load_state_dict(data["right"])
        return policy
```

## 验证清单 (全过才算封装成功)

```python
from lerobot.policies.factory import _get_policy_cls_from_policy_name
cls = _get_policy_cls_from_policy_name('left_right')  # 必须返回 LeftRightPolicy
p = cls(LeftRightConfig(input_features={'observation.state':[39]}, output_features={'action':[4]}))
batch = {'observation.state': torch.randn(4,1,39), 'action': torch.randn(4,1,4)}
p(batch)['action'].shape                    # [4,1,4]
p.compute_loss(batch)['loss']               # 标量
p.predict_action_chunk({'observation.state': torch.randn(2,1,39)}).shape  # [2,1,4]
p.save_pretrained(tmp); p2 = cls.from_pretrained(tmp)
p.eval(); p2.eval()                         # ⚠️ 必须 eval 再比权重
torch.allclose(p(batch)['action'], p2(batch)['action'])  # True (训练模式 dropout → False, 非bug)
```

## 实测踩坑记录

| 报错 | 根因 | 修法 |
|---|---|---|
| `Class X must define 'config_class'` | 缺类属性 | `config_class = XConfig` |
| `Class X must define 'name'` | 缺类属性 | `name = "x"` |
| `Can't instantiate abstract class XConfig without ... 'action_delta_indices'...` | PreTrainedConfig 抽象方法未实现 | 实现 6 个 (见上) |
| `Can't instantiate abstract class X without ... 'get_optim_params','predict_action_chunk','reset'` | PreTrainedPolicy 抽象方法未实现 | 实现 3 个 (见上) |
| `cannot assign module before Module.__init__()` | self.left 赋值在 super() 前 | super().__init__(config) 提前 |
| `Unknown policy name 'x'` | factory.py 只加了 policy 分支, config 未 import 触发注册 | 顶部 import config |
| `WeightsUnpicklerError: Unsupported global: GLOBAL numpy._core...` | torch.load 默认 weights_only=True 拒绝 numpy | `torch.load(..., weights_only=False)` |
| save/load 后权重不一致 | dropout 训练模式随机 | 对比前 `p.eval()` |

## 后续可选
- 状态机集成进 select_action (接近→抓取→抬起→转移→插入 编排, 见 SKILL.md 双脑+状态机节)
- 用 `lerobot_train --policy left_right` 标准训练替代手写脚本
