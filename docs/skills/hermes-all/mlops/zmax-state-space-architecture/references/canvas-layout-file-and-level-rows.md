# 画布布局文件 flows/state_space_obs.json — L2/L3/L4 行定位与连线 (2026-09-08)

背景: 老倪 2026-09-08 指示 "Flow-Matching DiT 是 L3 功能, 直接接 VLM 通用视觉, 你改一下布局"。
排查发现 DiT 节点 (ssdec) 名字标 L3 却物理躺在 L2 感知融合行 — 布局错位。本文是改画布布局的完整方法。

## 文件定位 (别改错文件)
- **状态空间画布布局 = 仓库根 `flows/state_space_obs.json`** (55 节点 + 67 links, 2026-09-08)。
- ⚠️ `tools/gui/flow.json` 是 **simulink 画布** (13 节点, 顶层键含 `sim`), 不是状态空间。
- 改前 `cp flows/state_space_obs.json /tmp/xxx.bak`; python json 读改写:
  `json.dump(d, open(f,'w'), ensure_ascii=False, indent=1)`。

## 行结构判定
- 行 = `row_bg` 节点 (type=row_bg, w≈3000 背景条), 节点 y 落在所属行 `[row.y, row.y+row.h]` 区间才算在该行。
- 行带随版本重排漂移 — **用区间判断, 别背 y 数值**。2026-09-08 行序 (上→下):
  📦数据源 → 大模型层 → 🚀L3 高级自动 → 🔧L2 分段感知/融合/控制/状态机/技能/执行 → 验证层 → 🔭可视化。
- 分级行名带文字标记: 基础辅助功能/高级自动功能/专家自主功能 (L2/L3/L4 或 🏆L4 专家 等前缀)。

## 本次修复的错位案例 (2026-09-08)
- 🎯 Flow-Matching Action Head (DiT, id=ssdec, type=model): 名字/desc 属 L3 高级端到端,
  却 y=-195 (落在 L2 感知融合行, 夹在 sssensor 传感器融合 与 ssobs 43D obs 之间)。
- v5.2.0 (b5793e0c) commit 消息写明高级层设计位置: VLM y-1050 (后移 -635) / **DiT y-610**。
- 修复: `ssdec.y = -610` → 回到 L3 行内。**改布局前先 `git log -1 <layout commit> --format='%b'`
  读设计意图, 别自己猜坐标**。

## links 格式与端口冲突
- links 每条: `{"id","f"(源节点id),"t"(目标节点id),"f_port","t_port","label"}`。
- **同一 (t, t_port) 只能有一条源** — 2026-09-08 实锤冲突: lkvlm_ah (VLM out1 → ssdec in1
  "潜空间 z") 与 lkmc_dc (ssmani_c out1 → ssdec in1 "接触流形坐标") 双占 in1。
  修复: 主输入 (VLM z) 占 in1, lkmc_dc 改 t_port=in3 (in2 已被 lkmp_dc 性能流形代价占)。
- 校验脚本要点: 坐标全 int (字符串 → QRectF TypeError Fatal Abort 崩 GUI)、
  目标节点 y 在所属行内、ssdec 的 t_port 无重复、id 无重复。

## v5.2.0 高级层链路 (设计非残留, 别乱删线)
YOLO框/触觉/图像 (ssdata/sstactile/ssyolo) → VLM (ssvlm, SmolVLA 视觉编码器, 收 in1/2/3)
→ [流形专家预留: ssmani_c/ssmani_p 收 VLM out1 潜空间 z] → ActionHead DiT (ssdec)
→ 前馈融合 (lkdc_ff: ssdec out1 → ssff in2 "u_mani 解码建议")。
- VLM→DiT 直连 lkvlm_ah 与 VLM→流形 lkvlm_mc/lkvlm_mp 并存是 v5.2.0 设计 (端到端主线 +
  流形专家并行调制), 流形→DiT 的 lkmc_dc/lkmp_dc 同理是设计, 老倪没说删就别删。
- 2026-09-08 只动了位置 + 端口去冲突, 没删任何 link。

## 生效
- 改完 flow json 需 GUI 重启 / 重开状态空间画布 (运行中进程加载的是启动时旧 json)。
- 节点源码/功能映射在 tools/gui/node_logic.py (node_ss_vlm/node_ss_dec), 布局改动不影响它。
