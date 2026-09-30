# 大模型判读结果面板 UI + 实时化 (2026-09-19 现场实录)

场景: 画布上放一个"视觉语言大模型"节点 (🧿/👁), 要让人**一眼看出工程在用某个 VLM**, 且**右键打开判读结果**,
能"清晰理解场景"。用户当场提了 4 条 UI 缺陷 + 1 条"为什么不实时", 逐条记下根因与修法。

## 1. 判读"实时"化 — 用户问"为什么不是实时更新的?"
根因: 节点/面板原来**只在点按钮或右键运行时**判读一次, 面板 5s 定时只是重读物化记录 → 看着不动。
正解 (已验证 0.00s 不阻塞、1.5s 内出新记录):
- `QCheckBox(自动判读) + QSpinBox(间隔s) + QComboBox(模式)`; `QTimer` 触发 →
  **判读必须放后台 `threading.Thread`**, 完成后 `pyqtSignal(dict)` **回主线程**刷新 (Qt 控件只能主线程改)。
- **按钮也走同一后台入口** — 同步调用会让慢判读期间界面像"死了", 用户以为没反应。
- 面板唯一数据源 = 每次判读**落盘**的 jsonl (`ts/mode/耗时/provider/json/why/帧`);
  没有记录就显示"暂无", **禁假值**。

## 2. 四条 UI 缺陷的根因与修法 (都可复用到任何画布弹出面板)
| 用户反馈 | 根因 | 修法 |
|---|---|---|
| "字体和背景都是黑色, 看不清" | `QDialog` 未设样式 → 深色主题下继承成黑字黑底 | 显式套**工程既有深色规范** (`tools/gui/calibration_dialog.py` 的 `_DARK`); **表格/原始输出框/复选框/微调框/下拉/滚动条都要写**, 漏一个就黑一块 |
| "最大化按钮不好使 / 窗口无法拖动" | `QDialog` 默认 flags 不含最大化; 以父窗口为 parent 被当瞬时窗口 | `setWindowFlags(Window｜MinMaxButtonsHint｜CloseButtonHint｜SystemMenuHint)` + `setWindowModality(NonModal)` + `setMinimumSize`; 再**记忆几何** (关闭写盘/打开恢复) |
| "含义里很多字被省略了" | 列宽写死 + 默认省略号 | `setWordWrap(True)` + **`setTextElideMode(Qt.ElideNone)`** + 关键列 `Interactive/Stretch` + 行高 `ResizeToContents`; 实测最长 28 字含义换 3 行完整显示 |
| "调整显示区域" | 固定布局 | 中部 **`QSplitter`** (可拖分隔条) + `resizeEvent` 立刻重排 (别等 5s 轮询) |

## 3. 无眼验证 UI (看不了图时的标准动作)
把窗口 `grab()` 成 QImage, **按像素统计**判"白字深底": 采样点亮度分布里"深底占比 + 亮字占比"。
实测判读表区域 **深底 90.3% / 亮字 9.69%** ⇒ 通过; 亮字占比≈0 就是黑字黑底。
比"我觉得应该能看清"可靠, 直接写进交付证据。

## 4. 右键入口的注册模式 (与工程既有套路一致)
`params.vlm_llm=True` → 在 `SimCanvas._show_node_menu` 里按 params 加 action →
`from vlm_panel import open_vlm_panel` 开窗。与既有 `params.calib_layer / verif_layer / viz_kind`
同一套路: **节点只用 params 声明"我右键能开什么", 渲染层不写死节点名**。

## 5. VLM provider 与节点接线 (同一功能的另一半)
- 接线形态: **帧类数据源 (环境/引擎真图/真机帧) + 任务指令 → provider 节点 → 场景理解层 → LLM 层
  (规划/推理/编排/意图解码/总装记忆)**。**不要把帧直接连给文本 LLM** — LLM 吃不了像素, 必须经 VLM 转场景文字。
- provider 优先级: `SS_VLM_URL`+`SS_VLM_KEY`(OpenAI 兼容) > DeepSeek(`~/.hermes/.env` 的 key,
  `deepseek-flash` 支持 Vision ✓; `deepseek-v4-pro` 不支持) > 本地 worker。
  **`SS_VLM_PROVIDER=local` 强制本地** — 否则 .env 有 key 时本地模型永远轮不到。
- 延迟现实: DeepSeek Vision **冷启 60~134s**(`thinking:disabled` 也慢), 只有 prompt 缓存命中 ~1s →
  **逐帧质检不可用**; 本地 3B 是 3~5s/帧的正解。分工: 慢 API 给"每步一次的少量判读", 本地模型给逐帧。
- 节点/面板的判读结果里必须带 `src` (哪个 provider/模型), 让人知道这条判读是谁给的。
