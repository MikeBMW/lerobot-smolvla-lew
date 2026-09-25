# 运行中任务诊断: 老倪问「现在在干什么 / 为什么这么慢 / 这几千步在干啥」 (2026-09-15 实测)

> 触发场景: 用户在 GUI 里点了运行 (或别的会话/桥在跑), 把一段引擎日志粘给你问这三个问题。
> 目标 = 用进程/日志/测速三类证据回答**是什么、为什么慢、预算含义**, 并指出是否在空转。

## 一、先定位"是什么在跑" (进程级, 别猜)

```bash
ps -eo pid,ppid,etime,pcpu,stat,cmd --sort=-pcpu | grep -E "python|studio" | grep -v grep | cut -c1-230
```
常见三件套 (本例同时出现):
- `gui-venv311/bin/python studio.py` = GUI 主进程 (引擎/IPC/渲染都在它里面)
- `<INTACT-JEPA>/.venv/bin/python tools/intact_worker.py --task pusht --device cpu` = **INTACT 推理子进程**
  (父进程是 studio.py ⇒ 说明这次运行挂了 L4 档真推理)
- `tools/intact_sw_optical_bridge.py --task optical_insert --seeds 0,1 --max-steps 900` = L4 光模块插拔链条
  (跨 venv 桥; 跑完会在 `reports/intact_sw/status.json` 留 `stage=done` + step/seeds/honest_note)
- 桥跑完常留 `<defunct>` 僵尸 (父进程没回收) — **无害, 不用管**; 真结果读 status.json。

## 二、引擎日志在哪 / 不在哪 (关键, 别浪费时间 grep 文件)

- 进度行出处在 `tools/gui/state_space_sim_real.py:2620` 附近, **每 25 步一条**:
  `[{step}/{max}] 阶段=… 残差=… 接触p=… grp=… grasped=… · YOLO 检出率… / YOLO 未启动`
- GUI 跑出来的引擎日志**只进 GUI 日志框** (self.log → Qt 信号), **不落盘**:
  `ls -l /proc/<gui_pid>/fd/1` 指向 `/tmp/studio_launch.log`, 但该文件只有启动信息
  (INTACT 挂载 / 权重加载 / warning), **进度行不在里面**。
- 所以: 让用户贴日志 (或问步数), 别指望从文件里数步数; 命令行侧的桥才会写
  `reports/intact_sw/bridge.log` + `status.jsonl`。

## 三、max_steps 到底是什么 (回答"这几千步在干啥")

`RealStateSpaceSim.run(max_steps=None, cap=None)` 的 docstring 就是权威口径:
- **insert 模式**默认 **500** 步; **full 模式** (插拔+AOI 13 段) 默认 **2000** 步
- **`cap="l4"` (L4 档自主恢复) → 预算 ×2 ⇒ insert 1000 / full 4000**
- `DT_ENV = 0.1` 秒/步 (metaworld 标定) ⇒ **4000 步 ≈ 400 秒仿真时长**
- 正常成功一次: insert ≈380~700 步; full(含 AOI/光耦合) ≈850~1000 步
⇒ 看到 `[x/4000]` = **full + L4 档**, 4000 是"最多给这么多"的恢复预算 (正常成功的 4 倍),
**不是必须跑满**; 跑满只说明一直没恢复成功。

## 四、活体测速 (回答"为什么这么慢", 给 ETA)

采样 worker 的 CPU 时间增量即可反推步速 (凭据: 单次 INTACT CPU 前向 ≈ **1.4 s**, 每 **8 步** 消费一个 chunk):
```bash
r(){ awk '{print $14+$15}' /proc/$1/stat; }; a=$(r <worker_pid>); sleep 20; b=$(r <worker_pid>)
echo "20 秒 CPU 增量 $(( (b-a)/100 )) 秒"     # 100 tick = 1 秒 CPU
```
- 例: 20 秒 +12.76 s CPU → 前向 ≈12.76/1.4 ≈ 9 次 → 引擎 ≈ 9×8 = **72 步/20 秒 ≈ 3.6 步/秒**
- ⇒ 4000 步 ≈ **18 分钟**。瓶颈就是 **INTACT 跑在 CPU** (`--device cpu`), worker 吃 63% 单核 +
  引擎主进程 (渲染 224² 帧 + 控制) 再吃 30% 单核; **GPU 全程 0%**。
- 提速正解 = 把 INTACT 推理挪到 GPU (`INTACT_DEVICE=cuda`); CPU 上这个吞吐是上限, 不是卡死。

## 五、⚠️ 更要紧: 分清"慢"和"卡住空转"

**卡住签名** (本例):
- 阶段长期停在 **接近**、`grasped=False`、**残差恒定不变** (0.055→0.059)、`grp` 在 0.83~1.00 抖
- 对照: 正常解析链 "接近" 阶段**只有约 40 步**就进 "对位" ⇒ 停 1000+ 步 = 手根本没在动
- 最可能元凶 (有日志实证): **L2 记忆层开着** (`data/memory_layers.json` = `{"L2":1}`), 势场把模型动作
  **抵消成 ≈0** —— 桥日志原样:
  `🧲 记忆层介入 … 模型=[-0.101,-0.019,0.019] 场=[0.164,0.031,-0.032] → 合成=[-0.0001,0.0001,-0.0002,0.75]`
  (模型往一边推、势场反向拉 → 合成速度 1e-4 m/s → 阶段永远停在接近)
- 处置: 把 `data/memory_layers.json` 的 `"L2"` 改成 **0** (引擎下次 ▶运行 生效) 再跑; 别等它烧完预算。

## 六、纪律

- **别擅自 kill 用户 GUI 里正在跑的任务** —— 报告"是什么/为什么/在不在推进"+ 给**一条**明确建议
  (老倪不要选项菜单), 让他决定停不停。
- 汇报口径照老倪规矩: 实测数字 (步/秒、CPU 占比、ETA) + 证据出处 (哪行代码/哪个日志), 不吹不猜。
