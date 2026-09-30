# REFERENCE_APPS 模板加/改节点 + 零回退取证 (2026-09-17: 模型引擎页加「🚀 YOLO 训练」节点)

归属: `simulink-flow-engineering`。本文件是"往画布模板里加一个节点并证明零回退"的完整配方。

## 数据结构 (别猜)

```python
REFERENCE_APPS = [ (应用名, node_specs, link_specs, layout), ... ]
# node_specs = [(type, name, params), ...]
# link_specs = [(src_idx, dst_idx, label?), ...]
# layout     = [[名字或"", ...] 每行]   ← 多行展开网格: 行=模型分支, 列=功能角色
```
`load_reference_app()` 里 `for i,(ntype,nm,params) in enumerate(node_specs): ... index_to_id[i]=n["id"]`
⇒ **link_specs 的索引 = node_specs 顺序**, 与 layout 无关 (layout 是按**名字**摆格子的网格;
同名出现在多行时每个 spec 各消费一个尚未使用的位置 `used.add(xy)`)。

## 三条静默坑 (都实测踩过)

1. **被跳过创建的节点, 索引存在但不能被连线引用**
   共享「🧩 结构条件」(无 `·` 后缀) 在 load 时被显式 `continue` 跳过 → `index_to_id` 里没有它
   ⇒ 写 `(2, 64, "训练")` 这种指向它的连线会被**静默丢弃**(不报错、日志也不提示, 只有对比结果时才发现"新增连线: []")。
   该画布里 🎯 YOLO 目标检测 = **索引 3**(不是 2)。**新加连线前先把 index→name 打出来核对源/目标索引**。

2. **`match_node` 取最长关键字 → 新节点名会被别人的裸关键字抢走**
   注册表里 `_reg("ss_yolo", ["YOLO", "目标检测"], ...)` 的裸 `"YOLO"`(4字) 比通用 `"训练"`(2字) 长
   ⇒ 「🚀 YOLO 训练」被派去跑**目标检测**而不是训练。
   修 = 给新节点**单独注册一个更长关键字**: `_reg("train_yolo", ["YOLO 训练"], "…", node_train)`(5字压过4字),
   **别去改别人的关键字**(会连带影响原节点)。

3. **分支可达性: 代码里有分支 ≠ 从界面到得了**
   `grep -c '"policy": "yolo"'` == 0 就是铁证 —— 引擎里 `_train_yolo_detector()` 写得再全,
   **没有任何节点传那个参数** ⇒ 永远走不到那段代码(用户"点不出训练")。
   加功能前先 grep 入口参数"有没有人真的设置它"; 同类孤儿还有"训练配置对话框挂在非训练节点上"
   (用户改了 steps, 但没有任何训练消费它)。

## 加节点步骤

1. **node_specs 末尾 append** 新节点 `(type, name, params)` → 旧索引全不变, 旧连线一条不受影响。
2. **layout** 在目标行/列把某个 `""` 换成新节点名(列位置对齐同类节点, 例如「训练/基准」列与 🚀 ACT 训练 同列)。
3. **link_specs** 追加连线, 源索引按上面"核对索引"一步确认(`(3, 新索引, "训练")`)。
4. 需要双击执行 → 在 `node_logic.py` 单独 `_reg` 长关键字(见坑 2)。

## 零回退取证配方 (老倪红线, 必做)

`REFERENCE_APPS` 是纯字面量 ⇒ **`ast.literal_eval` 直接解析, 不必起 Qt**:

```python
import ast, json
src = open("tools/gui/simulink_module.py", encoding="utf-8").read()
apps = None
for node in ast.parse(src).body:                      # 找 REFERENCE_APPS 的赋值
    if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "REFERENCE_APPS" for t in node.targets):
        apps = ast.literal_eval(node.value)
zoo = [a for a in apps if a[0] == "🔬 Model Zoo"][0]
nodes, links, layout = zoo[1], zoo[2], zoo[3]
baseline = {"nodes": [(i, n[1]) for i, n in enumerate(nodes)],
            "edges": [(nodes[f][1], nodes[t][1]) for f, t, *_ in links],
            "layout": layout}
json.dump(baseline, open("/tmp/zoo_before.json", "w"), ensure_ascii=False, indent=1)
```

改完再跑一次, 逐条断言:
① 旧 N 个节点 `索引→名字` **逐条不变** (切片比较 `now[:N] == before["nodes"]`)
② 旧连线**一条不少** —— 用 `Counter` 比**多重集**, **别按顺序比**(新连线可能插在中间, 顺序比较会假失败)
   `all(c_now[k] >= c_before[k] for k in c_before) and sum(c_now.values()) == sum(c_before.values()) + 1`
③ 节点数 == 旧 + 新增; 新节点在最末索引且 `params` 关键字段正确(policy 等)
④ layout **只有目标单元格变化**, 其余行逐条不变
⑤ 新节点名在 spec 与 layout 各恰好 1 处

**本次实测**: 65 节点 / 101 连线 vs 基线 64 / 100; 旧节点索引→名字逐条不变; 旧连线一条不少;
布局仅第 0 行第 10 列新增; 新节点名唯一 ✅。

## 派发链闭环验证 (节点名 → 语义 key → 业务方法)

```python
import node_logic
assert node_logic.match_node("🚀 YOLO 训练") == "train_yolo"      # 关键字没被抢
ck = {}
class FakeMod:
    def _log(self, *a, **k): pass
    def on_train(self, **kw): ck.update(kw); return (True, "stub")
node_logic.execute_node_logic(FakeMod(), {"name": "🚀 YOLO 训练",
                                         "params": {"policy": "yolo", "steps": 100}}, "验证")
assert ck.get("policy") == "yolo"                                 # 真的派发到训练且参数正确
```
实测收到 `{'steps': 100, 'batch_size': 8, 'lr': 1e-4, 'data_source': 'auto', 'policy': 'yolo'}` ✅

## 配套: 训练实现的三处口径修正 (同一节点一起改)

- **解释器**: 自动选**带 ultralytics 的那个 venv**(本仓 `gui-venv311`), 旧的硬编码 `~/lerobot-venv`
  实测**没装 ultralytics** → 一点就报错; 两个都不行要显式报原因, 不静默失败。
- **数据源**: 优先**真机标注** `data/yolo_annot/dataset`(走 `tools/yolo_annot_train.py --base auto` 域适应微调,
  imgsz 640), 否则回退仿真 `data/yolo_peg`(`train_yolo.py`, imgsz 480); 加环境变量 `SS_YOLO_DATA` 强制指定。
- **设备**: 旧实现在日志里写"4060 GPU"但参数走默认 `--device cpu` ⇒ **日志别说谎**: 用被选中的解释器
  `python -c 'import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)'` 判定后再决定传 `0` 还是 `cpu`。
