# Z-MAX Architecture PPT Layout Reference

## Three-Row Layout (User's hand-drawn version)

```
┌─────────────────────────────────────┐
│  Z-MAX 系统架构 · 三层总览           │
├─────────────────────────────────────┤
│  ┌────────────────────────────┐    │
│  │  SYS 2  云端训练            │ ← purple #7B2DC0
│  ├────────────────────────────┤    │
│  │  SYS 1                     │ ← blue #4472C4
│  │  ┌─────────┐ ┌─────────┐  │    │
│  │  │SYS 11   │ │SYS 12   │  │    │
│  │  │VLA-T    │ │Z-Flow   │  │    │
│  │  └─────────┘ └─────────┘  │    │
│  ├────────────────────────────┤    │
│  │  SYS 0  硬件驱动+原子功能   │ ← red #C00000
│  └────────────────────────────┘    │
│                        ┌──┐       │
│                        │V静│       │
│                        └──┘       │
└─────────────────────────────────────┘
```

## Layout Constants (in EMU for 13.33 x 7.5 inch slide)

Title:            (333138, 118973) 10515600 x 363875
Background frame: (2496000, 909956) 7200000 x 5398395
SYS 2 box:        (3216000, 1269000) 5760000 x 1080000
SYS 1 box:        (3216000, 2708043) 5760000 x 1800958
SYS 11 sub-box:   (3576000, 3068995) 2520000 x 1080000
SYS 12 sub-box:   (6096000, 3068995) 2520000 x 1080000
SYS 0 box:        (3216000, 4868044) 5760000 x 1080000 (RED)
V 静 marker:       (10848737, 91424) 804693 x 363875

## Template Colors (from 自主系统X.pptx)

Title text:     #002060 (dark blue)
Accent blue:    #0070C0
Body text:      #000000 (black)
Sub text:       #666666 (gray)
Orange accent:  #F7A90B
Red (SYS 0):    #C00000
Purple (SYS 2): #7B2DC0
Blue (SYS 1):   #4472C4
Light blue:     #58A6FF

## Product Iteration Phases

| Phase | Title | Dims | KPI | Color |
|-------|-------|------|-----|-------|
| Phase 0 | System0 · 原子功能 | A 标准接口 | L2基线 | green #3FB950 |
| Phase 1 | Sys-10 · ACT端到端+固定轨迹 | M + A | ±0.02mm | cyan #58A6FF |
| Phase 2 | VLA-T端到端泛化 | M+A泛化 | <70ms | purple #7B2DC0 |
| Phase 3 | Sys-12 · 精细感知潜空间闭环 | X + Z 扩展 | >99% | dark blue #4472C4 |
| Phase 4 | 全域认知 · 全系统 | Z·M·A·X 全域 | 7×24h | purple #A371F7 |

## KPI Bar (Home page top)

±0.02mm (定位精度) | >99% (连续成功率) | <70ms (推理延迟) | 1ms (控制周期)

## Console Architecture Module (L2/L3/L4 comparison)

Each column shows three rows:
- SYS2: 云端训练 (purple)
- SYS1: 边缘推理 with [SYS11 left] [SYS12 right]
- SYS0: 硬件执行 (red)

L2 features: offline training, ACT 52M, single station, no OTA
L3 features: remote deploy, SmolVLA, multi-station, OTA
L4 features: auto training 4090, VLA-T, full autonomous, dual-arm
