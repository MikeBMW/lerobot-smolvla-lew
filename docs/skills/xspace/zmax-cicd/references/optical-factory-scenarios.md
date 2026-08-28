# 光模块工厂三场景原子技能 JSON（2026-08-09 老倪设计任务）

主文件：`flows/scene_skills_3scenarios.json`（仓库内，已推 GitHub 114bfc8a）
GUI 模块库：simulink_module.py `("scene", "🏭 场景 (3)", [...])` 三个节点，scene_id 与 JSON 一致（SCN-01/02/03）。
交付对象：web 端据 JSON 建可视化场景（老倪 @web: "你给出场景链接，静静传 json 给你建可视化"）。

## 设计原则（老倪明确要求）
- 从 `flows/atomic_skills_raw.json`（242 个原子技能）分类组合：**插拔类 = XPO高密可插拔光学(59) + 操作动作(73) 中的 A001/A002/A010**；**搬运类 = 载具物流(9) + A004/A005**；**视觉检测类 = 视觉检测(10) + Q001-Q004 感知定位(15)**
- 专业工艺工程师视角：每个场景必须有**性能指标**（操作成功率>99%、节拍时间）+ **结构尺寸** + **质量门**，不是功能罗列
- 场景 node 点击打开一个连接（把 JSON 传给 ECS 网站）

## 三场景工艺参数基准（QSFP-DD 800G 光模块，行业标杆值）

| 场景 | SCN-01 高密插拔 | SCN-02 柔性搬运 | SCN-03 光学AOI |
|---|---|---|---|
| 成功率 | ≥99.5% | ≥99% | ≥99.9%（检出率）|
| 节拍 | ≤3.5s/颗 | ≤8s/颗 | ≤12s/颗（4道检测）|
| 关键尺寸 | QSFP-DD 45×17.4×8.5mm；笼子 2×4 腔距 18.75mm；插入深度 28mm±0.05；锁扣 3.2mm | 料盘 330×230×12mm 穴距 40mm；单颗 8.5g；码放≤10层 | 金线 φ25μm 焊点距 60μm；缺陷最小检出 10μm；0.35μm/pix |
| 力/精度 | 插拔力≤15N；定位 ±0.02mm；重复 ±0.01mm | 贴装 ±0.5mm；振动≤0.5g；ESD 1e6-1e9Ω | 转位台 0.001°；±2μm |
| 质量门 | 金手指无划痕；电接触≤0.5Ω | 码放±1mm；批次追踪100% | 误判率≤0.5%；结果可追溯 |
| 关键原子 | XPO002/003/004, A001/002/010, Q001/002 | XPO002, A001/004/005, Q001 | Q001-004, A001/005 |

## JSON 结构（每场景字段）
`id / name / category / description / scene_type / layout{workcell, robot, fixture, sensors, dimensions} / performance{operation_success_rate, cycle_time, ...} / process_steps[{step, name, desc, atoms}] / key_atoms / quality_gates` + `meta{version, author, industry, product, standard}`。

## 踩坑
- **模块库 LIBRARY 场景节点 dict 语法**：`{"name":..., "params":{...}}` 外层 dict 必须 `}}` 闭合（params 内层 `}` + 外层 `}` + 逗号），写成 `},`（只有内层闭）会 `SyntaxError: closing parenthesis ']' does not match opening parenthesis '{'`（ast.parse 报 525 行但真凶在 521/523 行少一个 `}`）。改完 `ast.parse` 全文件验证。
- **老倪对性能指标的口径**：成功率要写 `≥99.5%` 级别（行业标准是 >99%），节拍必须带单位（s/颗），检出率 ≥99.9%——光模块工厂是良率敏感行业，指标不达标会被当场打回。
