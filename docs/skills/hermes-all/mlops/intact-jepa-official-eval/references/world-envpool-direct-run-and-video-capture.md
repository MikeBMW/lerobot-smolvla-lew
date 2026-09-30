# 不依赖数据集直跑 env 录视频 (World / EnvPool 路径, 2026-09-18 实测)

场景: 老倪要"**用原版权重跑 X 机器人, 把视频发我看看**", 而该域数据集还没下完/太大 (reacher 完整
`reacher.h5` ≈ **98.9GB**, 压缩包 22GiB) 或只是要一段画面证据 —— 不必等数据集, 走官方 env 直跑。

## 为什么不能裸 `gym.make`

```python
env = gym.make("swm/ReacherDMControl-v0")   # ✗ obs 是 Box(state 向量), 无 pixels
obs, info = env.reset()                     # 拿不到图像, model.get_action 直接抛
```
正确入口是官方 `swm.World` (= 引擎同款封装, 自动加 pixels + 标准化 obs dict):
```python
import stable_worldmodel as swm
world = swm.World("swm/OGBCube-v0", num_envs=1, image_shape=(224, 224))  # add_pixels=True 默认
```
env id 从 `config/eval/<task>.yaml` 的 `world:` 段取 (`swm/ReacherDMControl-v0` · `swm/OGBCube-v0` …),
**别猜** (`import stable_worldmodel` 会注册 gym 环境; 漏了 import 报 `Namespace swm not found`)。

## EnvPool 是 batch API, 观测在 info 里

```python
_, obs = world.envs.reset(seed=42)      # ← 返回 (None, info); **obs 就是 info dict**
# obs keys 实测: pixels (1,1,224,224,3) uint8 · observation (1,1,6) · action · reward · step_idx …
out = world.envs.step(act)              # (None, reward, terminated, truncated, info) 同构
obs = out[4]
```

## 喂模型的 5 个必修点 (每一个都实报过错)

1. **必须是 torch.Tensor** —— 传 numpy 会得到
   `ValueError: 'int' object is not callable` (模型内部 `info["pixels"].size(0)`; ndarray 的 `.size` 是属性)。
2. **只转数值键** —— obs dict 里有 str/object 字段 (如 `id`)。`np.asarray(v).dtype.kind in "fiub"` 才转。
3. **动作历史初值含 NaN** → `_coerce_action_history` 抛 `non-finite values`。转完对非有限值
   `torch.nan_to_num(tn, nan=0.0, posinf=0.0, neginf=0.0)`。
4. **像素 NHWC → NCHW** —— `(B,T,H,W,C)` 且末维 ∈ {1,3,4} 时 `permute(0,1,4,2,3)`, 否则 ViT 报
   `expected 3 (channels) but got 224`。
5. **goal 是硬需求** —— `goal_displacement` 模型的 `get_action` 抛 `KeyError: 'goal'`。直跑没有数据集采样的
   目标帧, 就得显式构造 (占位/末帧) 并**如实标注 goal 来源**, 不能装作和官方口径一样。

## chunk 列数 ≠ env 动作维 (易广播错)

模型出 `(horizon, action_dim)` = pusht/reacher `(8,10)` · cube `(8,25)`;
env 的动作空间是 **2/5** 维 → 取前 N 维:
```python
act = model.get_action(obs_t, horizon=8)
a_np = act.detach().cpu().numpy().reshape(1, -1, act.shape[-1])
env_act = a_np[:, 0, :env.action_space.shape[0]]     # 不裁 → RuntimeError (2,) vs (10,)
```
`action_dim` 必须**从 checkpoint 反推** (`action_encoder.patch_embed.weight` 的形状), **别跨域抄 config.json**。

## 后端: 按域试 (EGL 不是万能的)

| 域 | 后端 | 现象 |
|---|---|---|
| reacher (DMControl) | `MUJOCO_GL=egl` ✓ | 正常 |
| cube (OGBench) | **`MUJOCO_GL=osmesa`** | EGL 下 `TypeError: 'NoneType' object is not callable` (GLContext 析构), 换 osmesa 通过 |

## 录视频: 用 `sitecustomize` 挂钩, 不改官方代码

不想 fork `eval.py` 时, 把 hook 做成启动期自动注入:
```
/tmp/intact_patch/sitecustomize.py   → PYTHONPATH=/tmp/intact_patch
```
里面包 `WorldModelPolicy.get_action`/`model.get_action`, 每步把 `info["pixels"]` 的**最后一帧**追加到全局
list, `atexit` 落 `np.save`。然后照常跑官方脚本 (`eval_official.sh`) —— 钩子跟着走。

**致命小坑**: 钩子的 `print()` 必须写 **stderr**。stdout 会被 glfw 的版本探测
`eval(out)` 解析 → `SyntaxError: invalid syntax` (报错信息里能看到你自己的日志行被当代码)。
另外「只在成功时存帧」要显式加 (`if bool(tr['done'][-1]): np.save(...)`), 否则循环多 seed 时
最后一跑 (失败) 会把成功帧覆盖掉。

## 帧/视频自检 (我看不到画面, 只能用数值说话)

```python
f.mean(), f[:, :, :, 0].mean() vs [1] vs [2]   # 通道均值: DMControl 偏蓝灰(R<G<B), 全同色=渲染坏
np.abs(np.diff(f.astype(float), axis=0)).mean()  # 帧间差 >0 才是在动
len(np.unique(f[50].reshape(-1,3), axis=0))      # 唯一色数 >500 才算有内容
```
抽帧/拼图用 PIL + `ffmpeg -framerate N -i f%04d.png -c:v libx264 -pix_fmt yuv420p`
(`imageio` 缺编码器时直接报 `expected bytes, NoneType` —— 别在这上面耗)。

## 数据集仍然要下的时候

- HF 清单: `quentinll/lewm-<task>` (`https://hf-mirror.com/api/datasets/quentinll/lewm-reacher/tree/main`),
  `reacher.tar.zst` 22.12 GiB → 解压 `reacher.h5` **98.9 GB** (磁盘闸门按 4.5× 压缩包算)。
- 官方 eval 期望的**路径名不同**: `datasets/dmc/reacher_random.h5` (不是 `datasets/reacher/reacher.h5`)
  → 解压后要建 `datasets/dmc/` 并对齐文件名。
- `tar: Unexpected EOF in archive` + 解压出的 h5 明显偏小 = **下载未完成**(假损坏), 不是文件坏;
  续传补到 `size` 与 HF 清单一致再解压 (判据见 `dataset-archive-provisioning`)。
