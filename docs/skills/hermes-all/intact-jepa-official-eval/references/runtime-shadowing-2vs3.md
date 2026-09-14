# ② vs ③ : 同名 module.py 遮蔽 (2026-09-13 实测转录)

老倪问「③ 这个配置，怎么报错了」→ 完整判决链与证据。**结论: 是配置与权重不匹配, 不是操作错, 也不用改代码。**

## 1. 报错原文
```
hydra.errors.InstantiationException: Error locating target 'module.InverseTransitionActor', set env var HYDRA_FULL_ERROR=1 to see chained exception.
full_key: inverse_actor
```
带 `HYDRA_FULL_ERROR=1` 后的链式根因:
```
ModuleNotFoundError: No module named 'module.InverseTransitionActor'; 'module' is not a package
  → ImportError: Error loading 'module.InverseTransitionActor':
       ModuleNotFoundError("No module named 'module.InverseTransitionActor'; 'module' is not a package")
     Are you sure that 'InverseTransitionActor' is importable from module 'module'?
  → InstantiationException: Error locating target 'module.InverseTransitionActor'
```
（hydra `_locate` 失败点: `hydra/_internal/utils.py:653` 抛 ImportError; `_instantiate2.py:139` 包成 InstantiationException）

## 2. 两个 module.py 的类清单 (实测 grep '^class ')
```
<repo>/module.py            11174 B, 09-11 22:31
  SIGReg · FeedForward · Attention · ConditionalBlock · ConditionalTransformer
  Embedder · MLP · IntentActionActor · ARPredictor            ← 没有 InverseTransitionActor
<repo>/paper_runtime/module.py  24263 B, 09-11 18:47
  … + InverseTransitionActor(246行) · MidpointBilinearSplitInverseActor ·
        ConditionalJacobianInverseActor · MixtureGaussianInverseActor      ← 官方那套
```
`hasattr(root_module, 'InverseTransitionActor') == False`（直接 import 实测）。

## 3. 权重 config 引用什么（判定能不能用的硬依据）
```python
# 遍历 ckpt 的 config.json 里所有 _target_
recovery_delta_full_{pusht,cube,reacher,tworoom}_s3072/config.json → "module.InverseTransitionActor"   (论文权重)
intact_goal_zmax_s3072, intact_goal_zmax_v2_s3072/config.json      → module.ARPredictor / Embedder /
                                                                     IntentActionActor / MLP          (repo 自训, 根 module.py 都有)
```
→ **论文权重只能在 ②(paper_runtime) 里跑；③(根运行时) 是给 repo 自训权重用的。**

## 4. 判决探针的真输出（同一句 hydra `_locate`，只换 sys.path 顺序）
```
③ 场景 sys.path[0]=repo root      → import module = /home/ubuntu/INTACT-JEPA/module.py
   → 失败: ImportError | Error loading 'module.InverseTransitionActor':
② 场景 sys.path[0]=paper_runtime  → import module = /home/ubuntu/INTACT-JEPA/paper_runtime/module.py
   → _locate('module.InverseTransitionActor') 成功: <class 'module.InverseTransitionActor'>
```
即：**脚本所在目录 = sys.path[0]，优先于 PYTHONPATH**；③ 的 PYTHONPATH 里虽然写了
`paper_runtime:repo`，但排在脚本目录之后, 救不回来。差异只来自 program/cwd, 与代码无关。
可重复执行的版本: `scripts/which_module_import.py`（在 repo venv 里跑）。

## 5. ③ 复现与后续阻塞（2026-09-13 状态）
```bash
cd /home/ubuntu/INTACT-JEPA        # cwd=仓库根, PYTHONPATH=paper_runtime:仓库根, HYDRA_FULL_ERROR=1
./.venv/bin/python eval.py --config-name=pusht policy=recovery_delta_full_pusht_s3072 \
    eval.num_eval=2 world.max_episode_steps=60 eval.eval_budget=50
# → 复现 InstantiationException (论文权重)

./.venv/bin/python eval.py --config-name=pusht policy=intact_goal_zmax_v2_s3072/weights_epoch_3.pt \
    eval.num_eval=2 world.max_episode_steps=60 eval.eval_budget=50
# → 过了 instantiate (不再报 InverseTransitionActor)，但还有两道坎:
#   a) 只写目录名 → ValueError: Ambiguous checkpoint: multiple .pt files in .../intact_goal_zmax_v2_s3072.
#      Specify the file directly.   ⇒ policy 必须显式指到 .pt 文件
#   b) 显式给 .pt 后 → stable_worldmodel/policy.py:420 get_action 里
#      RuntimeError: shape '[2, 25, -1]' is invalid for input of size 80
#      (num_envs=2 × horizon5 × action_block5 与根运行时的 action 维度对不上) —— **未解决**,
#      ③ 目前不能当验收通路; 论文权重官方评测一律走 ②。
```

## 6. 讲给老倪的口径
- 先给根因一句话: 两份同名 module.py 抢 import，③ 的脚本目录在 sys.path[0] → 命中根那版（无该类）。
- 再给证据: 同一句 `_locate` 在两种 sys.path 顺序下的结果 + 两个 module.py 的类清单 + 权重 config 的 `_target_`。
- 明确"这不是你操作错，是配置不匹配"；论文权重 → ②，repo 自训 → ③。
- 声明没有改任何 config/yaml（老倪「不改变逻辑/直接复制项目」口径），只做验证与复现。
- 附带发现要单独标出来（③ 的 Ambiguous checkpoint / reshape 维度未解决），别混进已解决项。
