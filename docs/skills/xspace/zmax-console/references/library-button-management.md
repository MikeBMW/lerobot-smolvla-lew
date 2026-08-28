# 模块库按钮管理坑 (2026-08-10 实测)

## 删按钮前先反查 VEH 编号 (用户报的编号可能是旧的)
LIBRARY_SEQ 序号随删除/新增动态重排 (删2加1=净-1, 后续全部前移)。
用户报的编号与实际按钮名经常错位 — 实测案例: 用户说"删掉 AWE VEH.5.14",
反查发现 VEH.5.014 = M03 GR00T (AWE 分组是 037-042)。
**删任何按钮前必跑**:
```python
QT_QPA_PLATFORM=offscreen python3 -c "
import sys; sys.path.insert(0, '.')
import simulink_module as sm
rev = {v: k for k, v in sm.LIBRARY_SEQ.items()}
for i in sorted(rev): print(f'VEH.5.{i:03d}', rev[i])"
```
拿不准就 clarify 确认 (删错资产代价高)。

## 删 LIBRARY 条目后的连锁同步
1. **REFERENCE_APPS 模板可保留** (模板用自己的 node specs, 不依赖 LIBRARY 按钮) — 别误删。
2. **ACT_BUILD_STEPS 引导必须同步**: 删除引用的按钮后引导会卡在对应步骤
   (用户点不到高亮按钮)。实测删 视觉主干 ResNet18 + VAE 编码器 后,
   ACT_BUILD_STEPS 从 9 步改 7 步并重编号。
3. 教程高亮 `self._lib_btns.get(name)` 已容错 (None 跳过), 不会崩。
4. 画布上从模板加载的节点会从稳定编号退化为 id%100 随机尾号 (名字未注册) — 可接受。

## 模块库按钮三种挂载 (LIBRARY 条目字段)
- 单节点: 默认分支 → add_node_at_center(ntype, name, params)
- 完整模型: `"flow": os.path.join(...flows, "x.json")` → it.get("flow") 分支 load_flow_file
- 模板: `"template": "参考应用名"` → load_reference_app_by_name
