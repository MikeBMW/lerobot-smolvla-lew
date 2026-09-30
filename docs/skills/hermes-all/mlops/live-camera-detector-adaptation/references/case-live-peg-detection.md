# 案例: 真机光模块实时检出闭环 (2026-09-18)

一次完整闭环的原始数据与命令, 供复用/对照。所有数字都来自真推理输出, 不是估算。

## 现场

- 相机: 生产工位 RealSense, 帧经 Docker 侧只读订阅落盘 `~/zmax_ss_remote/cam_rs.png` (640×480, ~10Hz)。
- 消费方: L2 旁路可视化 `tools/ss_yolo_on_real.py` (每 0.5s 取最新帧 → 检测 → 画框 PNG + JSON)。
- 标定数据: `data/yolo_annot` (会话层 `sessions/<会话>/{frames,labels}`; 类别只有 `peg` = 光模块)。
- 训练入口: `tools/yolo_annot_train.py`; 评测入口: `tools/yolo_live_eval.py` (本轮新增)。

## 基线 (17 张新鲜真机帧, imgsz 640, conf 0.25)

| 权重 | 检出帧 | conf mean / max |
|---|---|---|
| `runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt` (当时在役, 仿真域) | 0/17 | — |
| `.../yolo_peg/dr_mix/weights/best.pt` (DR 混训) | 0/17 | — |
| `.../yolo_annot/annot_0918_0711/weights/best.pt` (真机微调 10 轮) | 0/17 | — |
| `.../yolo_annot/annot_0918_0718/weights/best.pt` (真机微调 100 轮, **被 cgroup 连杀在 epoch 51**) | 17/17 | 0.649 / 0.706 |
| `.../yolo_annot/live_0918_0737/weights/best.pt` (本轮升级, 250 轮 + 去重) | 17/17 | **0.914 / 0.920** |

框 (真机帧, 静止工位): 约 41×115 px, 左上 ≈ (299, 24) — 细长竖直物体, 与"24cm 长光模块立在镜头前"一致。

## 关键命令

```bash
# 1) 基线评测 (自动采新鲜帧; 也可 --frames-dir 复用已冻结的评测集)
gui-venv311/bin/python tools/yolo_live_eval.py --frames 40 --imgsz 640 --conf 0.25 \
    --vis-dir reports/yolo_live_vis_before --out reports/yolo_live_eval_before.json

# 2) 建数据集 (含去重; 去重信息打在 stdout)
gui-venv311/bin/python -c "import sys; sys.path.insert(0,'tools'); \
  import yolo_annot_dataset as y; print(y.build_dataset(y.ROOT_DEFAULT, val_ratio=0.2))"

# 3) 训练 (独立 systemd 单元; 训练后自动跑真机帧对照)
gui-venv311/bin/python tools/yolo_annot_train.py --detached --epochs 250 --imgsz 640 \
    --batch 8 --patience 60 --name live_0918_0737 --base auto --live-frames 40
systemctl --user status yolo-annot-0918-073210 ; journalctl --user -u <unit> -f

# 4) 上在役 (单点指针) + 让实时管线生效
ln -sfn "$PWD/runs/detect/outputs/yolo_annot/live_0918_0737/weights/best.pt" models/yolo_peg_live.pt
systemctl --user restart ss-yolo-live
journalctl --user -u ss-yolo-live --since "-15s"     # 期望: ✅ 光模块(peg) conf≈0.9
```

判据行 (实时管线原样输出):

```
📷 cam_rs.png (real, age=0.09s) [640, 480] → 检出 1: peg=0.92  ✅ 光模块(peg) conf=0.92 box=[299,24,339,138]
```

## 训练数字

- 250 轮 · 0.9 分钟 (GPU 4060) · 18 样本 / 19 框 (去重后) · 1 类 (peg)
- val (4 张): 全检出, 平均 conf 0.929, mAP50 0.995
- 训练后真机帧对照 (新 vs 在役): conf 0.649 → 0.914 (+0.265) → 判定"有提升" → 上在役

## 证据包

`~/zmax_data/20260918_yolo_live_peq/`: MANIFEST.md · `yolo_live_eval_before.json` ·
`yolo_live_eval_live_0918_0737.json` · 画框图 (before/after) · `live_pipeline_annotated.png` ·
`yolo_detections.json` · `results.csv`。

## 本轮修掉的三个坑 (都在 SKILL.md 正文有对应条目)

1. GUI 起的训练被 cgroup 连杀 (100 轮 → epoch 51 静默死亡) → 改 `systemd-run --user --collect`。
2. 叠加框写进存档会污染训练集 → 保存用 `self._rgb_raw`, 画框只在显示副本上。
3. 旁路标注图非原子写 → 取证脚本 `cp` 到 0 字节的半张 PNG; 改 tmp+`os.replace`
   (并踩到 PIL `.tmp` 扩展名猜格式报错 → `im.save(tmp, format="PNG")`)。
