# 五层记忆系统落地实录 (2026-09-19)

一次完整的"整体优化多层级记忆系统"实录: 老倪给出五层定义 → 盘点已有资产 → 补最顶层宏观层 →
接入引擎 → 复核既有修复是否生效 → 阶梯台取证 → 得到"贡献 vs 缺口"的诚实结论。

---

## 0. 需求原话

> "全面优化 多层级记忆系统。L4 是工作记忆, L3 是流程记忆, L2 是肌肉记忆,
> 总装记忆对应大模型的 Qwen 顶层宏观记忆, 与状态空间工程的记忆保持同步。你来整体优化记忆系统"

## 1. 先盘点, 别急着写代码 (这次发现系统比预想完整)

盘点顺序(全部先读后写):
```bash
find . -name '*memor*' | grep -vE '.git/|__pycache__'      # 找模块/数据/文档
for kw in 工作记忆 流程记忆 肌肉记忆 宏观记忆 总装记忆; do    # 找各层关键词落点
  grep -rl "$kw" --include='*.py' --include='*.md' tools/ src/ docs/design; done
grep -nE '^def node_ss_mem|^def node_ss_global' src/lerobot/memory/mem_nodes.py   # 画布节点
```

盘点结果(值得记的结论): **L2/L3/L4/总装/全局中枢都已经有了**, 缺的只有最顶上的"LLM 宏观层"。
已存在的模块: `potential_field.py`(三层势场 + MemoryLayerBridge) · `global_memory.py`(共享编码 +
二态意图语法 attached/detached + 联合视图 + plan) · `memory_store.py` · `memory_graph.py` ·
`motor_hub.py` · `intent_decoder.py` / `target_decoder.py` · `mem_nodes.py`(画布节点 7 个)。

数据: `data/muscle_memory.json`(冠军轨迹, 键 = `seed|stage`, 值含 `n_ok/champ_u/champ_x/io`) ·
`data/assembly_memory.json`(`runs` 台账) · `data/shared_memory.json`(`l2/l3/l4/meta/links/motor`) ·
`data/memory_layers.json`(逐层开关)。

> 教训: **先盘点再动手**。若一上来就"从头设计记忆系统", 会重复实现四层已有资产。

## 2. 顶层宏观层 (`src/lerobot/memory/macro_memory.py`)

```python
class MacroMemory:
    def __init__(self, path="data/macro_memory.json", llm_url=None)   # llm_url 缺省读 SS_MACRO_LLM_URL
    def uplink(self) -> dict      # 读下层真实数据 → 能力画像/失败归因/语义知识; 返回本次增量
    def downlink(self) -> dict    # 宏观知识 → 分阶段建议 (确定性推导, 无 LLM 也可用)
    def sync(self) -> dict        # uplink + downlink + save (一键)
    def save(self) -> str         # tmp + os.replace 原子写
    def advise(self, stage)       # 供画布/分层消费
    def report(self) -> str       # 人能读的宏观报告
    def selftest(self) -> int     # 0 = 通过
    def _qwen_summarize(self, runs)   # 仅当 llm_url 存在; urllib 直调 OpenAI 兼容端点
```

store 结构: `version / knowledge / capability / diagnosis / advice / seen / meta`。

**能力画像由真实 run 统计推**(不做无根据结论):
```python
cap["overall"]        = {"runs": n, "success": ok, "rate": ok/n}
cap["insert_depth_mm"] = {"n","min","max","mean"}
cap["layers"]         = {"L2_segments", "L3_flows", "L4_predicts", "links"}
```

**失败归因带证据字段**(每条 `issue/evidence/suspect/check`):
例 `{"issue":"全臂零成功","evidence":"40 局 runs 全 done=False",
     "suspect":"执行层出力不足而非几何不可达","check":"解析链对照成功率"}`。

**下行建议按段区分** — 与总装仲裁策略保持一致:
接触段(`下降/插入/完成`)提示"提高记忆场权/修夹爪咬合"; 自由段提示"查 L3 相位与 L4 现场几何"。

### 自检 4 项 (可直接照抄的判据)
```
① 幂等: 第二次 sync 的 fresh == 0
② 只读下层: sync 前后 assembly/shared/muscle 的 mtime 不变
③ 下行建议覆盖 ≥7 阶段
④ 原子落盘: save() 后文件存在
```

### 引擎挂点
`run()` 尾部 `_write_shared_memory(tr)` **之后**:
```python
if os.environ.get("SS_MACRO") == "1":
    try:
        from lerobot.memory.macro_memory import MacroMemory
        self._macro_sync = MacroMemory().sync()
    except Exception as _me:
        self._macro_sync = {"err": f"{type(_me).__name__}: {_me}"}   # 失败不阻塞主流程
```
零回退实测: `SS_MACRO=0` → `hasattr(sim, "_macro_sync") == False`;
`SS_MACRO=1` → 属性出现且值为 `{'uplink': {...}, 'downlink_stages': 8}`。

