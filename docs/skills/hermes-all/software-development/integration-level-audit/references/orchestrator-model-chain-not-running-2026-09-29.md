# 编排链"模型一条都没跑到"的审计法 (2026-09-29 实测)

场景: 用户点了一个档位 + ▶运行, 认为"所有模型应该跑起来", 但实际什么都没发生。

## 第 0 步: 先看编排的**阶段归属**, 别先怀疑模型

```bash
./gui-venv311/bin/python tools/<loop>.py --status     # 当前阶段/终态/最后结果
./gui-venv311/bin/python tools/<loop>.py --dry-run    # 阶段表 + GPU 空闲
```

实测 (L5 标注→训练闭环, 9 阶段): 终态 `failed · stage=interact · 2s` ⇒ **第 0 阶段就抛异常退出**,
后面 annotate/supervision/L2/L3/L4/merge 一个都没启动 —— 用户看到的"模型没拉通"其实是**编排首阶段崩**。

### 首阶段崩的典型根因: 只在一个分支里赋值的局部变量

`hil_bridge.build_snapshot()`:
```python
if not stage:
    stage_note = "..."        # 只在 this 分支赋值
return {... "stage_note": stage_note ...}   # 无条件引用 → 另一条路径 UnboundLocalError
```
排查手法: 让编排把**每个子阶段的异常文本**落盘 (`*_state.json` 的 `snapshot_err` / `error` 字段),
不要只看终端最后一行。异常文本比"没反应"信息量高一个数量级。

## 第 1 步: 区分 fatal / non_fatal —— 可选输入的缺口不该掐断整链

实测三个连环卡点 (全是**可选输入**, 不是模型接不上):

| 卡点 | 症状 | 判定 | 处理 |
|---|---|---|---|
| 槽位未演示 | `stage_slots` ok=False | 下游 (L2) 本来就有退路 (退回监督数据集) | 标 `non_fatal`, 告警继续; 数据/代码错仍致命 |
| 数据集 val 空 | ultralytics `AssertionError: val: No images found` | 红线要求"自动标注样本绝不进 val" ⇒ 新集天然无 val | 训练用自动标注集, **val 用既有真机人工留出集**软链补齐 (红线不破, 口径诚实) |
| 训练跑完但真推理 0 框 | 数据量不足 (train 9 图) | 训练机械跑通 (rc=0 + best.pt 在位) | 标 `non_fatal` (**权重仍标"未过闸、不上在役"**, 绝不悄悄上线) |

终态三档口径: `done` / **`done_with_gaps`** (只有 non_fatal 缺口) / `failed`, 并落 `gaps` 列表 ——
既不让可选缺口把整链报成"失败", 也不装作全绿。GUI 徽章要同步认识新枚举值 (否则显示原始英文串)。

### 踩过的具体坑: 软链补 val 时图像/标签扩展名不同
图像 `.jpg` / 标签 `.txt`: 两路都用同一个 basename ⇒ 标签侧永远匹配不到 ⇒
`images/val` 有图而 `labels/val` 0 个 = **val 全变背景图, 评估失效**。必须按 stem 分别映射扩展名;
且幂等判据要"**图和标签都非空**才跳过", 只看图会永远补不上标签。

## 第 2 步: 逐节点断点清单必须走真注册表 (别写正则)

`tools/ss_node_debug_map.py` (本技能 `scripts/canvas_node_debug_map.py`) —— 只读, 对每个画布节点输出
`节点 → 档 → 连线数 → 注册 key → 执行函数 → 文件:行`, 顺带报"未注册 / 孤岛"计数。
实现: `from lerobot.engineering.registry import match_node, NODE_LOGIC` + `sourceview.get_node_location`,
与 GUI 双击分派**逐字同源** (自写 `_reg("key"` 正则漏掉循环注册)。
实测: 73 节点 / 178 连线 / 未注册 0 / 孤岛 0。

## 第 3 步: 三种调试入口的边界 (用户"逐节点 debug 数据流"前必须讲清)

| 入口 | 会真跑节点函数吗 | 断点能进哪 |
|---|---|---|
| ▶运行 (不勾引擎快演) = 真实化流程 | 引擎每步真跑, 节点函数按播放帧走 | 引擎 `state_space_sim_real.py` + 节点函数 |
| ⏭单步 / 右键运行节点 / 双击 | **是** (`execute_node_logic` 真调) | 节点函数真身 (`ZMAX_DEBUG_BREAK=<名子串>` 可在分派前停) |
| ▶运行播放演示 (`demo=True`) | **否** (读引擎帧数值) | 节点函数里的断点**不会停** —— 设计如此, 不是绑定问题 |
| 编排/训练子进程 (`Popen`) | 独立进程 | GUI 的断点进不去 → 必须单独 F5 那个脚本 |

## 第 4 步: HTTPError 503 先判"是不是本地取帧服务"

实测 6 路标注里 4 路 `err=HTTPError: HTTP Error 503`, 第一反应是"大模型限流"——**错**。
判法:
```bash
for c in arm local local2 depth aoi_gold aoi_surface; do printf '%-12s ' $c; \
  curl -s -m 6 -o /dev/null -w 'HTTP %{http_code} %{size_download}B\n' \
  "http://127.0.0.1:8791/snapshot/$c.jpg"; done
```
`503 / 40B` = 本机取帧服务"该路没有帧"(上游 Orin/相机/工控机不在线或该路未启用),
和云端视觉档无关。**先分清"没数据"与"模型报错"**, 否则会去修错的地方 (还会把"加 VLM 重试"当成修复)。

## 汇报口径

- 逐卡点给: 症状 (实测文本) → 根因 (file:line) → 改动 → 证据 (命令/数字)。
- 缺口如实列 (§6): 哪几路没帧 / 权重为何不可用 / 还缺什么输入, 不夸大"已全部拉通"。
