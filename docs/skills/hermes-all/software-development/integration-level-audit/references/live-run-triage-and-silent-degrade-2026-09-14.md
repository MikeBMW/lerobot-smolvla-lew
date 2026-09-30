# 「我现在正在运行呢, 断点无反应」+ 静默退化取证 (2026-09-14 下半场, Z-MAX L4)

承 `breakpoint-not-hit-branch-audit-2026-09-14.md` (上半场: loss 行属训练分支 + L4 装配 pop SS_L3)。
下半场两个新形态, 都已实测定案。

## A. 用户说"正在运行"时: 先查那个 run 是**什么进程**, 再谈断点

现场 (实测):

- 调试会话: VSCode F5 起 `studio.py` → `debugpy adapter` → 调试器 **pydevd 多进程**
  (`debugpy / launcher ... tools/gui/studio.py`, 子进程命令行里带 `--multiprocess`)。
- 用户点的「运行+L4」= GUI **起子进程** `tools/gen_l4_demo_video.py --also-latest`
  (`tools/gui/simulink_module.py` 内 `_sp.run([py, <root>/tools/gen_l4_demo_video.py, "--also-latest"] ...)`,
  另有一处 `_tool_script("gen_l4_demo_video.py")`), pid 实测存活 ~18s 后正常退出。
- 产物验证 (证明运行**成功**): `reports/l4_demo_20260914_125329.mp4` = 480×480 · **1817 帧 · 72.7s**
  (`ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=nb_read_frames,duration,width,height`)。

判据命令 (照抄):

```bash
# 谁在跑 / 调试器挂没挂上 / 有没有进程被断点停住
ps -eo pid,ppid,stat,etime,pcpu,cmd | grep -Ei "studio\.py|debugpy|pydevd|<入口脚本>" | grep -v grep
ss -tnp | grep -E "39777|<adapter-port>"        # ESTAB 到 adapter = 子进程在调试会话里 → 子进程断点能进
ps -eo pid,stat,cmd | awk '$3 ~ /^[tT]/'        # 空 = 没有任何调试进程停在断点
ls -lat --time-style=+%H:%M:%S reports/ outputs/  # 产物 mtime = 这个 run 在写什么

# 那个进程真正执行的文件集 (静态, 不用打断它)
grep -n "^\s*import \|^\s*from \|spec_from_file_location" tools/gen_l4_demo_video.py
grep -c "smolvla\|action_head\|intact" tools/gen_l4_demo_video.py       # 0/仅注释 → 链上没有这份代码
```

本次结论: 子进程执行的是 `gen_l4_demo_video.py` (metaworld+mujoco 脚本链) +
`src/lerobot/manifold/predictor_layer.py` (权重 `models/l4_mani_predictor_v5.pt`) +
`src/lerobot/manifold/yaw_actuator.py` (②段 yaw 每帧决策), **没有任何 import 到 smolvla_lew 包**
⇒ `class SmolVLALewActionHead` 与 loss 行在该 run 里不存在, 断点不可能进。
**"调试器没问题 (多进程已接上) · 是那份代码没跑"** —— 这句要先行说清, 否则用户以为工具坏了。

附带可查项 (可选, 本机实测该键为空, 别当唯一手段): VSCode 断点存放在
`~/.config/Code/User/workspaceStorage/<hash>/state.vscdb` → `ItemTable` 里 key 含 `breakpoint` 的行
(本机 2026-09-14 查无此键; 拿不到时改问用户断点是否灰色/空心 = 未绑定)。

短命子进程的取证坑: py-spy 会报 `Failed to get process executable name. Check that the process is running.`
—— 那是子进程**已经跑完退出** (本次 ~18s), 不是探针或 py-spy 的问题; 改用产物 mtime/ffprobe 判完成。

## B. 静默退化 + 每帧重载: "引擎计数 0, `__init__` 次数 = 步数"

现象 (探针实测, `SS_L3=1` 跑 12 步):

