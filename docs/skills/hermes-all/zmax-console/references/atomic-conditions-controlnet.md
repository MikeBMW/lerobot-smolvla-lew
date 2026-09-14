# 原子技能 → 条件编码 (ControlNet 思想) — 2026-08-09 老倪设计定稿

老倪: "参考 model_zoo.json 你要将 dds-skill-master.html 页面的原子技能, 都做成 dds-data-space.html 类似页面的条件; 你来设计一个 json 文件, 自动将原子技能转换成条件编码; 输入到结构条件节点; 核心思想是 control net"

## 核心思想 (ControlNet 类比)
- 原子技能 = **控制条件** (像 ControlNet 的 Canny/深度图 — 结构化控制信号, 不直接生成内容但约束生成)
- 条件编码 = **多模态条件向量** (图像/力/位姿/触觉/关节/点云/温度/信号/条码/CAD 各模态 one-hot + 语义)
- 注入结构条件节点 (coord_overlay) → `latent += proj(cond)×gate` → **技能条件"控制"VLA 动作生成** (图像是背景, 条件是主线 — 与 Z-MAX 坐标叠加架构同构)

## 数据源 (datadrive.world API)
- 原子技能: `GET https://datadrive.world/api/dds-atomic-api.php` → 242 条, 9 大类 (NPO光学51/XPO光学59/操作动作73/感知定位15/视觉检测10/安全集成10/载具物流9/移动导航7/学习泛化8)
- 字段: id/category/name/definition/input_cond/output_criteria/sensors/deps/maturity/difficulty/phase/scene
- 条件页样式参考: `dds-data-space.html` (C001-C038, 格式: ID/条件数据/Topic/多模态/→action/型号); 条件 API `/api/dds-cond-api.php` **404** — 用页面 HTML 正则抓取即可
- 条件 JSON 保存: `flows/atomic_skills_raw.json` (242 条原始)

## 文件链 (flows/)
| 文件 | 作用 |
|:---|:---|
| `atomic_skills_raw.json` | 242 条原始技能 (API 抓取) |
| `gen_atomic_conditions.py` | 生成器 1: 技能 → 条件编码 JSON |
| `atomic_skills_conditions.json` | **条件库**: 242 条 (D001-D242), list 格式 — 给双击注入用 |
| `gen_atomic_flow.py` | 生成器 2: 条件库 → Simulink DAG |
| `atomic_conditions_flow.json` | **画布 DAG**: 251 节点 (9 row_bg + 242 coord_overlay) + 242 连线 — load_flow_file 可加载 |

## 编码规则 (11 通道固定)
`MODALITY_RULES` 关键词表 (10 模态 + state_2d 兜底):
image(图/图像/视觉/相机/显微) / force(力/力矩/力控/六维力) / pose(位姿/坐标/手眼/6D/朝向) / tactile(触觉) / joint(关节/机械臂/轴) / pointcloud(点云/3D/扫描) / temp(温度) / signal(信号/IO/触发/到位/仓/状态) / code(ID/条码/扫码/编码) / cad(CAD/图纸)
- **⚠️ 必须固定 11 通道** (含 state_2d 兜底位, 无模态匹配时 state_2d=1): 第一版 56 条因无匹配追加 state_2d 变 11 键, 其余 10 键 → 通道数不一致。所有条件统一 11 通道是 ControlNet 定长编码前提
- 动作分类 `ACTION_RULES`: 取料pick/插insert/预插pre_insert/拔extract/放place/贴attach/锁screw/检测inspect/测试test/扫码scan/定位locate/压press/转运transfer...

## ⚠️ 两个 JSON 用途不同 (用户报"simulink 加载不了"的教训)
- `atomic_skills_conditions.json` = **条件库 (list)** — 不是画布 DAG! `load_flow_file` 只认 `{format, nodes[], links[]}` → 直接加载必然失败
- 正确用法: ①条件库 → Simulink 里双击 🧩结构条件 节点 → `_pick_atomic_condition` 选择器注入 (cond_ref/encoding/gate 写进节点 params) ②或跑 `gen_atomic_flow.py` 生成 **DAG 版** 让 load_flow_file 加载
- 生成 DAG 版: 每大类一行 row_bg 背景行 (🎨 分类名) + 该类条件节点横排 (coord_overlay, name=`🧩 {cond_id} {skill_name[:14]}`, params 带 cond_ref/skill/topic/action/modalities/encoding/gate), row_bg→节点各连一条线

## Simulink 注入入口
- 双击分发加分支: `if node.get("type") == "coord_overlay": self._pick_atomic_condition(node); return`
- `_pick_atomic_condition`: 弹 QDialog (分类下拉 + 技能下拉 + 信息预览 topic/模态/编码位) → 确认后写入节点 params + `it.update()` + `_sync()`
- 节点渲染 (paint) 已支持 coord_overlay: 画 + 号 + `叠加: latent += state×{gate} ({sd}D)`

## 验证
- 生成器在 **/tmp 副本**运行验证 (不污染工作区输出 JSON): 复制生成器+raw 到 tmpd → 运行 → 断言产物 → **与提交版逐字节一致** (生成器必须确定性, 无时间戳)
- offscreen `load_flow_file("flows/atomic_conditions_flow.json")` → nodes==251, links==242, row_bg==9, coord_overlay==242, 全 cond_ref
