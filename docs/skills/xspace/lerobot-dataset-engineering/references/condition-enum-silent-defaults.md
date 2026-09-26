# 条件/枚举字段被"静默降级"写成常量 (2026-09-26 实测, skill_ctx 全 0 根因)

> 症状: 数据集里 `skill_ctx` 24 维**只有 dim13=1, 其余恒 0** (等于没有技能/阶段条件);
> 训练不报错、loss 正常, 但"阶段条件化"从头到尾没生效 —— 典型**静默数据缺陷**。

## 1. 根因链 (代码定位 + 数据双证)

```python
# tools/l5_plan_and_gen.py (生成器)
stg = stage_l[t] if t < len(stage_l) else None
_si = STAGES.index(stg) if stg in STAGES else 0          # ← 未识别 → 静默归 0
_sk = np.zeros(24, dtype=np.float32); _sk[13 + _si] = 1.0
```
而引擎 trace 侧 (state_space_sim_real.py) 写的是**带前缀**的阶段名:
```python
tr["stage"].append(stage if self.sched.stage() in stage else f"阶段 {self.sched.stage()}")
# 实测值是 "阶段 接近" / "阶段 对位" ...
```
⇒ `"阶段 接近" in ["接近","对位",...]` **永远 False** ⇒ 每帧都取 0 ⇒ 全数据集同一个 one-hot。
另一层: 引擎真源是 **8 阶段**(含"完成"), 生成器的 `STAGES` 只有 7 个 ⇒ 即便没前缀, "完成" 也会落到 0。

**与 MoE 门控是同一反模式**(见 `mixture-of-experts-architectures`
`references/stage-coverage-silent-swallowing.md`): 未识别的枚举 → 静默降级成索引 0。
本仓库已出现两次, 评审时按"**枚举映射必须有显式 fallback**"逐处排查。

## 2. 修法 (归一化 + 显式未知槽)

```python
STAGES8 = STAGES + ["完成"]                       # 引擎真源 8 阶段
STAGE_UNKNOWN_SLOT = len(STAGES8)                 # 独立槽 (13+8=21, 24 维里留得下)

def stage_index(stg):
    if stg is None:
        return None
    t = str(stg).strip()
    for pre in ("阶段 ", "阶段", "stage ", "Stage ", "STAGE "):
        if t.startswith(pre):
            t = t[len(pre):].strip()
    if t in STAGES8:
        return STAGES8.index(t)
    if t in _STAGE_ALIAS:                          # planner.py 的 取料/运输/扫码/对准/检测/拔出/分拣
        return STAGES8.index(_STAGE_ALIAS[t])
    return None                                    # ★ 不再 return 0
```
调用处未识别 → 写 **独立未知槽 + 计数**, 并打印诊断行:
```python
_si = stage_index(stg)
if _si is None:
    _si = STAGE_UNKNOWN_SLOT; _unrecognized[0] += 1
...
print("   skill_ctx 诊断: %d 帧 · 不同阶段 one-hot %d 种 · 未识别阶段 %d 帧%s"
      % (len(sk_a), _uniq, _unrecognized[0], "  ⚠️ 仍为常量!" if _uniq <= 1 else "  ✅ 阶段条件已生效"))
```

## 3. 验证 (独立读 h5, 6/6 通过)

1. 重新生成一个小数据集 (`l5_plan_and_gen.py --n 1 --steps 60`)
2. **独立读 h5 统计**: `kinds = len({tuple(np.round(r,3)) for r in skill_ctx})` —— 修后 3 种
   (接近/对位/下降), 修前 1 种; 热点维落在 `13..20` 且**不含未知槽 20** (说明归一化生效)
3. 旧数据对照仍为 1 种 ⇒ 差异来自生成器修复, 不是读取口径变化
4. 工具 `tools/verify_skill_ctx.py` 即此三判据 (6/6)

## 4. 通用检查清单 (生成器产出后必做)

- 任何"条件/上下文"列: 先算 **不同取值的种类数** 与**每维 std**; 只有 1 种 = 条件没生效
- 字符串枚举字段: 打印**真实取值的 repr**(带前缀/大小写/别名会静默不匹配), 别只看变量名
- 枚举 → 索引映射: **禁止 `else 0`**; 用独立未知槽 + 计数 + 打印, 让缺陷可见
- 修生成器后: 老数据集不重写(保持可追溯), 新数据集带诊断行, 报告里写明"哪个数据集是修前/修后"
