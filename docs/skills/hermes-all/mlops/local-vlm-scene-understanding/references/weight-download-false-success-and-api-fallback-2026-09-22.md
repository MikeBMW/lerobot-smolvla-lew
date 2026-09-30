# 权重"下载成功"的假象: 判据用文件数+体积, 不用进度条 (2026-09-22)

补 SKILL.md 的"### 一、先确认权重到底下好没有" —— 另一种形态:
**下载流程正常结束、进度条接近 100%、但权重文件一个都没到。**

---

## 1. 症状: 进度条说成功, 实际只有配置文件

```
Fetching 14 files: 86%|████████▌ | 12/14 [00:04<00:00, 2.25it/s]     ← 看着像成功
du -sh ~/.cache/.../models--Qwen--Qwen2.5-VL-3B-Instruct   = **12M**   ← 只有配置
find ... -name '*.safetensors' | wc -l                     = **0**     ← 真权重没到
```

另一形态: `Fetching 11 files: 0%| | 0/11` 后直接结束, 仍 12M / 0 safetensors。
两次尝试 (默认下载 / 显式 `allow_patterns=['*.json','*.txt','*.safetensors','*.py']` + `max_workers=2`)
都只拿到 json/py, **拿不到 safetensors**。

⇒ **别信进度条的 file 计数**, 只信三者:
```bash
M=<hub>/models--<org>--<repo>
find $M -name '*.safetensors' | wc -l     # ① 权重文件数 (0 = 没下到)
du -sh $M                                 # ② 与预期体积对比
find $M -name '*.incomplete' | wc -l      # ③ 残片数 (0 且①>0 才算完整)
```

## 2. ⚠️ blobs 是**无扩展名哈希文件** —— 按后缀找会误判"没下到"

```
.../SmolVLM2-500M-Video-Instruct/blobs/
  4696831e...  (180 MB)
  7d0a3565...  (348 MB)
  b9bfd456...  (1936 MB)   ← 主权重在这里, 但**没有 .safetensors 后缀**
```

`find -name '*.safetensors'` 返回 0 个 / 显示 0 MB ⇒ **误判"权重没下"**。
**正确**: `find $M -type f -size +10M` 按**体积**找, 再核数量与总量
(实测 smolvlm2-500m: 11 个 >10MB 文件、共 5.7G ⇒ **完整**)。

## 3. 决策规则: 先问"这能力是不是非它不可", 再决定是否继续重下

**在继续重试几 GB 下载之前**, 按此顺序排除:

1. **已配置的云 API 是否覆盖同一能力？**
   实例: L5 要 Qwen2.5-VL-3B, 但本机 `~/.hermes/.env` 已有 `DEEPSEEK_API_KEY`
   ⇒ `SceneVLM.status()` 走 `deepseek-flash` (支持 Vision) ⇒ **零下载零显存即用**。
   详见 `local-vlm-scene-understanding`
   → `references/l5-route-cloud-api-and-thinking-latency-2026-09-22.md`。
2. **更小的等价权重**是否已下好？(smolvlm2-500m 完整在位 ⇒ 可做本地兜底)
3. 都不行再换渠道 (内网镜像/网盘/其它 endpoint) —— **让用户给渠道**比自己硬重试快。

## 4. 同类历史 (说明这是**反复出现**的形态)

```
paper-e5-goal-v1        : 下到 1.3G 后 timeout(exit=124), 未果
reacher.tar.zst (23.75G): 多次断流, 后由另一会话补齐
qwen2.5-vl-3b (~6G)     : 两次尝试, 只有配置到, 0 safetensors
```

⇒ **大文件 (>1G 级) 是该渠道的稳定薄弱点**。**一开始就留退路** (先确认云 API / 小模型兜底
是否够用), 别等重试两轮才回头找替代。

## 5. 报告口径

> 「两次下载均失败: 只拿到配置文件, **0 个 safetensors** (进度条 12/14、0/11 都不可信)。
> 但该能力已有替代: 本机 DeepSeek Vision key 已配 (实测可用) + smolvlm2-500m 本地完整。
> 3B 只在需要更强理解时才必要; 若要它建议走内网镜像/网盘 —— 您有渠道我直接拉。」

**要点**: 失败报**确切缺失证据** (0 safetensors), 替代报**已实测可用**, 给用户**明确的下一步**
(提供渠道), 而不是把"再试试"当结论。
