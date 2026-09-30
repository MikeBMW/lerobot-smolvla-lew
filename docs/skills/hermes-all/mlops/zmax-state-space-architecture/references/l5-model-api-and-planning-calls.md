# L5 大模型层调用口径: 规划类调用 + DeepSeek 推理模型坑 + "输出必须实测复核" (2026-09-26)

## 1. DeepSeek 模型调用 (本机 L5 节点/规划哨兵都用它)

- **`deepseek-flash` 是推理模型**: 响应 message 里有 `reasoning_content`(思考) 和 `content`(答案)。
  `max_tokens` 给小了(实测 800) → 全部预算被 reasoning 吃掉 → `finish_reason="length"` 且
  **`content` 为空字符串**(看着像"模型没回答"。诊断: 打印 `list(message.keys())` +
  `len(content)` + `len(reasoning_content)` + `usage.completion_tokens_details.reasoning_tokens`)。
  ⇒ 规划类调用 **max_tokens ≥ 9000**; 代码里加兜底: content 空则回退输出 `reasoning_content`(标注"这是推理过程")
- **耗时**: 规划类(长 prompt / 短答案) 实测 20~40s; 带真图的视觉类 实测 ~122s(文本路也 120s 量级)
  ⇒ 一律**异步/后台调用**, 别在 GUI 主线程或同步链路里调
- 账号可用模型: `deepseek-flash` / `deepseek-v4-pro`; 仓库配置的 `deepseek-flash` 即最新的 Flash(V4.1)
- 长输出会被 token 上限**截断**(本次"产品任务清单"表格只出了表头) → 如实记录"表体被截断",
  用前面已完成的小节执行, 别假装整份计划都拿到了

## 2. L5 "审视全局资源 → 出计划" 的调用模式 (`tools/l5_plan_review.py`)

1. 先用**可复跑的体检脚本**把真实状态抽成 JSON(控制台/数据 pipeline 五段/资源/服务/验证器),
   落 `reports/dev_platform_check_*.json` —— 别手工拼状态描述
2. prompt = 体检 JSON(截断到几千字) + **已定档事实清单**(带数字的结论: 哪些靶子判死/哪些口径关闭),
   要求输出: 断点/目标(含判据)/分阶段跨层计划/可立刻跑的训练任务(含防返工项)
3. 产出原样落 `reports/l5_plan_<ts>.md`(**不做二次加工**, 保留模型原文便于核对+引用)
4. 把 L5 点出的每一项**当成假设**, 逐条实测复核 (见 §3)

## 3. 铁律: L5 的输出是"假设", 结论以实测为准 (本次两条被证伪)

| L5 判断 | 实测复核 | 结论 |
|---|---|---|
| "页面注册含空串, 有未完成页" | 导航页 7 条全实 (`studio.py:11698-11704`), 空串来自**我自己体检脚本的正则** | ❌ 证伪(检查器 bug) |
| "GUI RSS 1.13GB, 疑内存泄漏" | 60s 两采样 1161368→1161560 KB = **+0MB**; 稳态是画布 87 节点+3D+Qt 缓存 | ❌ 证伪(无泄漏) |

- 教训: **体检脚本自己的正则/解析也会造假证据** → 报"发现 X"前先回到原始数据核一眼
- L5 判断为真时也要给出它没说的量: 例: L5 说"relay 最新是 mac_hw 非机器人流" → 实测
  `/api/relay/orin/status` 返回 `online=false, infer_count=0` ⇒ 本机只读订阅 Orin ROS 是活的,
  但 **Orin→云上行缺失** —— 这才是可交付给现场的断点描述
- 汇报时把"证伪了 L5 的哪两条"写出来(工程真实性), 别只留一条 L5 的漂亮结论
