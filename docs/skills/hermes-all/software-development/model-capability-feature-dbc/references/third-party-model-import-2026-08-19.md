# 第三方模型导入规范与实现 (2026-08-19)

规范文档: docs/third_party_model_spec.md (仓库内)
实现: tools/gui/model_importer.py
GUI 入口: model_tree.py 数据字典面板「导入」按钮 (后台线程, 完成后 refresh 树)

## manifest.json schema (zmax-model-v1)

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
  "config": { "input_dim": 39, "output_dim": 4 }
}
```

必填: format(=zmax-model-v1)/name/node/version/capabilities/interfaces/weights
node 规则: `^[A-Z][A-Z0-9_]{1,31}$` 唯一
capabilities 每个 ID 必须存在于 feature.dbc BO_ 列表 (硬校验, 拒绝不存在的)
interfaces 合法值: IN/OUT/CFG/TRAIN/DEPLOY/EVAL/MON/SCHED/GUIDE/MOD
adapter 可选 — 缺省用平台默认适配器 (观测→动作直通)

## adapter.py 契约

```python
class ModelAdapter:
    def load(self, weights_path, config=None): ...
    def predict(self, obs: dict) -> dict:  # 必须返回 {"action": [...]}
```

## 四步保证 (模型包 zip/目录 → 加载进平台)

1. validate_package(path) → (ok, errors) — 强校验, 不达标拒绝并列出原因
2. register_model(manifest) — 写 feature.dbc: BU_ 追加节点 + CM_ 行
3. load_adapter(pkg_dir, manifest) — 自定义 adapter 或默认直通
4. smoke_test(adapter, config) — 跑一次推理, 出 action 才算成功;
   失败 unregister_model(node) 回滚, 不留脏数据

## 权重格式决策 (评估结论)

- 自家训练/部署: safetensors (延续 Orin 热更新链路, 无 pickle RCE)
- 第三方导入: ONNX 优先 (格式中立 + 无 pickle + Orin TensorRT 路径)
  + .pth state_dict 兜底但必须 torch.load(weights_only=True)
- 原因: state_dict 本质 pickle, 第三方不可信包 = 任意代码执行后门

## 实测验证 (2026-08-19)

- 非法包 (能力 ID ZZ9 不存在) → 拒绝 ✓
- zip 导入 → 注册 feature.dbc + 默认适配器 + 冒烟通过 ✓
- feature.dbc 自动出现 EXT_TEST_MODEL 节点 + CM_ 组合 ✓
- 清理: unregister_model('EXT_TEST_MODEL') + rm third_party_models/<node>
