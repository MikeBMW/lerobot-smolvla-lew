# 真机数据 L2「边干边学」自动学习闭环 (sim → real 泛化)

> 老倪 2026-09-18: 「机器人正常插拔光模块的过程中自动学习数据, 完成 sim to real 的泛化过程。
> 状态空间的「🔀 推理/训练」节点选『🎯 真机数据 L2 训练』, 点运行即可根据真实数据训练。」
>
> 实现: `tools/ss_l2_autolearn.py`(闭环后端) + `tools/gui/l2_autolearn_panel.py`(回显面板)
> + `tools/gui/simulink_module.py`(三态模式开关 / ▶运行分派) + `tools/yolo_annot_dataset.py`(数据集红线)
> 取证: `tools/ss_l2_autolearn_selftest.py`(22 项断言) · `tools/gen_l2_autolearn_evidence.py`(GUI 11 项)

---

## 一、三环结构 (谁在什么时候动)

```
机器人正常插拔 (人示教/L4直驱, 只读旁路)
        │
        │  环1 在线采集 (常驻, 每 3s 探一次)
        │    新鲜帧门 → 姿态多样性门 → md5 去重 → 落帧 + 真值侧车(TCP/四元数/关节/六维力/夹爪/阶段)
        │                         │
        │                         ├─ 有标签 → sessions/auto_<ts>/  (annotator=auto:kinematic | auto:pseudo)
        │                         └─ 无标签 → sessions/pending_<ts>/ (annotator=auto:pending, **不进训练集**)
        ▼
  环2 触发 (新样本 ≥ K=12 张, 或 距上轮 ≥ T=20min 且有新样本) → 一轮学习:
       建数据集(去重 + auto 强制 train + pending 排除 + 体检)
         → 训练 (基座 = 在役权重, 独立 systemd 单元)
         → 训练后**新采真机帧同口径对照** (在役 vs 新)
         → 有提升才上在役 (指针**原子**切换 + sha256 前后留痕) ; 无提升按纪律不上默认档
        ▼
  环3 人工介入 (控制台「输入图像」窗口): 人工标注/修正 → annotator=human → 构成 val 与门槛裁决集
```

## 二、闸门与红线 (写死在代码里, 违背即停机)

| 红线 | 实现 | 为什么 |
|---|---|---|
| 不拿旧帧冒充实时 | `cam_rs.png` age 必须 ∈ [0, 3s]; **负帧龄拒用** (mtime 在未来=时钟被回拨) | 现场时钟回拨事故教训 |
| 帧要有内容 | 灰度 std ≥ 5 (与引擎同口径) | 半张/黑帧不进库 |
| 样本要有多样性 | 与上一张已收样本 TCP 位移 ≥ 8mm 或 转角 ≥ 3° 或阶段变化才收 | 机器人静止时相邻帧几乎相同, 只靠 md5 会让域适应数据永远是 1 张 |
| 不重复刷数据 | 同 md5 帧拒收 (最近 40 张指纹) | 重复帧会同时污染 train/val |
| **自动标注只进 train** | 构建数据集时 `is_auto → sp="train"` 强制; `stats.auto_in_val` 必须 0 (审计脚本另证) | val 是交付门槛的裁决集, 自动标注进 val = 自证循环 |
| **无标签帧不当负样本** | 无标签 → `annotator=auto:pending`, 构建时整会话排除 (`stats.n_pending_excluded`) | 在役权重低置信漏检的帧里其实有目标, 当"背景"进训练 = 教模型"光模块=背景", 反向伤害 |
| 几何真值拒算 | 标定未就绪 (`real_cam_calib.json ready=false`) → `autolabel_kinematic` 直接拒算并回传 gap | 不编造几何 |
| 抓取门 | 几何标签只在"抓取成立"时段发 (夹爪状态/阶段名); 无法判定 → 不发几何标签 | 不给"没夹住"的帧发标签 |
| 未证明提升不上线 | 判定只看**训练后新采真机帧**的同口径对照; 检出率↑ 或 (持平且 conf 均值 +0.02) 才算提升 | 老倪门槛; 训练内 mAP 不作为证据 |
| 0 检出不许上线 | `improved = new.peg_rate > 0 and ...` | 防止"没检出=没框=没损失"的假提升 |
| 训练脱离控制台 cgroup | GUI 侧一律 `systemd-run --user --collect --unit ...` | 控制台一退, 旧实现把训练连带杀 (实测死在第 51 轮) |
| 只读真机 | 只读 `cam_rs.png` + `state_*.jsonl` (旁路 tap 落盘), 零下行/零自启 | Orin 侧红线 |
| 上线原子性 | `symlink(tmp) → os.replace(tmp, live)` + `models/yolo_peg_live.history.jsonl` 留痕 (from/to/sha256/actor) | 读者要么旧要么新, 不会读到空指针 |

## 三、交付门槛判定 (代码位置: `decide_improved`)

