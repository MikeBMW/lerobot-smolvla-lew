# 算法归位 src + L4 JEPA predictor + 能力档位 (2026-09-08, v5.4.0)

会话: v5.4.0 发布 (3D 夹取修复 + VLM 真实编码 + L4 predictor 链路)。
本文件 = 应并入 SKILL.md 的两个章节 (patch 因 read-before-write 死锁未落, 手工补)。

## 🏛 算法归位 src 铁律 + 右键跳转两路径 (老倪三次纠正: "应该在 src policies")
**真实算法必须在 src/lerobot/ 框架层, GUI 只做薄壳** — 不是"底层类在 src 就行", 节点
函数的完整执行逻辑也要下沉 (老倪连纠 3 次: VLM 节点函数体、ActionHead、predictor 位置)。
- 落位按**语义同域**: VLM 视觉骨干 → policies/smolvla_lew/vlm_encoder.py (smolvla 策略视觉塔);
  ActionHead → 同包 state_space_action_head.py / 官方 action_head.py; **预测接触/性能流形的
  predictor → src/lerobot/manifold/predictor_layer.py (与 manifold_layer.py 同目录同域, 不在
  policies!)**。流形/标定/datasets/policies 同级, 新组件问"它属于哪个域"再落。
- 节点三层件套: ①src 真实文件 (纯 torch, 勿 import lerobot 包链 — 否则 GUI exec 加载断
  draccus/lerobot.utils); ②node_logic 加载器
  `exec(compile(open(真实路径).read(), 真实路径, "exec"))` 缓存 ns
  (co_filename 真实 → VSCode 断点可进); ③_EXTERNAL_LOC 映射 + 画布 params.source。
- **GUI 节点函数薄壳化**: node_ss_vlm 这类"看起来是算法"的完整执行逻辑 (帧→加载→编码→缓存)
  做成 src 函数 (encode_stage(pil, stage, cache, seed)), GUI 壳只取帧+转发+呈现 log。
- 新 nn.Module 组件: __main__ CLI 自检 (结构/参数量/前向维度), node 双击展示真实类 + 维度自检
  (随机权重诚实标注"训练后启用"), 不造假推理。
- 右键跳转**两条路径都查** (只修 _EXTERNAL_LOC 不够):
  ① `_EXTERNAL_LOC[key]` — **key 必须 = _reg 注册键** (曾写 ssvlm/ssdec 而注册是 ss_vlm/ss_dec
    → 永远查不到, 右键回退 GUI 薄壳; 实测 2026-09-08);
  ② 画布节点 `params.source` **优先于** node_logic 映射 (open_node_source 先开 source 文件) —
    flow json 里 source 要指向真实实现文件 (曾指 modeling_smolvla_lew.py 教学文件 / 空)。
  验证: `match_node(节点名)` → `get_node_location(key)` 应落 src 真实文件。
- 小坑: git add -A 会混入 untracked 杂项 (flow_yy.json / *.bak) → commit 后 `git rm --cached`
  + `--amend`; 发布流程只显式 add 指定文件。

## 🧠 L4 JEPA predictor 链路 + 能力档位
- L4 专家链架构 (老倪确认): encoder(VLM z) → **predictor 预测流形** → decoder 动作。
  现状核实法: 流形两兄弟 (manifold_layer.py) 是**解析几何层吃当前观测**, 不是预测器;
  引擎 est.predict/dyn.predict 是潜状态预测不进流形; LeWorldModel.ARPredictor
  (smolvla_lew/world_model_le.py) 是 next-frame 嵌入预测默认关。缺口 = "z+a→z'→流形坐标"。
- 落成: manifold/predictor_layer.py — LatentPredictor (z+a→z', LeWorldModel.ARPredictor
  轻量变体) + ManifoldReadout (z'→流形坐标 **6 维与引擎真值列一一对齐可监督**:
  mani_progress/mani_risk/mani_V/mani_eta/mani_rem/mani_dperp) + WorldModelPredictor 组合;
  decoder = smolvla_lew/state_space_action_head.py StateSpaceActionHead (流形→4D chunk)。
- 能力档位节点 (数据源层 ss_cap, 双击循环 L2→L3→L4, 写 module._cap_level):
  L2=insert 8段插装 / L3=full 13段插拔+AOI / L4=full + run(cap="l4") 恢复预算×2
  (full 4000/insert 1000, 失败回退不放弃直到完成或物理死局)。sim.run(max_steps, cap) —
  **cap 是 run() 参数不是 __init__ 参数** (曾误传构造 TypeError)。▶运行 接线:
  _cap_level 优先于 chk_l3_full (simulink_module ~10842, ~10898)。

## SmolVLM 真实编码补充 (2026-09-08 后半)
- 权重/依赖/编码通道已入 smolvlm-perception-integration 技能; 本节补架构落位:
  vlm_encoder.py 最终在 src/lerobot/policies/smolvla_lew/ (git mv, GUI 文件删),
  顶层 encode_stage(pil, stage, cache, seed) 为节点完整执行逻辑; node_ss_vlm 为薄壳。
- sim_real 每阶段第 6 帧存 _key_frames[stage] (R1 vision 运行), run 尾部挂 tr["key_frames"]。
- VLM 节点缓存 key = f"{stage}|{seed}" (带 seed, 防跨轮串)。
