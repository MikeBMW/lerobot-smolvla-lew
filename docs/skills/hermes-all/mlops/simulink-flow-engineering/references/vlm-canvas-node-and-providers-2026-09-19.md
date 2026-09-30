# 画布上的视觉语言大模型 (VLM) 节点: provider 选型 / 提速 / 结果面板 (2026-09-19 实测)

老倪: 「任务规划器 LLM 也要感知到视觉, 增加 Qwen2.5-VL / Qwen3-VL … 做一个 deepseek-v4-flash 节点, 显示的连接线接入
状态空间流程, 你来设计 UI, 让用户明确感觉到这个工程是在人机在环地使用 deepseek 视觉语言大模型的方案」。
（同类内容曾想写进 `cross-venv-model-canvas-node`，该技能是用户自有、自动策展写入被拒，故落到本技能。）

## 1. 接线形态 (画布)

`帧类数据源(环境帧 / 引擎逐帧真图 / 真机帧) + 任务指令(MES 工单) → 🧿 provider 节点(VLM) → 👁 场景理解层 →
文本 LLM 层(任务规划器 · 异常推理器 · 技能编排器 · INTACT 意图解码器 · 总装记忆)`。

- **不要把帧直接连给文本 LLM**：LLM 吃不了像素，必须经 VLM 转场景文字 —— 用户会问"视觉输入在哪里"，要在回复里解释这条。
- provider 节点 `params.vlm_llm=True` + 真机/环境帧入线 + 后续 5 条出线，整条路径在拓扑上一眼可见。
- 有意重接 (`帧→👁` 改成 `帧→🧿`) 在零回退工具眼里是"丢 3 增 3" → 报告里说明是用户要求的 UI 变更。

## 2. provider 选型与实测数据

| provider | 结论 |
|---|---|
| DeepSeek `deepseek-flash` (V4.1-Flash) | **支持 Vision ✓**(官方 pricing 表)；`deepseek-v4-pro` **不支持**；旧名 `deepseek-v4-flash-vision-exp` 已退役并入 V4.1-Flash |
| DeepSeek 延迟 | **冷启 60.9s / 134.3s，prompt 缓存命中 0.84s**；显式 `"thinking":{"type":"disabled"}` 后**仍慢**（快的那些是命中缓存）→ **逐帧质检不可用**，只适合"每步一次的少量判读" |
| 本地 Qwen2.5-VL-3B | 权重 7.1GB；**bf16 需 ~6.5GB 显存** → 8GB 卡+其它进程(~1GB) 同住会 **CUDA OOM**（实测只剩 8.62MiB）→ 上卡要 4bit(~2.5GB) 或 CPU |
| 权重下载 | **必须避开 `~/.cache/huggingface`**：磁盘守护会删 `*.incomplete`，正在下的权重被删 → `FileNotFoundError: ...incomplete`（实测白下 4.9GB）→ `HF_HOME=~/zmax_data/hf_home` |
| Qwen API | 秒级需 key；百炼 https://bailian.console.aliyun.com/ · SiliconFlow https://cloud.siliconflow.cn/account/ak · OpenRouter https://openrouter.ai/keys |
| key 兜底 | GUI 进程 env 通常没 key → 客户端直接解析 `~/.hermes/.env`（DeepSeek key 本机已有 = **零申请可用**） |
| 强制本地 | `SS_VLM_PROVIDER=local` 跳过 HTTP provider；否则"检测到 DeepSeek key"会一直优先于本地 worker |
| 分工 | DeepSeek = 少量高把握判读（慢无妨）；本地 Qwen 3B = 逐帧引导；最终运动决策仍由主 agent/操作员把关 |

请求体(OpenAI 兼容，与官方 vision guide 一致)：`messages[].content = [{type:text},{type:image_url,image_url:{url:data:image/png;base64,...}}]`
+ DeepSeek 专有 `thinking:{type:disabled}`。

**实测判读质量**（真机帧，可逐条报给用户）: `目标=光模块(带绿色拉环的金属模块)` · `位置=画面中上偏左` ·
`朝向=竖直,拉环朝上` · `画面质量{模糊/过暗/太远/遮挡}=全 false` · `背景=左右黑色料盒+中央白色标定板+下方金属夹具底座` ·
`标定建议=把模块平移至下方夹具底座中心并夹紧`；`guide` 模式额外给「目标是否在夹爪里=false + 下一步动作 + 验收判据」
—— 正好补上人工标定缺的那一环。**输出不合 JSON 时要如实报"不是合法 JSON"而不是编造**（轻量模型如 500M 会答 `"true"`）。

## 3. 判读结果面板 (PyQt5) 要点

- 窗口: `vlm_panel.py`，右键菜单由 `params.vlm_llm` 触发（`simulink_module._show_node_menu` 加 action + 分派 `open_vlm_panel`）。
- 数据单一来源: 每次调用落盘 `~/zmax_data/vlm_calls.jsonl` → 面板只读它（没有记录就显示"暂无"，**禁假值**）。
- 字段表三列 `字段 | 含义(物理/工程) | 模型判读`（键翻人话）；底部固定**人机在环红线**一行。
- 交互/配色铁律（最大化按钮、深色白字、不许省略、QSplitter）见 `zmax-console/references/dialog-interaction-and-legibility-2026-09-19.md`。
