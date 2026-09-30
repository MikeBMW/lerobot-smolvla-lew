# L5 大模型层技术路线: 云 API 是零下载出路 + 61s 延迟的真因 (2026-09-22)

老倪指令: 「**L5大模型层给出技术路线，必须找到出路**」。背景: 本地 3B VL 权重反复下载失败
(HF 镜像大文件受限), 需要一条不依赖大权重下载的路。本文是实测取证与结论。

---

## 1. 出路就在 `scene_vlm.py` 已内置的三路径优先级 (别去别处找)

`src/lerobot/policies/left_right/state_space/scene_vlm.py` 的 `__init__` 解析顺序:

```
① 显式 SS_VLM_URL / SS_VLM_KEY   (OpenAI 兼容, 如 dashscope + qwen-vl-max)
② **DeepSeek 自带 key**  ← 本机 ~/.hermes/.env 已有 DEEPSEEK_API_KEY ⇒ 零申请成本, 直接可用
③ 本地开源 worker (smolvlm2-500m 等)
```

代码注释原文 (值得直接引用给用户):
> 「DeepSeek: deepseek-flash (DeepSeek-V4.1-Flash) **支持 Vision ✓** (官方 pricing 表; v4-pro 不支持)」
> 「格式与 OpenAI 兼容完全一致 (content blocks + image_url data URL)」
> 「本机 ~/.hermes/.env 已有 → **零申请成本, 直接可用**」

**实测 `status()` 落点**:
```
{'path': 'http', 'provider': 'deepseek', 'model': 'deepseek-flash',
 'detail': 'DeepSeek Vision (本机已配 key, 无需申请) https://api.deepseek.com'}
available: (True, '')
```

⇒ **结论: 本机已配 API key 时, 云 API 是零下载、零显存的最快出路。**
几 GB 的 VL 权重下不动时, **先试这条路**, 别在下载上耗时间。

## 2. 真实入口方法名 (别猜, 猜了就 AttributeError)

```bash
grep -nE '^\s{4}def [a-z]' src/lerobot/policies/left_right/state_space/scene_vlm.py
```

真实公开入口 = **`ask(image, prompt, system, max_tokens, ctx, allow_rule)`** ·
**`describe(image, ctx)`** · **`guide(image, ctx)`** · **`quality(image, ctx)`** · `close()`。
(`understand()` 不存在 —— 我第一次就猜错, 报 `AttributeError`。)

## 3. 能力达标: 返回结构化场景理解 (实测原文)

`describe(真机帧)` → `{"ok": true, "text": "<JSON字符串>", "src": "http:deepseek-flash", "json": {...}}`:

```json
{"目标可见": true, "目标是什么": "红色方块与青色小方块", "目标位置": "画面中上",
 "在夹爪上吗": false, "朝向": "看不清",
 "画面质量": {"模糊": false, "过暗或过曝": false, "太远或太小": false, "被遮挡": false},
 "光照": "均匀明亮，无明显阴影或过曝",
 "背景线索": "红色机械臂、木质桌面、透明围挡、灰色地面、黑色底座",
 "标定建议": "请操作员将红色方块和青色小方块摆放到桌面中央的绿色标记附近…"}
```

字段齐: 目标/位置/朝向/在夹爪上/画面质量/光照/背景线索/标定建议 ⇒ **够喂 L4 意图/L3 流程/L2 执行**。

## 4. ⚠️ 61.3s 的延迟 = **thinking 没关** (不是"API 慢/网络差")

实测 `describe()` 耗时 **61.3s**。而本技能正文记的基线是 **DeepSeek-Vision API 单帧 2.2s
(关掉 thinking: `SS_VLM_THINKING != 1`)**。

⇒ 差 28 倍 ⇒ **先怀疑 thinking 开着**, 而不是归因网络/服务。
**下次遇到秒级以上的 VLM API 调用, 第一步就是确认 `SS_VLM_THINKING != 1` 并复测。**

## 5. L5 的部署形态: 慢决策 ⇒ 必须异步旁路

即便优化到 2.2s, 与**控制回路的 101ms (10Hz)** 仍差一个数量级。所以:

```
① **不阻塞控制循环** — 按需触发 (换工件/换工位/异常时), 不进每帧回路
② **场景指纹缓存** — 同一场景不重复问 ⇒ 秒级延迟只付一次
③ **降级链** — API 超时 → 本地 500M → 规则兜底
```

这与画布 `node_ss_llm` 的既有定位一致 (「慢决策, 回路外」), 不是新发明。

## 6. 顺带确认: smolvlm2-500m 本地兜底**是完整的**

```
~/.cache/huggingface/hub/models--HuggingFaceTB--SmolVLM2-500M-Video-Instruct  = 5.7G
blobs 里 11 个 >10MB 文件, 含 1 个 1936MB 主权重 ⇒ 完整 (不是空壳)
```

**坑**: `find .../blobs -name '*.safetensors' | xargs ls` 可能显示 **0 MB** —— 因为 blobs 里是
**无扩展名的哈希文件**。**用 `-size +10M` 按体积找, 别按扩展名找**, 否则会误判"权重没下到"。

## 7. 坑清单

| 坑 | 对策 |
|---|---|
| 猜 `understand()` → `AttributeError` | 先 grep `def` 拿真实入口 (`ask/describe/guide/quality`) |
| VLM API 单帧 61s 就归因"API 慢" | 先关 thinking (`SS_VLM_THINKING != 1`) 再复测 |
| 按扩展名在 blobs 里找权重 → 判"没下到" | blobs 是无扩展名哈希文件, 按 `-size +10M` 找 |
| 3B 权重下不动就卡住 L5 | 先看 `SceneVLM.status()` —— 本机 DeepSeek key 已配, 零下载可用 |
| 想把 L5 塞进每帧控制回路 | 秒级 vs 101ms 差数量级 ⇒ 只能异步旁路 + 缓存 + 降级链 |
