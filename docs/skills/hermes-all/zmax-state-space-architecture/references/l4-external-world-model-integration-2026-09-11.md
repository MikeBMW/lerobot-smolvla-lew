# L4 接入外部世界模型 (INTACT-JEPA) — 会话实录 2026-09-11

老倪任务: 参考 github.com/zju3dv/INTACT-JEPA, 在状态空间 L4 层加 INTACT 节点, 输出直接接
机器人硬件接口; "输入可以再下载新数据集"; 跑起来后研究如何适配 L4。

## 1. INTACT 是什么 (jepa.py / module.py / direct_solver.py)
- **免搜索** intent→action 世界模型。Direct 控制器直接输出动作, 无 CEM 采样 (每步仅 5 次前向)。
- 核心三件: ① `intent = goal − current` (目标位移=意图) ② `IntentActionActor(z, intent, prev_act_emb)
  → (mean, log_std)`, 推理取 **mean** ③ 训练损失 = 高斯 NLL
  `0.5*((t−mean)²·exp(−2log_std) + 2log_std)`。
- `actor_features` 布局: `four_slot = [z, intent, z*intent, prev_act_emb]` (4×192=768);
  `five_slot` = 5 段; 旧 grammar = **3 段 (576)**。
- 论文成绩: Goal-displacement INTACT 89.39% macro SR; PushT 单域 80.22%。

## 2. 环境搭建 (踩坑顺序)
```bash
sudo apt-get install -y libegl1 libgl1 libglfw3 libglew2.2 libosmesa6
export PATH="/home/ubuntu/.hermes/bin:$PATH"      # ★ uv 不在 PATH → install.sh 直接报
bash scripts/install.sh cu124                     #   "Python 3.10 or uv is required." 退出
```
- venv 建好后若依赖缺: `uv pip install --python .venv/bin/python -r requirements-dev.txt -i <mirror>`
  (清华镜像 403 → 用阿里云 `https://mirrors.aliyun.com/pypi/simple/`; torch 先单独按 cu124 index 装)。
- 就绪判据: `torch 2.6.0+cu124, stable_worldmodel 0.1.0, stable-pretraining 0.1.7, ogbench, mujoco,
  h5py, timm` 全可 import; `python scripts/preflight_check.py` 27 单测过。
- **预检会用 PATH 里的 python** → 必须让 `.venv/bin` 最前, 否则报 "No module named torch/h5py"。

## 3. 数据与权重
- 数据 `quentinll/lewm-pusht`: 12.23 GiB `.zst` → 解压 43.12 GiB `.h5`
  (keys: action(2336736,2) / pixels(2336736,224,224,3) / proprio(2336736,4) / state / episode_idx /
   ep_len / ep_offset)。**eval 用原始 HDF5**, 只有训练才转 Lance。
- 大文件下载: aria2 16 线程 + `-c`, **完成判据 = `.aria2` 控制文件消失**。
  ⚠️ 用 `ps|grep aria2c` 判完成 → 提前解压 → `zstd: Data corruption detected`(假损坏, 实测踩过)。
- 权重 `INTACT-JEPA/INTACT` 有**三套运行时**, 必须配套:
  | 运行时 | 权重 | 说明 |
  |---|---|---|
  | 根运行时 (E1) | `INTACT-no-previous-action/*` | `scripts/eval_official.sh` 用这个 |
  | `paper_runtime/` (仓库自带) | `paper-e5-goal-v1` 分支 (`INTACT-unified/*`) | 论文权重专用兼容层 |
  | CLEAR v0.5.1 | 需另下 `CLEAR_ROOT` + manifests | `scripts/eval_clear_v051.sh` |
- **grammar 不匹配是最大坑**: E1 权重 `intent_actor.net.0` 输入 576 (3 段) 而当前代码
  `four_slot`=768 → `size mismatch`。正解 = 下 paper-e5-goal-v1 用 `paper_runtime/`;
  当时临时给 `module.py` 加 `three_slot` 分支凑通(违反代码完整性, 需 `INTACT_SKIP_PREFLIGHT=1`)。