真数据首跑: `15 局 · 成功率 100% · L2 681 段 · L3 40 条 · L4 40 条 · 链接 60 条`,
无 LLM 端点 → `llm=False` 如实标注。

## 3. 既有修复的复核 (四个坑的实锤数字)

复核前状态: `data/memory_layers.json` **四层全 0**(被主动关掉), 注释写着
"L2 势场与模型动作反向抵消 (合成≈0.0001) 导致全链卡在'接近'"。

排查顺序(先量方向, 再改公式):
1. 量 406 段冠军轨迹 `cos(Δx, champ_u)`: 中位 **+0.995 ~ +0.999**, **0 段反向**
   ⇒ 冠军轨迹没问题, 排除"轨迹存反了"。
2. 查阶梯台文档记录的**两个真根因**:
   - **喂错坐标系**: 桥喂 `peg_head()`, 而冠军轨迹记的是夹爪位置 `self.x = obs[0:3]`,
     同 seed 差 `(0.017, 0.054, 0.176)m` = **176mm** ⇒ 势场在自己坐标系之外求梯度。
     换 `obs[0:3]` 后 `d_perp` 0.1358m → **0.0002~0.02m**, 相位 SK01→SK03→SK07 正常推进。
   - **夹爪通道缺失**: `blend_action` 只混 `u[:3]`, `u[3]` 永远来自模型 ⇒ 救援时夹爪不闭合,
     工件没被抓起 (探针: 1000 步工件位置一动不动)。修法: `champ_u`(4 维) + `grip_at(x)` 按弧长
     取当拍冠军夹爪指令, 同一个 `w` 混进 `u[3]`。
3. 第三个坑(桥新建引擎实例改写场景): `ObstacleField.from_engine` 不传 `geom` 会新建第二个
   `RealStateSpaceSim` 并 reset, 而 metaworld 底层 sim 进程内共享 ⇒ 正在跑的场面被改写
   (实测 peg 瞬移 Δ=[+1.2mm,−17mm,0]m), 所有涉 L4 的 A/B 失真。
   修法: `from_real_data(..., use_engine_geom=True, geom=self.geom)`。

## 4. 阶梯台复核结果与解读

命令:
```bash
cp data/memory_layers.json /tmp/gates_bak.json     # 先备份
gui-venv311/bin/python -u tools/mem_ladder_integration.py \
    --arms off,L2,L23,L234 --seeds 104 --steps 1200 --disturbs none
cp /tmp/gates_bak.json data/memory_layers.json     # 跑完恢复
```

结果 (v5-ep4 权重 · seed 104 · 1200 步 · 无干扰):

```
臂      成功   插入mm    距成功线(65mm)   调用/步
off     0/1    194.0     +129.0          1.0
L2      0/1    185.6     +120.6          1.0
L23     0/1    183.3     +118.3          1.0
L234    0/1    182.9     +117.9          1.0
```

对照 09-14 (v4-ep2 权重) 同 seed 同臂:

| 臂 | 09-14 | 09-19 | Δ |
|---|---|---|---|
| off | 649.3 | 194.0 | **−455.3** |
| L2 | 431.6 | 185.6 | −246.0 |
| L234 | 419.1 | 182.9 | −236.2 |

闸门: `N1`(L2 准确性) ✅ · `N2`(L23 ≥ L2) ✅ · `N5`(零搜索, candidate=0, 调用/步 1.0) ✅ ·
`N6`(std 0) ✅ · `N3`/`N4` **缺数据**(本次只跑无干扰档, 不是真失败)。

**结论(诚实三段)**:
1. 记忆层**不再反向抵消** — 四臂单调正向, 每层叠加改善 8~11mm ⇒ 坐标系 + 夹爪通道两个修复生效, 可安全重开。
2. **但记忆层救不了场** — 总贡献 11mm vs 缺口 118mm ⇒ 瓶颈在基线本身 (off 194mm), 记忆层是锦上添花。
3. 主因是**模型权重** — 换 v5-ep4 后基线自身就前进了 455mm。

## 5. 可复用的检查清单

- [ ] 动手前先盘点: 已有几层? 缺哪层? (别重复造)
- [ ] 上层只读下层: 用例断言下层文件 mtime 不变
- [ ] 幂等: 事件指纹去重, 重复 sync 的 fresh == 0
- [ ] LLM 诚实: 无端点 → 规则归纳 + `llm=False`
- [ ] 落盘原子: tmp + `os.replace`
- [ ] 逐层开关默认关; 零回退硬证据 = 关闭时新属性不存在
- [ ] 报"抵消"之前先量方向 (cos 分布), 再动公式
- [ ] 阶梯台逐层叠加看**单调性**, 跑前备份开关、跑完恢复
- [ ] 汇报给"贡献 vs 缺口"比值, 别把小幅正向说成有效提效
- [ ] 缺数据的闸标"缺数据", 不当回退报