```
  12 次  SmolVLALewPolicy.__init__      ← 每步重载 625M (~4s/步)
   0 次  SmolVLALewPolicy.select_action ← 模型从未真执行
   0 次  action_head.py 的 predict_action / forward / DiT.forward
  action_head.py 已执行行 = 仅模块级类定义 (50..167), 无任何函数体
```

抓原始异常 (引擎把异常吞在 `except` 里只 log 一次):

```python
# 把引擎那个方法包一层 (或把引擎 log 收进列表后过滤 ⚠️/失败)
_orig = sim._l3_forward
def _wrapped(v):
    try: return _orig(v)
    except Exception as e: traceback.print_exc(); raise
sim._l3_forward = _wrapped
```

原文: `⚠️ L3 推理失败: Failed to instantiate processor step 'device_processor' with config:
{'device': 'cuda', 'float_dtype': None}`。

根因: ckpt 里保存的预处理器 pipeline 的 `device_processor.device` 写死 `cuda` →
`make_pre_post_processors(policy_cfg, pretrained_path=ckpt)` 在**无可见 CUDA 的环境实例化就失败** →
整段加载中断 → `return None` 静默退解析链; 且**类级缓存赋值语句排在失败语句之后** ⇒ 每帧重试整段加载
(625M × 每帧)。

修法 (官方 `scripts/lerobot_eval.py` 同款, 三处一起):

```python
dev = os.environ.get("SS_L3_DEV") or ("cuda" if torch.cuda.is_available() else "cpu")
pre, post = make_pre_post_processors(
    pol.config, pretrained_path=ckpt,
    preprocessor_overrides={"device_processor": {"device": str(dev)}},     # ← 关键
    postprocessor_overrides={"device_processor": {"device": str(dev)}},
)
# 失败熔断: except 里记类级失败标记 (_L3_FAILED), 后续帧直接 return None 不再重载;
#          入口处 if _L3_FAILED and os.environ.get("SS_L3_FORCE_RETRY") != "1": return None
```

修后同探针实测 (12 步): `__init__` 12→**1** · `select_action` 0→**3** · `predict_action_chunk` 0→1 ·
`SmolVLALewActionHead.predict_action` 0→**1** · `DiT.forward` 0→2 · **`predict_action` 主体行 313-345 命中 39** ·
`DiT.forward` 主体 176-190 命中 16 · 引擎 `l3_calls` 0→**12** (模型动作真被 engine 消费); **loss 行 307 仍 0**。
零回退复测: 未受影响档 (L4 INTACT 直驱) 20 步 `IntactNode.step`/`decode` 20/20 不变 + `ast.parse` 语法检查通过。
不设 `SS_L3_DEV` 且无卡时也自动落到 cpu (同一份 overrides 生效)。

诚实边界 (汇报时必须写): 本次全程 `CUDA_VISIBLE_DEVICES=""` (训练占 GPU 5975 MiB, 加载 625M 有把训练打挂的风险),
所以"有 GPU 时 L3 真接管跑完整段"**未验证**; 结论限定在"载入+推理真的发生了"这一级。

## C. 相邻可复用技巧

- **活进程真栈**: `sudo <venv>/bin/py-spy dump --pid <pid> [--nonblocking]` (机器上
  `gui-venv311/bin/py-spy` 与 `~/.hermes/hermes-agent/venv/bin/py-spy` 都有)。本次用它抓到探针卡在
  `huggingface_hub/hf_api.py: list_repo_tree` (网络) → 修法是给探针加
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1` (走本地缓存), 之后 50s 内跑完。
- **探针打桩要打印失败原因**: 目标类/函数名按实现核对 (`IntactIntentService` 不是 `IntactPolicyService`;
  `build_skill_ctx` 是模块级函数不是类方法), 打桩失败写进报告 (`打桩失败: [...]`) 而不是静默跳过。
- **改探针脚本后回读验证**: 用 python 字符串替换改脚本会**静默 no-op**; 改完 `grep -c "<新标记>"` 确认,
  否则报告里的"已打印项"其实是空的。
