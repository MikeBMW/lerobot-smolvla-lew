# GUI 部署功能与路径/类归属坑 (2026-08-09 实测)

## 🐛 repo 根路径必须 3 层 dirname (tools/gui/studio.py)

`studio.py` 在 `tools/gui/` 下, `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
只有 2 层 = **`tools/` 目录**, 不是仓库根! 仓库根需要 **3 层**:
```python
root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```
**症状**: 读 `models/saved/registry.json` 时拼成 `<repo>/tools/models/saved/registry.json` →
`os.path.exists` False → 部署模型下拉空、registry 兜底失效(异常被 except 吞, 界面静默空白)。
**排查**: 打印 `reg_path` 看是否多了一层 `tools/`。
**规则**: 在 tools/gui/ 下的文件, 凡引用仓库根一律 3 层 dirname; 已有 `_repo_root()` 方法的类直接用
(它已是 3 层)。验证脚本断言时注意函数内可能用 `_os.path` 前缀 (import os as _os), 别只匹配 `os.path`。

## 🐛 方法误放类 → AttributeError 静默吞 → 界面空

`_refresh_deploy_models` 曾被 patch 进 **InferencePanel** 类(8087 行区域), 但调用点在
**TrainingModule**(2528 行) → `self._refresh_deploy_models()` 抛 AttributeError →
被 `except: pass` 吞 → 下拉永远空(registry 明明有数据)。
**排查**: offscreen 实例化 `TrainingModule()` 直接调该方法, 不吞异常看真实 AttributeError;
`grep -n 'def _refresh_deploy_models'` 确认方法所在类(看前后 `class X` 行)。
**规则**: patch 工具加方法时, 用 `grep -n '^class \|def <method>'` 先确认目标类边界,
方法必须落在调用方所属类内; 新方法一律 offscreen 实例化验证 `hasattr(mod, method)` 再提交。

## 🐛 SimCanvas `_items` 属主是 SimulinkModule (点击画布刷屏 AttributeError)

simulink_module.py `SimCanvas.mouseReleaseEvent`(~2330 行)用 `self._items.get(nid)`——
但 `_items` 定义在 **SimulinkModule**(2568 行 `self._items = {}`), SimCanvas 没有 →
拖动节点后每次点击画布报 `AttributeError: 'SimCanvas' object has no attribute '_items'` 刷屏
(用户"点击没反应"假象)。修: `self.module._items.get(nid) if self.module else None`
(SimCanvas 构造已存 `self.module = module`)。
**规则**: 跨类访问成员一律 `self.module.xxx` / `self.parent.xxx`, 别假设子类也有父类的属性。

## 📱 VEH.2.31 部署模型下拉 + 推送到Orin 按钮 (端侧部署联动)

- **下拉数据源**: `models/saved/registry.json`, 每项 `path` → `os.path.join(path, "checkpoints", "last", "pretrained_model")` 存在才列入; ACT 优先在首 (`items.sort(key=lambda x: (0 if x[0]=="act" else 1,))`) 默认第一个=ACT
- **按钮联动铁律**: 「📥 推送到 Orin」初始 `setEnabled(False)`, 只有点选「📱 端侧部署」模式卡
  (`_ct_pick("deploy")`) 才 `setEnabled(True)` —— 用户报"点击没反应"多数是按钮禁用态(没选部署模式)
- **模型源优先级**: 部署下拉 currentData → 模型引擎 ckpt_edit 文本 → registry 最新 ACT
- **布局偏好 (老倪 2026-08-09)**: 部署行一行排列 —— 部署模型下拉(VEH.2.27) + 上传容器(VEH.2.29)
  在中间, 推送到Orin(VEH.2.28) 最右侧 (stretch 前放中间控件, 推送按钮放 stretch 后); 原独立
  rowc(上传容器)并入部署行, 别留单独一行
- **推送语义 = 带模型容器推到 Mac**: 模型 safetensors scp ECS `/www/wwwroot/datadrive.world/models/`
  (版本化 act_<ts> + act_latest 覆盖即部署) → chmod 644(scp 保留 600 → nginx 403) → HEAD 验证 URL
  → relay `/command` 下发 Mac 指令 → Mac 守护轮询拉模型 + 原生 arm64 构建容器。详见
  docker-gpu-training `references/mac-native-arm64-deploy.md`。

## VEH.2 编号是运行时自动分配的 (offscreen 拿不到)

`_veh2_apply` 按控件 y/x 坐标排序自动编号 `VEH.2.xx`(上→下、左→右), 依赖控件在 stack 页内的
parent 链(`_holo_page_of` 沿 parent 找 objectName `model_engine` → P03)。
**offscreen 直接实例化 TrainingModule 时无 stack parent → coords 空是正常现象**, 不是 bug。
用户报 "VEH.2.28 右侧/放中间" 等布局指令时, 按**构建顺序 + y/x 布局**推断编号,
别依赖 offscreen 的 `_holo_coords`(必然空)。编号会随控件增删漂移, 布局调整后重启让编号重算。
