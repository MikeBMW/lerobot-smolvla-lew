# 标定数据 → YOLO 训练: 数据组织 / 引擎训练入口 / 解释器·数据源·device 三收口

> 2026-09-17 实测沉淀。老倪: 「标号的数据在哪里? 怎么组织 yolo 训练? 在模型引擎功能页, 有 YOLO检测的训练配置,
> 你看看怎么运行」。全部结论都是代码级 + 真跑取证。
> 配套: `references/console-restart-discipline-and-yolo-annot-fixes-2026-09-17.md` (标定窗两个真 bug + 类别口径 +
> 重启纪律) · 取证脚本 `scripts/verify_annot_drag_relabel.py`。

## 1. 数据在哪 / 怎么组织 (两句说清)

- **原始落盘** = `data/yolo_annot/sessions/<会话>/{frames,labels,session.json}` +
  `annotations.jsonl` (追加式审计流水: 像素框 + 类别 + 来源 + 帧龄, **不改历史**) + `meta.json`(会话清单/张数)。
- **训练唯一入口** = `data/yolo_annot/dataset/{images,labels}/{train,val}` + `data.yaml` + `stats.json`,
  由「📦 构建数据集」(`tools/yolo_annot_dataset.py --build`) 从 sessions 生成 ——
  **直接拿 sessions 去训是错的**, ultralytics 只认 data.yaml。
- 实测 6 张 → `train=6 val=6 框=6 类别=['peg']`, 体检 `✅ 通过` 同时报 **2 对同 md5 重复图**
  (标定员连点两次保存) ⇒ 有效样本 4 张。**重复图体检会抓, 别忽略那条 ⚠️。**
- ⚠️ 小样本 `val` 复用 `train` (`stats.json: val_overlap_train=true`, 工具显式标注) ⇒
  **此阶段 mAP 不可信, 只证管线跑通**; 要真精度得 100+ 张、覆盖不同位置/光照/朝向。
- 构建后可先看 `dataset/stats.json` (类别分布/会话来源/note) 再决定要不要补标。

## 2. ⚠️ 模型引擎页的「YOLO检测 训练配置」点了不会跑 —— 入口不可达

`tools/gui/simulink_module.py` 的 `on_train` 里**确实有**这条分支:
```python
if policy == "yolo":
    return self._train_yolo_detector(steps=steps)
```
但 **全仓 `grep -c '"policy": "yolo"' = 0`** —— 真训练节点一律是
`("system", "🚀 X 训练", {"policy": "act"|"smolvla"|…, "steps": N})`, 而 YOLO 行只有
`🎯 YOLO 感知开关` / `🎯 YOLO 目标检测` / `📐 2D→3D 解算` / `🔌 State Adapter`,
**没有训练节点** ⇒ 这个分支从界面**根本到不了**。
老倪看到的"训练配置"是 `🎯 YOLO 目标检测` 节点右键的**通用** steps/batch/lr 对话框
(`on_train_config`), 它只往该节点 params 里写 steps —— **没有任何训练会消费它**。

**判断法 (两条 grep, 别猜)**:
```bash
grep -n '"policy": "yolo"' tools/gui/simulink_module.py      # 0 命中 = 入口没接上
grep -n '("system", "🚀'   tools/gui/simulink_module.py      # 看真有哪些训练节点及各自 policy
```

**处置**: 要在这页点起来, 必须**新增一个训练节点**
`("system", "🚀 YOLO 训练", {"policy": "yolo", "steps": N, ...})` ——
节点构成属架构改动 (会影响模型引擎页布局/节点数), **先跟老倪确认再动**, 别擅自加。
「训练步数 steps」对 YOLO = **epoch 数** (`epochs = int(steps)`), 正式训 100 起, 默认 50。
**当前可用入口** = 视频流窗口的「🚀 训练 YOLO」(同一条 `tools/yolo_annot_train.py` 命令, 已实测跑通)。

## 3. 训练实现的三处收口 (通用铁律, 不止 YOLO)

凡是"引擎里的按钮 → 拉起外部训练脚本"这类实现, **解释器按能力探测、数据源按存在性解析、日志打真实值**;
写死任何一个都会变成"按钮点了没反应 / 跑了错的东西但日志看着正常"。

| 项 | 旧实现 (错) | 正解 |
|---|---|---|
| 解释器 | 写死 `~/lerobot-venv/bin/python` —— 实测该 venv **没有 ultralytics** ⇒ 一点必报"ultralytics 未安装" | **按能力探测**: `gui-venv311/bin/python` (ultralytics 8.4.126) → `~/lerobot-venv/bin/python`, 用 `py -c 'import ultralytics'` 判定; 都不行才显式报错并说明候选 |
| 数据源 | 写死仿真 `data/yolo_peg` | 有 `data/yolo_annot/dataset/data.yaml` → **真机标注(默认走这条**, 现场唯一真数据) + `tools/yolo_annot_train.py --base auto --imgsz 640`; 否则退仿真 + `train_yolo.py --imgsz 480`。环境变量 `SS_YOLO_DATA=<dir>` 可强制指定 |
| device | `train_yolo.py` 默认 `--device cpu`, 而日志硬编码写 "4060 GPU" (**实际在跑 CPU**, 自己骗自己) | 按 `torch.cuda.is_available()` **现探**再传 `--device`; 日志必须打**实际**解释器 / 数据源 / epoch 数 / 权重输出路径 |

真机数据走 `yolo_annot_train.py --base auto` 的理由: `--base auto` 会挑**现有仿真权重**做域适应微调
(仿真权重在真机 0 检出, 微调才是正路), 训练后还带**真推理验证**。

## 4. 实测 (引擎将要执行的同一条命令)

```
cd ~/lerobot-smolvla-lew && gui-venv311/bin/python -u tools/yolo_annot_train.py \
    --data data/yolo_annot/dataset --root data/yolo_annot --epochs 2 --imgsz 640 --base auto --name <name>
```
- 环境: `CUDA:0 NVIDIA GeForce RTX 4060` ✅ · ultralytics 8.4.126 · torch 2.7.1+cu128
- 模型: 73 层 / **3,005,843 参数** / 8.1 GFLOPs
- 权重落 `runs/detect/outputs/yolo_annot/<name>/weights/best.pt`
  —— ⚠️ **ultralytics 会给 project 自动加 `runs/detect/` 前缀**, 别按传进去的 project 路径去找
- 训练后真推理验证: val 6 张 → **0 框** (只训 2 轮 + 6 张近同姿态 = 正常"没学会", **不是管道故障**;
  判"管道通没通"看的是 完成日志 + best.pt 落盘 + 逐图验证行都打出来了)
- 冒烟产物建议清掉 (`runs/detect/outputs/yolo_annot/engine_smoke`), 别混进正式对比

## 5. 报告口径 (老倪会问)
- 先说 **数据现状的实数**: 几张 / 几个会话 / 有效几张(去重) / 类别分布 / 多少张进 train/val。
- 再说 **管线通没通** (命令 + GPU + 参数量 + 权重路径 + 验证行), 最后才说**精度还不可信及原因**
  (样本少 + val=train)。**别把"管线跑通"说成"模型可用"。**