```
improved = (new.peg_rate > 0) and (Δ检出率 > 0 or (Δ检出率 == 0 and Δconf 均值 > 0.02))
Δ 来自 yolo_live_eval: 训练后新采 N 张新鲜真机帧, 同 imgsz(640) / 同 conf(0.25) / 同帧来源
```
上线动作: `switch_live_pointer(best)` → 指针切换 + 写历史。**未提升不动指针**, 产物留在 `runs/detect/outputs/yolo_annot/<run>/weights/`。

## 四、操作 (画布 + 命令行)

画布 (状态空间):
1. 双击「🔀 训练/推理」节点 → 循环切换 `📷 推理 → 🚀 训练 → 🎯 真机数据 L2 训练`
   (节点标题即时显示当前模式, 指示圆点: 蓝=推理 / 绿=训练 / 橙=真机L2)
2. 选到 `🎯 真机数据 L2 训练` 后点 **「▶ 运行」** → 打开「🎯 真机数据 L2 训练」面板并自动起常驻闭环
   (双击「📦 数据源」运行环境节点同源入口)
3. 面板: `▶ 开始边干边学` / `🔁 立即跑一轮` / `⏹ 停止` / 训练轮数 / 新样本触发数 / `有提升→自动上在役` 开关
   面板显示的每个数字都来自产物文件 (state.json / verdicts.jsonl / stats.json / 指针), 缺口如实报

命令行:
```bash
python3 tools/ss_l2_autolearn.py --status              # 状态 (样本/指针/最近判定/常驻/标定/相机)
python3 tools/ss_l2_autolearn.py --collect-once        # 采 1 张 (过闸门)
python3 tools/ss_l2_autolearn.py --collect --minutes 30
python3 tools/ss_l2_autolearn.py --cycle --epochs 60   # 跑一轮完整闭环
python3 tools/ss_l2_autolearn.py --daemon --trigger-n 12 --trigger-min 20
python3 tools/ss_l2_autolearn.py --stop
```
自检: `tools/ss_l2_autolearn_selftest.py` (22 项) · `tools/gen_l2_autolearn_evidence.py` (GUI 11 项)

## 五、目录与产物

| 路径 | 内容 |
|---|---|
| `data/yolo_annot/sessions/auto_*/` | 自动标注样本 (帧 + 标签 + truth.jsonl 真值侧车) |
| `data/yolo_annot/sessions/pending_*/` | 待人工标注帧 (不进训练集) |
| `data/yolo_annot/dataset/` | 构建产物 (train/val 硬链接 + data.yaml + stats.json + truth.jsonl) |
| `runs/detect/outputs/yolo_annot/<run>/` | 每轮训练产物 (weights/best.pt + results.csv) |
| `reports/yolo_live_eval_<run>.json` | 同口径对照原始结果 (before/after 都在) |
| `/home/ubuntu/zmax_data/l2_autolearn/` | 闭环工作区: `state.json` 心跳/计数 · `verdicts.jsonl` 每轮判定 · `runs/cycle_*/` 证据包 · `autolearn.log` |
| `models/yolo_peg_live.pt` | **在役单点指针** (只读方: L2 旁路 / GUI 叠加 / 训练 `--base auto`) |
| `models/yolo_peg_live.history.jsonl` | 上线历史 (from/to/sha256/actor) |

## 六、当前实测状态 (2026-09-18 15:06 首次真实一轮)

- 建集: `train 24 / val 2` · 图 34 · 样本真值 18 · 体检 0 错误
- 训练: 30 轮 → `runs/detect/outputs/yolo_annot/auto_0918_150616/weights/best.pt`
- 同口径对照 (12 张训练后新采真机帧): 在役 12/12 conf 0.295 vs 新 12/12 conf 0.295 → **Δ=0 → 不上默认档** (纪律生效, 指针未动)
- 证据包: `/home/ubuntu/zmax_data/l2_autolearn/runs/cycle_0918_150616/`

## 七、已知缺口 (要变强的唯一瓶颈 = 数据 + 标定)

1. **相机标定未就绪** (`models/real_cam_calib.json ready=false`, 缺 K 与 T_base_cam) → 现在只能走
   **伪标注** (在役权重 conf ≥ 0.35); 几何真值标注 (机器人当标定物, `real_autolabel.py`) 拒算。
   补: `tools/calib_real_cam.py --intrinsics <棋盘图目录>` → `--handeye <图片+tcp json 目录>` + 人工量一次 `plane_z`。
2. **val 只有 2 张人工标注** → mAP 不能当泛化证据, 交付话术只能到"本工位可检出"。
   要覆盖不同姿态/位置/光照: 再标 100+ 张 (每个姿态 3~5 张), 走控制台「输入图像」窗口人工标注 (它同时是门槛裁决集)。
3. 伪标注阈值 0.35 是当前折中 (在役权重实测 0.25~0.91 波动): 高阈值→少标不标错, 低阈值→引入噪声标签。
   标定就绪后应优先走几何真值路, 伪标注退为兜底。
4. 当前 `prod_stage` 为空 (`{"states": []}`) → 抓取门只能用夹爪/阶段名判, 阶段信息缺时几何标签不发 (如实)。
   产线阶段话题接上后, 采集可精确到"插拔过程的哪些段"。
