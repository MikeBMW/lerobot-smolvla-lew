# INDEX (part 2, 2026-09-14 下半场) — 新增 reference + 待并入 SKILL.md 的文本

> 为什么又开一个索引: 本 skill 的 `SKILL.md` 与既有 `references/00-INDEX-new-additions-2026-09-14.md`
> 编辑被 "read-before-write + skill_view dedup 不返回内容" 卡死 (同一路径二次 view 只回 dedup 标记,
> 门禁要求"本轮已加载内容"), 于是新内容只能落新文件。**下次前台会话 (能正常 view+patch) 请把下面
> 三节并入 `SKILL.md`, 并补 `## 参考` 指针。**

## 新增文件 (本轮已落)

- `references/live-run-triage-and-silent-degrade-2026-09-14.md`
  A) 「我现在正在运行呢, 断点无反应」现场判定 (GUI 起子进程 + pydevd `--multiprocess` 已接上)
  B) 静默退化: `Model.__init__` 次数 = 步数 (ckpt `device_processor.device` 写死 cuda) 根因 + 修法 + 修后数字
  C) 相邻技巧: py-spy 活进程真栈 / `HF_HUB_OFFLINE=1` 解探针卡网络 / 打桩失败要打印

## 待并入 `SKILL.md` 的三节 (标题即建议小节名)

### 「断点没进来 / 断点无反应」= 运行期取证, 不是读代码

四步: ①那行属哪个分支 (训练 loss 行在推理里永不含命中: `forward` vs `predict_action`) ②该分支在那条链上
被构造/调用了吗 (档位装配会 `pop` 掉别档开关; 直驱绕过槽位) ③用户说"正在运行"时先查那个 run **是什么进程**
(`ps` 树 + `ss -tnp` 看子进程是否 ESTAB 到 debugpy adapter + `ps` STAT `t/T` 看有没有进程真停在断点 +
产物 mtime/ffprobe 判跑完没有 + `grep -c "<目标模块>" <入口脚本>`) ④上探针 (`templates/probe_runtime_callchain.py`),
必带微对照 (`forward()` 命中 loss 行 / `predict_action()` 增量 0)。

铁律: `CUDA_VISIBLE_DEVICES=""` 跑探针并回查 `nvidia-smi` 证明训练未扰动; 同口径数字;
复刻 GUI 装配 (同一份 `install_direct_act`); 必须给"可命中的替代断点位置"; 区分"没跑"与"跑了被硬闸拒绝";
探针自身坑 —— `def` 行 0 次行事件要报函数级计数+函数体行区间 (实例: `predict_action` 1 次 · 主体 313-345 命中 39),
字符串替换改脚本会静默 no-op (改完 `grep -c` 回读), 打桩目标名不存在要记"打桩失败"。

### 静默退化: "计数 0 + 模型被反复重载" = 载入路径在失败循环

`Model.__init__` 次数 == 步数 (12 步 → 12 次, ~4s/步, 625M 反复载入) 且引擎侧调用计数 0 ⇒ 载入抛错被吞 +
类级缓存赋值排在失败语句之后。抓原始异常 (包一层引擎方法 / 收集引擎 log 过滤 `⚠️|失败`)。
修法 = 官方 eval 同款 `preprocessor_overrides/postprocessor_overrides={"device_processor": {"device": dev}}`
+ 设备 env 可覆盖 + 失败熔断 (`*_FORCE_RETRY=1` 复位)。修后 12 步实测: `__init__` 12→1 · `select_action` 0→3 ·
`head.predict_action` 0→1 · 引擎 l3_calls 0→12 · loss 行 307 仍 0。改完必跑未受影响档零回退复测 + 语法检查。

### 假接入第 8/9 形态

8. 画布` 画了拓扑、运行期不调` (节点在真实装配里被 `pop` / 被直驱绕过) → 运行期计数 0。
9. `静默退化 + 每帧重载` (载入失败被吞 → 每帧重试加载并退回解析链, 面板看不出异常) → 判据同上一节。

## 建议补的 `## 参考` 指针

```
- references/breakpoint-not-hit-branch-audit-2026-09-14.md — 「断点没进来」取证数字 (训练 loss 行 + 档位 pop 双因)。
- references/live-run-triage-and-silent-degrade-2026-09-14.md — 「正在运行但断点无反应」现场判定 + 静默退化(每帧重载)根因与修法。
- templates/probe_runtime_callchain.py — 运行期调用链探针 (函数级 + 行级计数)。
```
