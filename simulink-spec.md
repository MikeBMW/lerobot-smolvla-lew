# Z-MAX Simulink 模式 · 统一节点规范 v1.0 (2026-08-01)

> GUI 控制台 (PyQt5) 与 Web 工作台 (comfyui.html) 共用此规范。
> 两边 JSON 结构完全一致，可互相导入导出 / 实时同步。

## 1. 工作流文件格式 (Flow JSON)

```json
{
  "format": "zmax-simulink",
  "version": "1.0",
  "name": "800G DR8 产线流程",
  "sim": {"dt": 0.01, "t_end": 10.0, "solver": "fixed-step"},
  "nodes": [ ... ],
  "links": [ ... ]
}
```

## 2. 节点 (Node)

```json
{
  "id": "n3f2a1",
  "type": "hardware",
  "name": "Orin Nano",
  "x": 120, "y": 80, "w": 150,
  "icon": "🖥",
  "color": "#ff4444",
  "status_key": "orin_online",
  "params": {
    "ip": "192.168.23.10",
    "port": 8765,
    "fps": 30
  },
  "inputs":  [
    {"id": "in1", "label": "cmd", "dtype": "str"}
  ],
  "outputs": [
    {"id": "out1", "label": "state", "dtype": "float[7]"}
  ],
  "actions": [
    {"label": "▶ 采集", "cmd": "record_start", "duration": 30}
  ]
}
```

### 2.1 type 枚举 (5 类, 与 web comfyui.html 完全一致)

| type | 中文 | 颜色 (web/GUI 共用) | 说明 |
|------|------|--------------------|------|
| condition | 条件 | `#a371f7` 紫 | 信号条件/触发/逻辑判断 |
| model     | 模型   | `#58a6ff` 蓝 | VLA/ACT/SmolVLA/LEW 等策略模型 |
| action    | 动作   | `#00d4aa` 绿 | 取料/放置/插入/扫码等原子动作 |
| system    | 系统   | `#d4a800` 黄 | 调度/编排/工作流系统 |
| hardware  | 硬件   | `#ff4444` 红 | Orin/MAC/4090/机械臂/传感器 |

### 2.2 端口
- 输入端口画在节点**左侧**，输出端口画在**右侧** (Simulink 习惯)
- 连线从输出 → 输入，箭头指向输入

## 3. 连线 (Link)

```json
{"id": "l1", "f": "n3f2a1", "t": "n2b9c0", "f_port": "out1", "t_port": "in1"}
```
- `f` = 源节点 id, `t` = 目标节点 id (与 comfyui.html 的 L=[{f,t}] 兼容)
- `f_port`/`t_port` 可选 (缺省 = 单端口节点)

## 4. Simulink 交互规范 (GUI + Web 一致)

| 操作 | 行为 |
|------|------|
| 从左侧模块库拖拽 | 放到画布生成节点 |
| 双击节点 | 打开参数面板 (Block Parameters) |
| 从输出端口拖拽 | 画连线，松开到输入端口完成连接 |
| 点击连线中点 | 删除连线 (悬停显示 ✕) |
| 滚轮 + Ctrl | 画布缩放 (20% ~ 300%) |
| 空白处拖拽 | 平移画布 |
| Delete | 删除选中节点 (连带其连线) |
| Ctrl+D | 复制选中节点 |
| ▶ 运行 | 按拓扑顺序执行节点 (仿真时钟推进) |
| ⏹ 停止 | 停止仿真 |
| 单步 | 执行一个时间步 |

## 5. 运行语义 (Simulink 数据流)

1. 节点按 DAG 拓扑排序 (连线确定顺序)
2. 每个 time step: 源节点产出 → 沿连线传递 → 目标节点消费
3. 每个节点执行 `process(inputs, dt) -> outputs` (GUI 内本地模拟 / 或转发到实际硬件)
4. 无连线的节点: 独立运行 (如 4090 训练节点)

## 6. 同步接口

- GUI 导出: `{"nodes": [...], "links": [...]}` → POST `https://datadrive.world/api/comfy/task`
- Web 导入: GET `/api/comfy/status` 拉取节点运行状态
- 节点 id 生成: `n` + 时间戳 + 3位随机 (web 端 `'n'+Date.now()+rand` 同规则)
