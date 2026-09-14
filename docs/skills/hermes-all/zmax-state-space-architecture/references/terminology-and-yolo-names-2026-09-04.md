# Z-MAX 术语统一 peg/插销 → 光模块 + YOLO names 覆写 (2026-09-04, commit 52113786, 102 文件)

> 感知链代码 (det3d / yolo_state_aligner / state_space_sim_real / YOLO 框标签) 改动前先读。
> 注: yolo-3d-perception-chain 与 zmax-left-right-policy 是 user-owned 技能不可后台写,
> 术语知识落脚于此; 建议前台 `hermes curator adopt` 后把本文件内容合并进 yolo 技能。

## 术语分层 (哪层换、哪层绝不换)
- 业务对象 = 光模块 (光模块工厂)。**表述层已全换**: 中文"插销"、注释/docstring 裸词 peg、
  日志/GUI 文本 (node_logic 日志行打印 `光模块=[...]`、ss_dreamview 图层说明、YOLO 框标签)。
- **保留不动** (动了会砸/失真):
  - 代码变量标识符: peg / PEG_POS0 / peg_off / d_hp / self.peg (数据流一致性)
  - metaworld 环境绑定: site 名 pegGrasp/pegHead (mujoco XML)、任务名 "peg-insert-side-v3"
  - 数据集/权重/目录名: data/yolo_peg、train_peg_rl.py、peg_depth_v1-2、场景判断 ("peg" in cur)
  - 治具真实零件词: 定位销/对接销/工装定位销 (工厂真零件, 不是光模块)
- 再 grep "peg" 有残留 ≠ 漏改 — 大部分属上面保留层, 别"好心"清掉。

## YOLO 检测类别名业务化 (det3d 键已变!)
- ⚠️ ultralytics **顶层 `model.names[id]=..` 赋值不生效** (实测推理 res.names 不变) —
  必须 `model.model.names[id] = "光模块"` (yolo_state_aligner.__init__; 推理 res.names 跟随,
  画框 _vis["boxes"] 自动显示光模块)。
- 类 id 顺序 {hand:0, peg:1, hole:2} 与训练标注绑定 (gen_yolo_data.py) — **只改名勿改 id**。
- det3d dict key 现在是 `"光模块"` (来自 res.names), 不是 "peg":
  - align() 判 `"光模块" in det3d` 写 obs[4:7]/[22:25]; z_map 键同改
  - 消费点已同步: yolo_state_aligner / state_space_sim_real (det3d.get("光模块")) /
    tools/diag_depth_align.py
  - 循环消费自动跟随: simulink_module det3d[cls] 遍历、probe_r1_calib 遍历 key
- 权重识别坑: 主检测 = runs/detect/outputs/yolo_peg/peg_v1/weights/best.pt (names 3 类);
  outputs/yolo_peg_depth/*/weights/best.pt 是**深度单类模型** names={0:'depth'} — glob 按
  mtime 排序会先命中最新的 depth 模型, 覆写 names 时无 peg 可改 (不是 bug)。

## 术语替换分层法 (再做类似改名)
1. 中文词全文本可换 (只出现在注释/字符串/文档)
2. 注释/docstring 裸英文词可换, 但排除: `peg-` 复合 (peg-insert/nut-on-peg 任务专名)、
   引号内 dict key (d["peg"] 数据键)、md 反引号命令与 ``` 围栏代码块
3. 中文单字陷阱: "零开销"含"销"字 (grep 误报); "握着销/销头"=被操作物体可换,
   "定位销"=真实零件不换 → 用**白名单词组替换** (PAIRS 列表) 而非全文替换
4. 正则 `\bpeg\b(?!-)` 匹配裸词并排除 peg-insert 类; pegGrasp/peg_z0 天然不匹配 (词边界)
5. 替换后必做: 改动 .py 全量 py_compile + 零残留复核 + 消费点 grep (det3d["peg"] 等)
