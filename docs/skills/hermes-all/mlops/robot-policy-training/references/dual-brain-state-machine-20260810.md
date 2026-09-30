# 双脑+状态机 完整插拔方案 — 2026-08-10 突破记录

## 成果
- 抓起 **8/8**（官方专家 7/8）· 插入 **7/8**（与专家持平）
- 首个学习架构完整解决 peg-insert 插拔（此前 5 视觉大模型 BC 全 0/8、RL 全 0/6）
- 文件：`tools/train_full_pipeline.py`（训练+评估一体）· 权重 `outputs/rl_peg/full_pipeline.pt`
- 流程时序：接近(32帧)→抓取(45帧)→抬起(9帧)→转移(38帧)→插入(1帧)=125帧

## 架构
```
左脑 MLP:   39D obs → 4D 动作 (3层512, ExpertMLP结构)  — 连续动作生成
右脑 WM:    obs(39)+act(4) → next_obs 预测 + contact概率 — 抓取时机判断 (acc 1.00)
状态机:     接近→抓取→抬起(+8cm)→转移(容差5cm)→插入→完成
```
- 右脑 = LeWorldModel 思路的轻量 state 版（39D+4D→next obs + sigmoid contact 头）
- W2-VLA 论文映射：结构条件=W2接口（相对向量），右脑=未来腕部预测，状态机=W2-CoT 阶段编排

## 版本演进（每个版本都是教训）
| 版本 | 改动 | 结果 |
|---|---|---|
| 双脑 v1（train_dual_brain.py）| MLP偏置接近+contact夹持 | 抓起 3-5/8（首个突破 0）|
| 纯解析接近 | delta 方向满速/半速/微调 | 0/8（**MLP偏置接近才是关键**）|
| 状态机+学习模型 | 接近→对位→下降→抓取（z_err<0.01）| 0/8 卡抓取（z 永远贴不住）|
| 状态机+专家动作 | 验证状态机阶段识别 | 抓起 8/8 插入 7/8（状态机本身对）|
| **双脑抓取+状态机插入** | 双脑抓取条件+状态机抬起/转移/插入 | 抓起 8/8 插入 0/8（转移卡）|
| **抬起 +5cm→+8cm, 力 0.5→0.8** | 避开台面 | **抓起 8/8 插入 7/8** 🎉 |

## 关键代码逻辑（train_full_pipeline.py）
```python
# 状态转移 (APPROACH=0, GRASP=2, LIFT=4, TRANSFER=5, INSERT=6, DONE=7)
if state == ST_APPROACH:
    if d_hp < 0.06 and contact_p > 0.5: state = ST_GRASP   # 双脑抓取条件
elif state == ST_GRASP:
    if peg[2] - peg_z0 > 0.02: state = ST_LIFT             # peg 真被抓起来
elif state == ST_LIFT:
    if peg[2] > peg_z0 + 0.08: state = ST_TRANSFER         # 抬 8cm 避开台面
elif state == ST_TRANSFER:
    if abs(peg[0]-hole[0]) < 0.05 and abs(peg[1]-hole[1]) < 0.05: state = ST_INSERT
elif state == ST_INSERT:
    if d_ph < 0.05: state = ST_DONE

# 动作执行
if state == ST_APPROACH:
    act[:3] = act[:3]*0.3 + np.clip((peg-hand)*2.0, -1, 1)  # MLP 偏置接近
    act[3] = -1.0                                            # 张开 (负值=张开!)
elif state == ST_GRASP:
    act[:3] = act[:3] * 0.1                                   # 位置锁定
    act[3] = 0.6                                             # 夹持 (正值=夹持!)
elif state == ST_LIFT:
    act[:3] = [0,0,0.8]; act[3] = 0.6
elif state == ST_TRANSFER:
    d_xy = hole[:2] - peg[:2]
    act[:3] = np.clip((d_xy/np.linalg.norm(d_xy))*0.6, -1, 1).tolist() + [0.0]
    act[3] = 0.6
elif state == ST_INSERT:
    act[:3] = [0,0,np.clip((hole[2]-peg[2])*2.0, -0.6, 0.6)]
    act[3] = 0.6
```

## 训练配方
- 数据：官方专家轨迹 50 条（obs, act, next_obs, contact 标签[d_hp<0.06], 抓握点 delta）
- 左脑：动作回归 MSE；右脑：next obs MSE + contact BCE；对位头：delta MSE
- 800 epoch, batch 256, seed 42（**必须固定！不固定重训质量漂移**）
- 训练 3 头（left/right/align），评估只用 left+right

## metaworld 关键物理细节
- `grab_effort`（动作[3]）：**正值=夹持(0.6), 负值=张开(-1.0)**——官方专家 `_grab_effort` 用 0.6
- 官方专家抓取阈值：xy 差 <0.04 且 z 差 <0.15 → grab（但实测 z 要贴住 <0.01 才夹得中，0.029 就夹空）
- `rightEndEffector/leftEndEffector` sites = 夹爪钳口，中点 ≈ endEffector（偏移 0.005），endEffector 即钳口位置
- pegGrasp site = peg 中段抓握点；抓握目标 = pegGrasp + [0,0,0.02]（上方 2cm 对准）
- 抬起高度 <5cm 时 peg 蹭台面，水平转移卡死（d_xy 卡 0.15 不动）

## 视频生成
- `tools/gen_insert_video.py`：跑 seed → 录帧（每 2 帧 1 张）→ PNG 临时目录 → ffmpeg 合成 → 旋转 180°
- **imageio.mimsave 报 `expected bytes, NoneType found`**（av 编码器不兼容）→ 改 cv2 存 PNG + ffmpeg
- 视频 seed 有随机性：评估日志某 seed 成功 ≠ 录视频那次成功，失败就换成功 seed 重试

## 待办（后续会话）
- 20 seed 稳定性测试
- 插入 7/8 → 8/8（转移微调 / 抬起更高）
- 真机迁移（Orin 力控夹爪，仿真物理瓶颈真机可解）
- 与抓取点对位头（grasp_point_mlp, loss 0.007）融合做右脑对位增强
