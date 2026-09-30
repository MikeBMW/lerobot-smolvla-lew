# 条件技能 → 动作技能 硬件映射

> 小芳 · 验证框架

## 数据闭环

```
条件技能(环境输入)         模型推理            动作技能(硬件输出)
C001 100G取料条件 ──→  Sys-1 ACT ──→  A001 100G取料动作
C002 400G取料条件 ──→  Sys-11 SmolVLA ──→  A002 400G取料动作
C003 插入条件      ──→  Sys-12 LeWorld ──→  A003 力控插入
C011 AOI_1条件     ──→  Sys-21 VTLA ──→  A011 AOI_1检测
...
```

## 硬件验证

```python
# 验证条件→动作闭环
for cid, aid in CONDITION_ACTION_MAP.items():
    condition = gds.get(f"cond_{cid}")   # 环境输入数据
    action = gds.get(f"act_{aid}")       # 模型输出的动作
    
    verify(condition, action)  # 硬件验证
```

## Condition ID 清单

| ID | 条件技能 | 输入数据 | 输出动作 |
|:---:|:---|:---|:---|
| C001 | 100G光模块取料 | 姿态+力 | A001 取料 |
| C002 | 400G光模块取料 | 姿态+力 | A002 取料 |
| C003 | 插入测试座 | TCP+力 | A003 力控插入 |
| C004 | 拔出 | TCP | A004 拔出 |
| C011 | AOI_1 | 图像 | A011 AOI_1 |
| C012 | AOI_2 | 图像 | A012 AOI_2 |
| C021 | NG分拣 | 结果+料盘位 | A021 NG放置 |
| C031 | 扫码 | 码值 | A031 扫码校验 |
