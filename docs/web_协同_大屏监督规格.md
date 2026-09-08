# web 协同：大屏动作级监督扩展规格 (P1/P2) — 2026-08-10

> 方案: docs/factory_fine_ops_supervision.md (已提交 a9f62316)
> 目标: factory-dashboard.html 每机器人卡增加"动作级指标"监督区

## 1. 数据模型 (每机器人卡新增 action 字段)
```javascript
action: {
  stage: 'INSERT',          // 状态机阶段 0-7: APPROACH/ALIGN/DESCEND/GRASP/LIFT/TRANSFER/INSERT/DONE
  stageIdx: 7,              // 0-7 数字 (大屏可画进度 [7/8])
  scenario: 'PEI-Cover-组装', // 场景1-6: WB键合/DA贴装/AA耦合/PEI-Cover/隔离器/COC共晶
  metrics: [                // 该阶段监督指标 (名称/值/单位/目标/达标)
    { k: 'd_ins', name: '插入深度', v: 0.02, unit: 'mm', target: 0.1, pass: true },
    { k: 'f_ins', name: '插入力',   v: 7.2,  unit: 'N',  target: 10,  pass: true }
  ],
  pass: true,               // 全部指标达成?
  lastFail: null            // 最近未达标项 {k, name, v, target}
}
```

## 2. 8 状态阶段指标模板 (前端预置, 按 stage 显示)
```javascript
const STAGE_METRICS = {
  APPROACH: [{k:'d_hp', name:'收敛距离', unit:'m', target:0.06},
             {k:'t_appr', name:'接近时间', unit:'s', target:1.5}],
  ALIGN:    [{k:'e_xy', name:'对位误差', unit:'mm', target:0.5}],  // 精密场景 target=0.001
  DESCEND:  [{k:'e_z', name:'到位精度', unit:'mm', target:0.2},
             {k:'v_desc', name:'下降速度', unit:'m/s', target:0.5}],
  GRASP:    [{k:'contact', name:'接触概率', unit:'', target:0.5},
             {k:'grip_f', name:'夹持力', unit:'', target:0.6},
             {k:'ok', name:'抓取成功', unit:'', target:1}],
  LIFT:     [{k:'dz', name:'抬升高度', unit:'cm', target:8},
             {k:'t_lift', name:'抬升时间', unit:'s', target:0.5}],
  TRANSFER: [{k:'t_xfer', name:'转移时间', unit:'s', target:2},
             {k:'e_xy2', name:'到位偏差', unit:'mm', target:5}],
  INSERT:   [{k:'d_ins', name:'插入深度', unit:'mm', target:0.1},
             {k:'f_ins', name:'插入力', unit:'N', target:10},
             {k:'done', name:'完成判定', unit:'', target:1}],
  DONE:     [{k:'hold', name:'保持稳定', unit:'', target:1},
             {k:'t_done', name:'阶段节拍', unit:'s', target:999}]
};
```

## 3. API 契约
```
GET  /api/robot-action?robot=R3&zone=oe   → {stage, stageIdx, scenario, metrics[], pass, ts}
POST /api/action-log                      → 记录 {robot, stage, scenario, metrics[], pass, ts}
GET  /api/action-log?robot=R3&date=today  → 历史记录数组
```

## 4. 展示 (每机器人卡, 插在现有 速度/节拍/负载/温度 上方)
```
当前动作: 插入 (PEI-Cover-组装) [7/8]
┌ 动作指标 ────────────┐
│ 插入深度 0.02/0.10mm ✅│
│ 插入力 7.2/10.0N ✅    │
└──────────────────────┘
```
- 达标 ✅绿 / 临界(>90%目标) ⚠️黄 / 超标 🔴红
- 单指标超标 → 卡 warning; 关键指标超标或连续3次 → alarm + 告警列表
- actionLog 追加留痕, 可点开看时间线

## 5. 模拟数据 (P1 演示)
- 现有 simulate()/setInterval 模式扩展: 每个机器人按场景循环 8 阶段, 指标带 ±噪声
- 场景1-6 分配: R1=WB键合 / R3=DA贴装 / R4=AA耦合 / R5=PEI-Cover / R6=隔离器 / R7=COC共晶
- 真机接入: left_right select_action 每 N 帧上报 (P3)

## 6. 场景3D (factory-3d.html) 联动
- 机器人当前动作时, 3D 场景高亮对应工位 (zone 闪烁 + 工具提示显示 stage)
- 与 dashboard 同数据源 (/api/robot-action 轮询)
