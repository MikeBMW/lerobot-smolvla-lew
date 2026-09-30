# 状态空间断点"又进不去" — 根因④: 真实采样延迟 + 数据源节点优先 (2026-09-01)

## 现象
v3.3.5 节点真实执行改造后, 用户点 ▶运行, 断点设在 node_metaworld_data 里又进不去。
环境全对: 进程是新代码(晚于 node_logic.py mtime)、`ZMAX_DEBUG_BREAK=metaworld` env 在、
debugpy 已连接、`/tmp/simulink_log.txt` 显示状态空间画布加载正常。

## 根因链
1. 真实化后 `_ss_tick` 逐帧真实执行节点: 📡传感器融合首次执行 `_ss_env_obs` →
   `_yolo_ensure_aligner` 加载 YOLO 权重(6MB)+metaworld env 创建+render, 主线程阻塞 10s+;
   🎯YOLO 节点推理 2-5s。
2. 数据源节点(📦 metaworld 数据源)在 `_ss_order` 里排第 17 位(画布 nodes 顺序)。
3. 播放 22 帧要 20-40s 才轮到数据源 → 用户等不及, 误判"断点又坏了"。
4. 日志佐证: 停在"🧠 任务规划器"后长时间无节点执行日志(卡在真实采样)。

## 修复 (simulink_module.py `_start_state_space_sim`)
```python
self._ss_order = [n for n in self.nodes if n.get("type") != "row_bg"]
# 数据源节点(数据流源头)排到第 1 帧 — 断点调试第 1 帧即停
_src = [n for n in self._ss_order if "数据源" in n.get("name", "")]
_rest = [n for n in self._ss_order if n not in _src]
self._ss_order = _src + _rest
if _src and getattr(self, "_log", None):
    self._log(f"⏩ 数据源节点优先: 「{_src[0]['name']}」第 1 帧执行 (断点调试命中快)")
```

## ⚠️ 误匹配坑 (踩过)
第一版判断条件用了 `"数据源" in name or params.get("source")` —
**params.source 是右键源码映射字段, 状态空间画布全 22 节点都有** → `_src` 匹配到全部节点
→ 排序无效(数据源还是第 17 位)。只按节点名"数据源"匹配才正确。
验证: 模拟排序断言 `new_order[0] is 数据源节点` 且 `len == 原节点数`。

## 诊断顺序 (用户报"断点进不去")
1. `/proc/<pid>/environ` 查 ZMAX_DEBUG_BREAK 是否在 (env 被 open_in_vscode 右键重写覆盖过 — 根因①)
2. `/tmp/simulink_log.txt` 尾部: 目标节点日志("📦 数据源:")没出现 = 没执行到
   (帧数截断=根因② / 卡在真实采样=根因④); 有日志但断点没停 = 断点绑定问题
3. 进程是否暂停在断点: `/proc/<pid>/status` State + 主线程 wchan(poll_schedule_timeout=空闲,
   futex 等待=可能暂停在 debugpy)

## 调试 GUI 固有规律 (老倪体验)
- 断点暂停 = 主线程冻结 = 所有窗口关不掉 + Windows 弹 "studio.py is not responding"
- 弹窗点「等待」(Wait), **勿点「关闭程序」= 杀进程断点全丢**
- 切 VSCode 按 F5 继续即恢复; 动作快(<5s)可避免 Windows 检测弹窗
- execute_node_logic 暂停前已打 🔴 日志提示(去 VSCode F5 继续)
- 真实采样节点(传感器融合/YOLO)首次执行 10s+ 卡顿是真实计算代价, 同进程内 `_YOLO_ALIGNER`
  缓存后第二次秒级; 每次重启 GUI 首次运行仍要等 — 别当 bug 修
