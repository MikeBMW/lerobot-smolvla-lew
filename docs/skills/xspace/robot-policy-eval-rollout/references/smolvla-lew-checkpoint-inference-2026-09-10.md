# smolvla_lew checkpoint 加载/接入避坑 (2026-09-10)

补充 `lerobot-policy-inference-pipeline.md`(官方管道 / resume 坑 / SS_L3 闭环注入)。
本文件记的是**同一件事的失败面与替代路径**, 以及"训练完为什么 GUI 没变化"的排查口径。

## 一、config.json 的 `type` 键是两面坑 — 别只按一种修

- 症状 A(管道 reference 第二节): 缺 `type` → `from_pretrained` 报
  "Expected a dict with a 'type' key".
- 症状 B(本次实测): **有** `type` → `SmolVLALewConfig.from_pretrained(ckpt)` 抛
  `draccus.utils.DecodingError: The fields `type` are not valid for SmolVLALewConfig`.
- **别退回"手动 dataclass 构造"**: config.json 的 `input_features` 是 dict, 直接
  `SmolVLALewConfig(**d)` 会让 `FeatureType` 仍是 dict →
  `AttributeError: 'dict' object has no attribute 'type'`(卡在 `config.validate_features()`)。

**稳妥加载路径(不依赖 from_pretrained 的 config 解析)**:
```python
import json, tempfile, draccus
d = json.load(open(f"{ck}/config.json")); d.pop("type", None)      # 有就剔除
tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump(d, tf); tf.close()
cfg = draccus.parse(SmolVLALewConfig, config_path=tf.name)        # 正确反序列化 FeatureType
policy = SmolVLALewPolicy(cfg)
from safetensors.torch import load_file
miss, unexp = policy.load_state_dict(load_file(f"{ck}/model.safetensors"), strict=False)
```

## 二、`missing` 一大把不是加载错误

- 本次 `missing=197, unexpected=0` — 全是 `model.smolvlm.vlm.*`(**VLM 主干**),
  构造时已从 HF 加载(SmolVLM2-500M-Video-Instruct, 日志 "Loading weights: 489/489"),
  训练 checkpoint 只存可训练部分。
- **判定口径**: `missing` 全在 vlm 主干 + `unexpected=0` = 正常; 别据此认为"模型没载入"。

## 三、推理输出可能不是 tensor — 比较前必须提取 action

`policy.select_action(...)` / postprocessor 可能返回 dict(EnvTransition), 直接 `.detach()`
会 `AttributeError: 'dict' object has no attribute 'detach'`:
```python
def _extract_action(x):
    if isinstance(x, dict):
        for k in ("action", "actions", "Action"):
            if k in x:
                x = x[k]; break
        else:
            x = next(v for v in x.values() if hasattr(v, "detach"))
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x, dtype=float).ravel()[:4]
```

## 四、引擎帧钩子探针法 = 接入第一步(零风险, 不动控制路径)

引擎自带帧钩子, 不必手搓 obs:
```python
sim = RealStateSpaceSim(seed=104, vision=False, mode="insert", log=lambda *a: None)
def sink(sim, act, o):
    img = np.asarray(Image.fromarray(np.asarray(sim.env.render())).resize((128,128), Image.LANCZOS))
    frames.append((img, np.asarray(o[:39], np.float32), np.asarray(act, np.float32).ravel()[:4]))
sim._frame_sink = sink
sim.run(max_steps=900)
```
图像 128×128 / state `o[:39]` / act = 引擎专家动作 — 与 `collect_simreal_vla_data.py` 的采集
格式**完全同款**(训练数据就是这条钩子采出来的), 所以模型输入同构。
收集一轮后逐帧喂模型 → 与专家动作对比 = "模型在真实分布上的动作一致度"。

**实测(v9 = `checkpoints/030000`, seed104 344 帧, 采样 80 帧)**:
`xyz MAE 0.168 · gripper MAE 0.615` — 与管道 reference 第六节"gripper 学不准(0.30)"方向一致,
xyz 也还没到能独立闭环的水平。已沉淀为 `tools/probe_smolvla_lew.py`。

## 五、⚠️ "训练完了 GUI 画面一点没变" = 训练产物没有推理入口(不是训练失败)

用户会把这个当"训练没效果"来问。事实: 三个显示位置都与新模型无关 —
- 画布 ▶运行 = 引擎解析链(前馈 MLP + 状态机 + 肌肉记忆); L4 档 = L4Demo 演示控制器;
- 🎥 操作视频 = **预生成的 mp4**(`tools/gen_insert_video.py` 的双脑 MLP rollout),
  不重新生成就永远是旧视频;
- 🧭 3D 视图 = 当次运行的引擎轨迹。

**排查口径**: `grep -rn "smolvla_lew\|checkpoints/last" tools/gui/*.py` — 若没有加载 checkpoint
做推理的脚本, 就是"没接入"。接入 = 管道 reference 第四节的 `SS_L3=1` 闭环注入,
或先用第四节探针法出对比数据(零风险)。
