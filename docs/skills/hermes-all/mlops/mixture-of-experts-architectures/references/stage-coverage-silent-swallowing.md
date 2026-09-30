# 专家数 ≠ 阶段数 → 静默吞阶段 (2026-09-26 实证根因 + 修法 + 四条验收)

> 场景: 阶段专家 MoE, 引擎状态机 8 阶段, MoE 只建了 7 专家。用户报"E0 吞 4 阶段 / E4E5 饿死", 但没有报错、loss 正常、诊断矩阵也看不出。

## 1. 机制(从代码定位, 不是猜)

引擎状态机阶段表(`cognition.py`, `calibration_layer.py`, `manifold_layer.py` 同源):
`["接近","对位","下降","抓取","抬起","转移","插入","完成"]` —— **8 个**
MoE 侧(`stage_moe_backbone.py`): `STAGES = ["接近",...,"插入"]` —— **7 个**

引擎走到"完成"时, 喂给门控的 `stage_p` 是 8 维 one-hot 的**最后一位**; 模型只认 7 维 ⇒ 该行和 = 0
⇒ 命中 `uniform 1/n` 兜底 ⇒ hard top-1 `argmax` **恒取 E0**。

```
if route == "prior":
    g = stage_p / stage_p.sum(1, keepdim=True).clamp_min(1e-6)
    g = torch.where(g.sum(1, keepdim=True) > 0.5, g,
                    torch.full_like(g, 1.0 / self.n_experts))   # ← 均匀兜底 = 静默故障源
...
idx = g.argmax(1)     # 均匀 1/7 → argmax 恒 0 → E0 吃掉一切未识别阶段
```
⇒ 结论: **门控里任何 `uniform` 兜底, 在 hard top-1 下都等价于"永远选 E0"**。越靠后/越罕见的阶段越容易被吞,
而诊断集若本来就缺那些阶段, 则永远测不出来。

## 2. 修法(向后兼容, 老 ckpt/老数据逐位不变)

```python
STAGES_ENGINE   = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]   # 引擎真源
STAGE_TO_EXPERT = {"接近": 0, "对位": 1, "下降": 2, "抓取": 3,
                   "抬起": 4, "转移": 5, "插入": 6, "完成": 6}      # 显式覆盖表(可多对一)

# __init__: 显式兜底专家(env 可配) + 路由统计
self.default_expert = int(os.environ.get("SS_MOE_DEFAULT_EXPERT", 6))
self.route_stats = {"frames": 0, "unrouted": 0, "per_expert": [0] * n_experts}
self._proj_cache = {}

# forward: 先把任意维 stage_p 投影到专家空间(按 device 缓存 P, 别每帧重建)
if stage_p.shape[1] != self.n_experts:
    P = torch.zeros(stage_p.shape[1], self.n_experts, device=stage_p.device)
    names = STAGES_ENGINE if stage_p.shape[1] == len(STAGES_ENGINE) else STAGES
    for i, nm in enumerate(names[:stage_p.shape[1]]):
        P[i, STAGE_TO_EXPERT.get(nm, min(i, self.n_experts - 1))] = 1.0
    stage_p = stage_p @ P                      # 8 维(含"完成") → 7 维 (完成→E6)

rowsum = stage_p.sum(1, keepdim=True)
g = stage_p / rowsum.clamp_min(1e-6)
unr = (rowsum.view(-1) <= 0.5)
if bool(unr.any()):                            # 不再静默: 显式兜底 + 计数
    fb = torch.zeros_like(g); fb[:, self.default_expert] = 1.0
    g = torch.where(unr.view(-1, 1), fb, g)
    if self.training or os.environ.get("SS_MOE_ROUTE_STATS"):
        self.route_stats["unrouted"] += int(unr.sum().item())     # .item() 会同步 GPU → 默认仅训练时统计
```
`route_stats["per_expert"]` 在 hard 分支用 `torch.unique(idx, return_counts=True)` 累计 → 直接给取证。

## 3. 验收四条(本次实测 6/6 通过)

| # | 判据 | 做法 | 通过标准 |
|---|---|---|---|
| ① | **修前对照** | 用"均匀 1/7 兜底"老逻辑喂缺失阶段 one-hot | hard 路由落 **E0**(复现症状, 证明确是它) |
| ② | **修后全覆盖** | 逐阶段喂 one-hot 进真模型 | `argmax == STAGE_TO_EXPERT[阶段]`, 阶段数/阶段数 全中 |
| ③ | **零回退** | 原有维数路径 vs "纯归一化" | `torch.allclose(..., atol=1e-7)` **逐位相同** |
| ④ | **不再静默** | 全零 `stage_p` | 落 `default_expert` 且 `unrouted` +1(**需先开 `SS_MOE_ROUTE_STATS=1`**, 否则计数被省 GPU 同步的开关挡住 → 取证会假失败) |
| ⑤ | **同源 A/B 不回退** | 门控诊断 + 引擎真跑 | 单射性/有效专家/熵与修前一致; 引擎 `rc=0` (`MOE_BYPASS_DONE`) |

## 4. 通用教训(评审清单)

- 建 MoE 前先把**引擎/任务的阶段枚举**与 `STAGES` **逐项 diff**; 两套阶段表共存(7 与 8)本身就是 bug 源。
- 门控的每个兜底分支: **显式指定专家 + 可观测计数**, 禁止 `uniform` 兜底(等价于恒选 E0)。
- 诊断集必须覆盖**全部**阶段(含终态/罕见段), 否则"吞阶段"永远测不出来。
- 修改门控后必做**逐位零回退校验**(老维数路径 `allclose`), 否则会静默改掉已上线 ckpt 的行为。
- 想省 GPU 同步而给统计加开关时, **取证脚本要先打开那个开关**(本次就因此先出现一条假失败)。