- **config.json 需自生成** (E1 tar 只含 .pt):
  ```python
  with initialize_config_dir(config_dir="config/train", version_base=None):
      cfg = compose(config_name="intact_goal", overrides=[
          "img_size=224", "embed_dim=192", "history_size=3",
          "model.action_encoder.input_dim=10",        # PushT 动作块维 (不是 2!)
          "model.intent_actor.action_dim=10",
          "model.intent_actor.action_emb_dim=0",      # net.0 输入 576=3×192 反推
          "model.intent_actor.feature_layout=four_slot",
      ])
  d = OmegaConf.to_container(cfg, resolve=True)["model"]   # ★ 顶层必须是 model 段
  json.dump(d, open(ckpt_dir/"config.json", "w"))
  ```
  loader 是 `instantiate(config)` (顶层要 `_target_=jepa.JEPA`); 存整个训练配置会报
  `Missing key load_state_dict` / `Missing mandatory value: model.intent_actor.action_dim`。
  **参数都从 checkpoint 形状反推**: patch_embed 10 / net.11 输出 20=2×10 / net.0 输入 576=3×192。
- eval 用法: `bash scripts/eval_official.sh direct pusht <ckpt目录**绝对路径**> 42 20`
  (相对路径会被拼到 `$STABLEWM_HOME/checkpoints/` 下 → 解析不到)。
- **实测结果**: 官方 direct / pusht / 20 episodes = **70.0%** (论文 80.22%), 0.104 s/step,
  forward_calls 5/step; 两次独立运行 70.0% / 70.0% 一致。

## 4. 官方跑通视频取证
- `sitecustomize.py` 注入 (`PYTHONPATH=/tmp/intact_patch`) patch
  `swm.policy.WorldModelPolicy.get_action` → 记录 `info_dict["pixels"]` 末帧, atexit 存 npz。
- imageio 缺编码器 → 帧导出 PNG 序列 + `ffmpeg -framerate 8 -i f%04d.png -c:v libx264`。
- 局限: hook 只在部分调用路径触发 (20 episodes 只抓到 50 帧), 视频作"真实画面"证据足够,
  成功率以 eval 的 JSON 为准。

## 5. 在我们引擎上适配 (13 层排查, 6 个真 bug)
数据构造: `z = obs[:39] + stage_onehot(7) = 46`; `intent = goal − obs[7:10](_pc)`;
`prev = 上一动作`; `target = u_exec_vec`。采集必须**包装 `sim.accel` 捕获它实际收到的 obs**
(拿 `tr["obs"]` 会不同源: 前 12 维一致但后段不同 → 同输入输出差 3 倍)。
- 训练结果: 世界模型 `(z,a)→z'` held-out MSE **6e-5**; actor test MAE 0.0147(干净数据) /
  0.0413(含失败轨迹, gripper 维 0.153)。
- 结果表 (10 seed):
  | 方案 | 成功率 | 模型参与 |
  |---|---|---|
  | 解析链 | 100% | — |
  | 纯 INTACT actor | 0/10 | 100% |
  | 混合(残差 ±0.03) | 6/10 | ~100% |
  | latent-guard (世界模型误差守卫) | 0/10 (guard 从未触发) | ~100% |
  | **一致性守卫 TOL=0.15** | **10/10** | **21-34%** |
- TOL 扫描: 0.05→100%/0%参与(退化) · 0.15→100%/21-34% · 0.3→0%/86% · 0.6→0%/100%。
- 结论: 引擎是有状态调度器 (`u = w_ff·u_ff + (1−w_ff)·u_fb` + 8 阶段状态机), 内部状态不可观测 →
  **模型只能辅助(≤30%), 不能主导(>50% 必崩)**。latent 误差监控检测不到"停滞"类失败。
- 插拔口径: `done` = `sched.stage()=="完成"`, 由 `_insert_depth()=‖peg_head−_goal_p()‖` 决定。
  阈值 6mm → 残余 4.5-5mm 就判完成(视频里看着没插进去, 老倪肉眼抓出) → 收紧到 **2mm** 后
  成功率 100%→**73%(11/15)**, 残余 <2mm 才是真插到底。

## 6. 诊断脚本模式 (可复用)
```python
class W:                     # 包装 accel: 记录 obs + 返回动作 + 统计来源
    def forward(self, obs): ...
    def analytic_forward(self, obs): return self.forward(obs)   # ★ 两个入口都要包
sim.accel = W()
```
- 只读帧捕获走 `sim._frame_sink` (别在 forward 里渲染: 实测采纳率 27%→77% 且全崩)。
- 排查输出: stage 序列 + 到孔距离 + actor/guard 计数 + `s.sched.stage()` 字符串集合
  (引擎阶段名 = 接近/对位/下降/抓取/抬起/转移/插入, 带推进后缀如 "下降 · 接触")。
