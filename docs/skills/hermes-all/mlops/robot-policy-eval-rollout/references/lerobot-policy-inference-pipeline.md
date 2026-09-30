# LeRobot 策略推理管道 + 续训 resume 坑 + VLA 闭环实测（2026-09-10）

## 一、官方推理管道（验证单帧能力，别手搓 batch）

```python
import sys, torch
sys.path.insert(0, "<repo>/src")
from lerobot.datasets.lerobot_dataset import LeRobotDataset
from lerobot.policies.smolvla_lew.modeling_smolvla_lew import SmolVLALewPolicy
from lerobot.policies.factory import make_pre_post_processors

ckpt = "<repo>/outputs/train/smolvla_lew_v8/checkpoints/last/pretrained_model"
policy = SmolVLALewPolicy.from_pretrained(ckpt)          # 需 config.json 有 "type"
policy.eval().to("cuda")
pre, post = make_pre_post_processors(policy.config, pretrained_path=ckpt)

ds = LeRobotDataset("data/smolvla_peg_v8", root="<repo>/data/smolvla_peg_v8")
item = ds[i]
item["task"] = "metaworld 光模块插拔"                     # ★ 必带, 传 int 会 TypeError
batch = pre({k: (v.unsqueeze(0) if hasattr(v, "unsqueeze") else v)
             for k, v in item.items()})
act = policy.select_action(batch)
act = post(act) if post is not None else act               # 反归一化
gt  = item["action"].numpy()[:4]
```

**实测对比（同一 ckpt）**：直喂原始帧/state 误差 **0.35**；走官方 preprocessor **0.15**。
差值全是归一化——不修会误判"模型没学会"。

## 二、config.json 的 `type` 键（续训后必查）

训练会重写 `checkpoints/last/pretrained_model/config.json`，**丢掉 `type`**。
`from_pretrained` 抛：

```
draccus.parsers.decoding_choice: ParsingError: Expected a dict with a 'type' key for ...
```

修复（1 行）：

```python
import json
p = "<ckpt>/config.json"
d = json.load(open(p))
if not d.get("type"):
    d["type"] = "smolvla_lew"
    json.dump(d, open(p, "w"), indent=1)
```

## 三、续训（resume）三坑

```bash
lerobot_train --config_path=<ckpt>/train_config.json    # ★ 必须用 "=" 号!
```

1. **`--config_path=` 必须等号**：`cfg.validate()` 用 `parser.parse_arg("config_path")`
   在 `sys.argv` 里按 `--config_path=` 前缀查找；空格分隔写法找不到 →
   "A config_path is expected when resuming"
2. **train_config.json 里 `resume: true`**：训练存档时写的是 false，须手动改
3. **`output_dir` 用同一个目录**才能真正 resume（换新目录=从头训）；
   改 `steps` 到目标总步数（如 10000 → 30000 即续训 20000 步）
4. 备份/复制 checkpoint 目录很慢（1.2GB 模型），能原地 resume 就别复制

## 四、VLA 闭环注入引擎（模型当执行者）

引擎每帧：

```python
if os.environ.get("SS_L3") == "1":
    n = int(os.environ.get("SS_L3_EVERY", "4"))
    if cache is None or step % n == 0:      # 降频缓存 (VLM ~0.6s/帧)
        cache = l3_forward(visual39)
    if cache is not None:
        u_ff = np.concatenate([np.clip(cache[:3], -0.5, 0.5), [u_ff[3]]])   # xyz 换模型, gripper 留状态机
```

`l3_forward`：`env.render()` → `np.ascontiguousarray` → `/255.0` → 与训练同尺寸 →
拼 `{"observation.image", "observation.state", "task"}` → preprocess → `select_action`。

## 五、闭环实测（seed 104，同一布局）

| 配置 | 结果 |
|---|---|
| 解析链基线 | ✅ 343 步成功 |
| L3 模型执行 (SS_L3=1) | ❌ 1000 步失败 |

单帧误差小（xyz 0.01~0.08）+ 闭环失败 = **covariate shift**（分布偏移），不是接入 bug。
判定顺序：先验单帧误差 → 小则结论是分布偏移 → 解法是 DAgger 迭代（用模型 rollout 数据再训）。

## 六、gripper 二值回归（架构性缺陷，加步数无效）

| 训练步数 | 抓取段动作误差（gripper 真值 1.0）|
|---|---|
| 10000 步 | 0.31（预测 ≈ 0.0）|
| 30000 步 | 0.30（预测 ≈ 0.0）|

MSE 回归 0/1 目标天然收敛到均值 ≈ 0 → 模型"该抓时不抓"。
平均误差 0.1505 → 0.1599（无改善）。**加步数/加参数不解决**。
务实方案：模型管 xyz + 状态机管 gripper 时机；根治需给 gripper 单独分类头（BCE）或 DAgger。

## 七、另一条独立线：引擎规则侧成功率（对比基线，勿与模型成绩混淆）

同一轮做的是**解析链**（硬编码规则 + 状态机）的插入成功率调优，与模型无关：

- 28 seed 广撒：**32.1% → 46.4%**（13/28）
- 有效修复：① insert 步数上限 500→1000（深孔布局重抓余量）② 插入深处夹持误判
  （peg 顶孔壁致 `|o[4:7]-x-off0|>2cm` → 误判"夹持丢失回退"把插好的拔出）→ 深层强制判定为夹持
  ③ 遇阻后 site-推算差 >5mm → 回接近重抓刷新锁存（>8mm 守卫太松，peg 滑 7.4mm 不触发）
- 汇报时必须标注"**引擎侧成绩，非模型**"——避免把规则调参说成模型能力
