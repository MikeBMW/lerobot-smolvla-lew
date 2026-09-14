# 把训练好的策略接成执行者：DAgger / 残差 / 闭环同构 (2026-09-10 实测)

结论先行 —— 这次是**负结果 + 一条替代路线**，不是已验证的 DAgger 成功流程。别把下面
的 DAgger 步骤当成"推荐做法"，当成"什么时候不该做 DAgger"的判据用。

## 背景
- 引擎解析链(规则)28 seed 成功率 **46.4%**（插入段判据/夹爪误判/滑脱重抓三项修复后）。
- 把微调好的 SmolVLA-Lew(30000 步, freeze_smolvlm + DiT ActionHead + LEW) 真接进闭环：
  每帧渲染 → 官方预处理 → `select_action` → 取 xyz 替换引擎 `u_ff[:3]`（gripper 仍由状态机出）。
- 单 seed 基线：解析链同 seed 343 步成功；模型驱动 **1000 步失败**。6 seed 评估 **0/6**。

## 为什么失败（不是接入 bug）
1. 先验单帧误差 0.05~0.16（看着不大）→ 闭环累积 → covariate shift → 越走越偏 → 崩。
2. 确认不是"没接上"：给 `_l3_forward` 打计数器，40 步调用 10 次（每 4 步一次），
   返回真实非零动作；引擎日志有"L3 真执行接入"。
3. 确认不是"没同构"（见下）：图像尺寸/指令串/归一化三项修正后仍然失败。

## DAgger R1 全链（记录，供判断是否值得再投入）
1. 采集：`SS_L3=1 SS_DAGGER=1` 跑 10 seed 模型驱动 rollout，每 4 步记
   (frame, state39, **expert=被替换前的解析链 u_ff**, model=模型输出, stage) → 1500 帧。
   专家标签天然对齐：引擎先算 `u_ff`（解析链）再被模型覆盖，覆盖前 copy 即标签。
2. 转 LeRobot 格式追加 episodes：`action` 列 = **专家动作**（DAgger 核心），
   `observation.state` = 39D，视频按 25fps、`timestamp = i/25`；episodes parquet 的
   `videos/observation.image/file_index` = 新 episode 号（对应 `file-{idx:03d}.mp4`，
   `video_path` 模板 `videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4` 兼容）。
   坑：data parquet 列必须**全部** append（漏 `next.success` → pandas "All arrays must be of the same length"）。
3. 训练：resume 自 30000 步 ckpt，`steps: 40000`，数据集换 `*_d1`（134 eps / 131383 帧）。
4. 评估：闭环 **0/6**（同 seed 解析链 5/6）。

## 判据（复用价值最高）
- **DAgger 可自举的前提是模型"至少偶尔成功"**。闭环 0/N → rollout 全是失败轨迹 →
  专家动作在那些状态上不可达/无意义 → 加轮次无效。**先花 10 分钟测闭环成功率，再决定是否投 DAgger**。
- **单轮新增数据占比太小撬不动**：1500 / 131383 ≈ 1.1%。
- **推荐替代：残差学习** `u = u_解析链 + Δu_模型`（Δu 初始 0）——起手等价解析链，
  成功率不清零（符合"新功能不得让成功率回退"红线），只学修正量；DAgger 已采的专家动作可直接当标签。

## 闭环执行"三同构"检查（任何 VLA 接引擎前逐项过）
| 项 | 训练口径 | 常见错误 | 修法 |
|---|---|---|---|
| 图像 | 128×128（PIL LANCZOS 缩放后编码） | 推理喂 480×480 原图 → 分布外 | `Image.fromarray(img).resize((128,128), LANCZOS)` |
| 语言指令 | `meta/tasks.parquet` 里的原串 | 代码硬编码别的串；或传 int → `TypeError: 'int' object is not iterable` | 动态读 tasks.parquet，显式传 `task` 字符串 |
| 归一化 | 官方 `make_pre_post_processors(config, pretrained_path=ckpt)` | 手搓 `img/255` + 原始 state | 走官方 pre；直喂会把误差从 0.15 虚高到 0.35 |
| 帧率 | 每 4 步 1 帧 | 每帧推理（慢且分布不同） | 每 N 步推理一次，中间沿用 |

## 二值维（夹爪）不是步数问题
- 抓取段 `gripper` 真值 1.0，模型输出 ≈0；xyz 维误差 0.01~0.08 正常。
- 加训 10000→30000 步（+20000）后平均误差 **0.1599 vs 0.1505**（基本没变）。
- 根因：0/1 二值维用 MSE 回归天然趋均。处方：夹爪交给规则/状态机，或改 BCE / 分类头。
- 报进展要**分维度**看，平均 loss 会掩盖单维失效。

## 引擎侧接入的工程经验
- 开关式接入最安全：`SS_L3=1` 才走模型（生产不设 = 解析链原路径），`SS_L3_CK` 选 checkpoint
  （便于 v8 / d1 / fast 多模型对比），`SS_L3_EVERY` 控推理频率。
- 记录钩子 `SS_DAGGER=1` 只在模型分支里 append，不影响正常路径。
- 训练完 `config.json` 会丢 `type` 键 → `from_pretrained` 报 draccus `Expected a dict with a 'type' key` → 手动补。
- `cp -r` 复制 `checkpoints/last`（symlink）会变实体目录 → 训练保存时
  `FileExistsError: '<step>' -> .../last` 崩；用 `cp -rL`，或复制后 `rm -rf last && ln -s <step> last`。
- `train_config.json` 的 `steps` 是**总步数**。
- 杀训练进程别 `pkill -f lerobot_train`（自匹配自杀）：`ps -eo pid,args | awk '/lerobot_train/ && !/awk/ {print $1}'` 再按 pid 杀。
- batch 影响：本机 4060 上 batch 8 = 4.52 s/step，batch 1 = 1.73 step/s（快 7.9 倍）；催进度时先降 batch。
