# 第三方模型导入规范 (Z-MAX Model Package Standard v1)

> 2026-08-19 · 设计: 静静 · 目标: **只要标准格式, 一键导入即加载进平台**
> 对应能力库: feature.dbc (BU_ 节点 / CM_ 能力组合 / SG_ 信号契约)

---

## 一、保证机制 (为什么"只要标准格式就能加载")

```
第三方模型包 (标准格式)
    │
    ▼ ① 格式校验 validate  ── 不达标 → 拒绝导入 (强校验, 无灰色地带)
    │      manifest schema + 能力ID存在性 + 权重格式 + 接口声明合法
    ▼ ② 自动注册 register ── 写入 feature.dbc (BU_ 节点 + CM_ 能力组合)
    │      平台立即识别新模型 (数据字典树/模型列表自动出现)
    ▼ ③ 接口自动挂载 auto-wiring ── 按声明接口生成数据流适配
    │      平台提供标准 IN/OUT/CFG 基座, 模型只需实现「观测→动作」纯函数
    ▼ ④ 冒烟验证 smoke test ── 自动跑一次推理, 出动作即挂载成功
    │
    ▼ ⑤ 加载进状态空间 (平台运行环境, 可切换/可评估/可部署)
```

**四条硬保证**:
1. **校验保证** — manifest 缺字段/能力 ID 不存在/权重缺失 → 拒绝导入并报错
2. **注册保证** — 校验通过自动写 feature.dbc, 无需手工配置
3. **适配保证** — 无自定义适配器时用平台默认适配器兜底 (观测→动作直通)
4. **验证保证** — 冒烟测试出动作才算导入成功, 否则回滚注册

## 二、模型包格式 (目录/zip)

```
my_model/
├── manifest.json          # 模型声明 (必需)
├── weights/
│   └── model.safetensors  # 权重 (必需, 标准格式)
├── adapter.py             # 适配器 (可选, 缺省用平台默认)
├── config.json            # 推理配置 (可选)
└── README.md              # 说明 (可选)
```

## 三、manifest.json 标准 (schema v1)

```json
{
  "format": "zmax-model-v1",
  "name": "第三方插拔模型",
  "node": "EXT_MY_MODEL",
  "version": "1.0.0",
  "capabilities": ["B1", "C1", "C2", "D1"],
  "interfaces": ["IN", "OUT"],
  "weights": "weights/model.safetensors",
  "adapter": "adapter.py",
  "runtime": { "gpu": false, "latency_ms": 50 },
  "config": {
    "input_dim": 39,
    "output_dim": 4,
    "desc": "观测维度39, 动作维度4 (xyz+夹爪)"
  }
}
```

### 字段规则 (强校验)
| 字段 | 必填 | 规则 |
|---|---|---|
| format | ✅ | 必须为 `zmax-model-v1` (格式版本) |
| name | ✅ | 模型显示名 (≤32字符) |
| node | ✅ | 节点名, 大写+下划线, 唯一 (与 feature.dbc BU_ 不冲突) |
| version | ✅ | 语义化版本 x.y.z |
| capabilities | ✅ | 能力 ID 数组, **每个 ID 必须存在于能力库** (feature.dbc BO_ 列表) |
| interfaces | ✅ | 接口数组, 合法值: IN/OUT/CFG/TRAIN/DEPLOY/EVAL/MON/SCHED/GUIDE/MOD |
| weights | ✅ | 权重相对路径, 文件必须存在 |
| adapter | ❌ | 适配器相对路径; 缺省 → 平台默认适配器 (观测→动作直通) |
| runtime | ❌ | 运行时要求 (gpu/延迟), 平台据此调度 |
| config | ❌ | 模型配置 (输入输出维度等), 平台透传 |

## 四、接口契约 (adapter 实现标准)

平台定义标准接口基座, 第三方模型只需实现:

```python
# adapter.py 模板 (平台自动加载)
class ModelAdapter:
    # 输入: 标准观测 dict {image/state/tactile...}
    # 输出: 标准动作 dict {action: [...], info: {...}}
    def predict(self, obs: dict) -> dict: ...
    # 可选: 配置加载
    def load(self, weights_path: str, config: dict): ...
    # 可选: 说明
    def explain(self, obs: dict) -> str: ...
```

平台负责: 数据采集→标准观测组装→调 predict→动作下发→监控上报,
模型只需「观测→动作」, 数据流全由平台接管 (状态空间运行环境)。

## 五、导入流程 (GUI 一键)

1. 平台「导入模型」按钮 → 选模型包 (zip/目录)
2. 校验 → 失败显示原因 (哪项不达标)
3. 注册 → feature.dbc 自动加 BU_/CM_ → 数据字典树刷新出现
4. 挂载 → 加载权重 + 适配器 (或默认适配器)
5. 冒烟 → 自动跑一次推理 → 出动作 = ✅ 加载进状态空间
6. 可切换 → 模型列表出现新模型, 选中即用 (训练/评估/部署/监控同流程)

## 六、边界与回滚
- 能力声明越界 (能力库没有的 ID) → 拒绝
- 节点名冲突 → 提示改名
- 冒烟失败 → 自动回滚 feature.dbc 注册, 不留脏数据
- 权重格式不符 → 拒绝
