# v4.1 能力库演进实录 (2026-08-19)

## 背景
老倪原型前「大小脑」清单 (VIS/TAC/LAN/FUS/DEC/CTR/SYS 30项) → 对照工程原型
(状态空间六层源码 + 三脑架构) 增补更新 → v4.0 65 能力 → v4.1 ID 统一。

## 演进链
- v2: 8 域 31 能力 (L0-L3 四层, 方案书视角)
- v3.0: 四层架构 (P/F/S/X/M/K) 45 能力, 双视图 (Query 场景→需求点 / Key 层→能力→模块)
- v4.0: 以老倪大小脑清单为骨架, 7 域 65 能力, 每条带 status (✅实装/🛠部分/🔲待建)
- v4.1: ID 统一 `前缀-序号` (M-01/K-01, SYS 层级压平 SYS-01~10)

## 7 域结构 (model_feature.py 现行)
P 感知(10): VIS-01~07 + TAC-01/02 + LAN-01
F 融合(5): FUS-01~05
S 策略(17): DEC-01~18 (无 DEC-09, 已归位控制域)
E 控制执行(7): CTR-01~07 (CTR-05 运动学解算 = 原 DEC-09)
X 安全边界(10): SYS-01~10
M 平台执行(4): M-01~04
K 支撑(12): K-01~12

## SYS 压平映射 (v4.1)
SYS-01-L0→SYS-01 硬件安全 / L1→SYS-02 力控保护 / L2→SYS-03 动作限幅 /
L3→SYS-04 稳定性 / L4→SYS-05 误差警戒 / SYS-02-L3→SYS-06 路径安全 /
L2→SYS-07 动态安全 / L1→SYS-08 静态安全 / L0→SYS-09 设备联锁 / SYS-03→SYS-10 告警

## 批量 ID 重命名坑 (实测)
- 链式 replace 顺序: SYS-01-L2→SYS-03 的中间产物被后续 SYS-03→SYS-10 规则误伤
  → 动作限幅变 SYS-10, 与告警重复, 能力数 65→64
- 修复: 按上下文定位 (name=动作限幅 / module=安全执行边界) 精确改回
- 铁律: 长串先替换; 短 ID 正则词边界 \bK1\b (防误伤 K10-12); 替换后跑 ID 唯一性自检;
  文档简写引用 ("SYS-01-L2/L4" 这种) 会被前缀替换拆坏丢前缀, 需上下文定位补全

## 场景-能力追溯自检
SCENES 每条需求点 {rid, desc, layer, capability, module}:
- capability 引用的 ID 必须存在于 FEATURE_LIBRARY
- layer 标注必须包含每个 capability 的实际归属层 (自检脚本抓出 6 处遗漏)
- 落地文件: tools/gui/model_feature.py / feature.dbc / docs/feature_list_v4_engineering.md
