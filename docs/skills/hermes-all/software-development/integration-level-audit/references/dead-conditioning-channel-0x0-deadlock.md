# 可学通道「0x0 死锁」— 参数在位、指标自报已用、贡献却恒零 (2026-09-14 实锤)

INTACT-JEPA v6「记忆条件通道」`skill_ctx` (L2 原子技能 → 动作头) 案例。这条坑的形态是
**假接入里最隐蔽的一种**: 文件在位、前向形状对、训练日志 `skill_ctx_used=1.000`、
推理诊断 `skill_used=1.0`, 一路"看起来全接上了", 唯独通道**贡献恒等于 0 且永远学不动**。

## 症状清单 (命中任意一条就该查)

1. **消融逐位相同**: 同一权重、同一批真帧, 只改"看不看得见该通道" (喂真值 vs 喂全零),
   两遍输出 `torch.equal` **逐位相同**、MAE 相同到小数点后 16 位 → 该通道输出恒 0。
2. **ckpt 里新增参数训了多轮仍是全零**:
   ```python
   sd = torch.load(".../weights_epoch_3.pt", map_location="cpu")
   for k, v in sd.items():
       if "skill" in k:                      # 换成你的新通道前缀
           print(k, tuple(v.shape), float((v != 0).float().mean()))
   # intent_actor.skill_enc.3.weight  (32,32)  nonzero%=0.000  ← 训满 3 轮仍全零
   ```
   注意只看"新加的那一侧"没意义: 随机初始化的层天然 nonzero%=1.0 —— **零初始化的那层
   是否离开 0 才是判据**。
3. **梯度取证** (决定性, 直接调真模型真损失):
   ```python
   stats = model.action_nll(z, intent, prev_act, target, skill=skill_on)  # 真值
   stats["loss"].backward()
   print(float(enc[-1].weight.grad.abs().max()))        # 新通道末层
   print(float(net0.weight.grad[:, -k:].abs().max()))   # 入口层新列
   print(float(net0.weight.grad[:, :-k].abs().max()))   # 入口层老列 (对照组)
   # → 0.000e+00 / 0.000e+00 / 9.222e-01: 老能力在学, 新通道两侧梯度全 0
   ```
   形状细节: 训练侧 `previous_action` 是 `[B,T,A]` (Embedder 要 3D)、`skill` 是 `[B,T,K]`、
   `z/intent` 是 `[B,T,D]`; 推理侧才是 2D `[B,D]`。混用会报
   `permute(sparse_coo)` / `Tensors must have same number of dimensions: got 2 and 3`。

## 根因 (0×0 死锁)

为了让"暖启动 = 老模型逐位等价"(零回退), 常见做法是**把新通道的输出投影零初始化**。
若同时把**入口层的注册新列也置零**, 则:

```
E(s) 贡献 = 入口层新列 (全 0)  ×  末层输出 (零初始化 ⇒ 恒 0)  = 0
∂L/∂(末层) = (新列ᵀ·δ) ⊗ 输入 = 0        ← 乘的是全 0 矩阵
∂L/∂(新列) = δ ⊗ (末层输出)ᵀ  = 0        ← 乘的是全 0 向量
```
两侧同时为 0 ⇒ 谁也不会先离开 0 ⇒ **通道永久死亡, 训多少轮都一样**。
前向恒等 + 反向恒零, 所以所有"接上了"的表面证据都成立。

## 修法 (保留零回退, 但让梯度可通)

**只允许一端是零**, 另一端必须非零:

```python
# 入口层: 老列逐位复制(保住老能力) + 新列给**小随机**, 不要置零
_b = 1.0 / (new_w.shape[1] ** 0.5)
new_w[:, old_w.shape[1]:].uniform_(-_b, _b)
# 末层保持零初始化 → 暖启动输出仍逐位不变 (0 向量乘任意权重恒 0)
```
解冻后实测: 输出与解冻前**逐位相同** (零回退不破), `∂L/∂(末层)` 由 0 → **1.165e-01**;
真优化 5 步后 `|末层.weight|max` 0 → 0.002758, `loss(on)=11.25210 < loss(zero)=11.25257`。

配套: 写一个**无条件**的体检函数, 在 init 之后跑 —— 续训 (暖启动已有权重) 时会把
"两端全零"的死锁状态一并带过来, 这种自愈体检能让续训也活过来:

```python
def _break_skill_deadlock(model) -> bool:
    actor, enc = getattr(model, "intent_actor", None), None
    if actor is None or getattr(actor, "skill_enc", None) is None:
        return False
    enc, net0 = actor.skill_enc, actor.net[0]
    k = int(getattr(actor, "skill_emb_dim", 0) or 0)
    if k <= 0 or net0.weight.shape[1] <= k:
        return False
    with torch.no_grad():
        if float(enc[-1].weight.abs().max()) == 0.0 and float(net0.weight[:, -k:].abs().max()) == 0.0:
            net0.weight[:, -k:].uniform_(-1.0 / (net0.weight.shape[1] ** 0.5),
                                          1.0 / (net0.weight.shape[1] ** 0.5))
            return True
    return False
```

## 连带义务: 作废建立在死通道上的结论

死通道会让**判闸/消融实验给出"该通道无提升"的 ❌**, 那个 ❌ 是对一个恒零通道的正确描述,
**不是"模型学不会"的结论**。所以发现死锁后:
- 把该通道之前所有"无提升/塌缩"的判闸结果**标记作废**, 重训后重判 (本次: v6/v5/v6r2 全作废;
  其中 v5/v5r2 那批**根本没有该通道**, 它的 ❌ 是另一回事, 属真·能力不足, 别一起作废)。
- 不要把"指标自报 `used=1.0`"当接入证据 —— 它只证明"传进去了", 不证明"有贡献"。
  要证明有贡献, 只有两条: **消融输出不同** + **梯度非零**。
- 重训要**另起目录名** (v6r2 → v6r3), 旧 ckpt 留作"修复前"对照证据, 别原地覆盖。

## 数据侧别背锅 (先排除再修代码)

同一症状先查数据集那列是不是真值, 别急着改模型:
```python
f = h5py.File(H5, "r"); x = np.asarray(f["skill_ctx"][:])
print(x.shape, np.count_nonzero(x) / x.size, (np.abs(x) > 1e-8).mean(axis=0).round(3).tolist())
# (149100, 24) 0.2667 [.., 1.0, 0.826, 0.831]  ← 真值, 逐维非零, 不是零列
```

## 归档位置

- 修复提交: `INTACT-JEPA` 20a7791 (`fix(skill通道): 破除 0x0 死锁`)
- 取证脚本 (本机可复跑): `/home/ubuntu/INTACT-JEPA/tools/skill_deadlock_evidence.py`
- 会话纪要: `/home/ubuntu/l4_ab/V6R3_SKILL_DEADLOCK_FIX.md`
