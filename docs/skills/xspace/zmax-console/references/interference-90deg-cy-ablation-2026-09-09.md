# L4 干扰注入 / 90° 物理边界 / CY 训练正则消融 (2026-09-09 晚实测)

## 1. L4 抗干扰: peg 摆放干扰注入(mujoco free-body qpos)
- peg(光模块)是 **free joint 自由体**(body 名 'peg',qpos 7 维: 3 平移 + 4 四元数),
  关节名不含 'peg' → 按 **body 索引定位**: `m.body_jntadr[body_id]` → `m.jnt_qposadr[jnt]`。
- 注入时机: env.reset() 之后、obs/_get_obs 之前 → 改 qpos + `mujoco.mj_forward` →
  引擎"现场几何/obs 全重读"(o[4:7] 销位/head site 随 body 转),决策链解析伺服自动跟踪新摆放。
- 干扰后**每帧现场读**几何(禁旧锚): 抓取/插入全走现场 site → 平移 ±4cm + 小角 ≤15° attempt1 稳定成功。
- **多布局 attempts 兜底**: 同进程多次 run(cap="L4"),每次 `_jitter_round+=1` 得新随机干扰布局,
  直到 done — "来料重摆"语义,容忍干扰最终必达成功(GUI simulink_module 已接)。
- **死局早停**: 仅**未夹持**时 peg 台面漂移 >10cm 或压翻 z<0.012 → break 交 attempts 换布局;
  夹持转移段 peg 离初始 >10cm 是正常 → grasped 时跳过,防误杀。

## 2. 干扰测试必须隔离/关闭肌肉记忆(peg 被当冰球推)
- 肌肉记忆固化标杆键 = "场景 seed + 段" → **peg 摆放已变仍命中旧标杆** → 快通道重放旧 u_exec
  把移位后的 peg 一路推飞(实测漂移 25cm 死循环, 判据误杀 + 滑脱误报叠加)。
- CLI 回归/干扰测试一律 `SS_MUSCLE=0`(记忆红线); 引擎侧: 干扰注入成功后关 `_mm_on` +
  log("干扰: 标杆失效, 全精算伺服") — 布局变了标杆失效的正确降级语义。

## 3. "水平旋转 90°" 的仿真物理边界(7 组壳实验 + 5 组抓取策略实锤)
- peg = 24cm 长条盒(卧放, 3×3cm 截面, 长轴水平), 绕竖轴转 90° **视觉非常清晰**(长条从横向转纵向)。
- **90° 下任务物理无解**: 夹爪动作空间仅 xyz+gripper(4D, 无绕竖轴 DOF), 且 metaworld 夹爪
  指缝与转 90° 长条的接触几何导致夹持摩擦不足 — 常规/深夹(grasp_th 0.5→0.3)/抓取点改长条
  中心(质心)全部抬升滑脱; 拨正(夹爪推 peg 端绕竖轴转回)实测推不动(台面摩擦+位置控制力不足)。
- **壳方案全失败**: 任何"光模块体壳"附加物 — hinge 铰接子体 / rigid 贴体 geom / contype=0
  纯视觉 / mass 1e-4 — 都破坏**干扰轮**的 peg 抓取(转移段滑脱误报死循环), 但**无干扰基线正常**
  (mujoco 自由体+附加质量的接触数值耦合, 不可参数调)。基线 867 步 done 是壳兼容判据。
- **结论**: 90° + 成功需要末端绕轴旋转 DOF(C2, 仿真底层第 5 动作维 + 回正策略, 半天级架构改动);
  仿真演示走"旋转动画 + 物理可成功角(±15°)"并字幕诚实标注; 真机 6 轴末端回正。

## 4. 训练正则 detach bug(CY 几何先验"没用"实锤 + 消融法)
- **现象**: cy_consistency_loss 等距正则加进训练, 声称"提升"—— 消融(同配置 λ=0 vs λ=0.3)
  数字**完全一致** → 正则从未生效。
- **根因**: 比较项用了 `oa.detach()/ob.detach()`(模型输出截断梯度) → 正则项对模型参数梯度恒 0,
  loss 白算。提升全来自数据增强(干扰数据), 不是正则。
- **修复**: 去掉 detach, 让正则比较流过模型前向输出。
- **铁律**: 任何"辅助损失/正则"进训练后, 必须做**同配置 λ=0 消融对照**验证其真实贡献 —
  数字有差才算生效; 声称提升前先跑消融。
- 效果(修复后): 抗干扰 57.4%→64.6%(+7.2pp), clean 45.7→43.3(抗干扰优先的合理取舍)。

## 5. predictor 权重加载必须架构匹配
- `WorldModelPredictor(z_dim=7, hidden_dim, num_layers)` 权重 state_dict 与创建参数不匹配 →
  `Unexpected key(s)` 静默失败(日志"注入失败"但 mae 看似变化)。v1/v3 = 384/3层, v2/v4/v5 = 512/4层;
  引擎创建 predictor 与部署权重必须同架构(当前 512/4, v5 权重优先)。

## 6. 功能清单"按 L2/L3/L4 分级"的语义混淆(三套分级别搞混)
- 仓库三套分级语义不同: ① **画布能力档位 L2🔧基础辅助/L3🚀高级自动/L4🏆专家自主**
  = `src/lerobot/verification/capability_levels.py` 权威(CAPABILITY_LEVELS, L2-A01 等编号);
  ② **规范场三层 G1/G2/G3** = node_func_tree.py(110 功能, verification_dialog Tab1 树);
  ③ **产品作业分级 L1刚体/L2柔性/L3性能** = PRODUCT_TREE(dialog Tab2, 客户视角)。
- 用户说"功能清单按 L2/L3/L4" = ①能力档位。仅 capability_levels.py 有清单**不算完成** —
  GUI 对话框(verification_dialog)与网页(gen_web_feature_pages)必须**显式接入**: 加第⑤ Tab
  能力档位树(feature 模式默认切到它), function-list.html 加 §0 章节。检查"有没有"先看消费端,
  不看数据源。

## 7. 飞书发视频: media 消息不是 file 消息
- 上传 `im/v1/files` file_type=mp4(绑定 receive_id)→ 发送必须 `msg_type=media`(content 含
  file_key); `msg_type=file` 报 230055("upload type does not match message type")。发完 code=0 才算。
