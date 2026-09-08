# studio.py 编码规则与部署行布局 (2026-08-09 会话沉淀)

## 1. 仓库根路径 = 3 层 dirname (tools/gui/studio.py 特有, 反复踩坑)
- studio.py 在 `tools/gui/` 下, 仓库根 = `os.path.dirname` **3 次**:
  ```python
  root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
  ```
- 2 层 = `tools/` 目录 → 读 registry.json / outputs / reports 全错位 (多一层 tools/), 表现为"下拉空 / 拉回模型路径错 / FileNotFoundError"。
- 同仓库其他工具脚本 (tools/xxx.py) 是 2 层 (tools/xxx.py → tools → 根)。**按文件位置定层数**, 别照抄。
- 排查: `grep -n 'dirname(os.path.dirname(os.path.abspath(__file__))' studio.py` — 凡是该模式且文件在 tools/gui/ 下都该是 3 层。

## 2. 方法定义错类 → AttributeError (下拉空的隐形根因)
- `_refresh_deploy_models` 曾误放在 `InferencePanel` 类内, 但 `TrainingModule.__init__` 调用 `self._refresh_deploy_models()` → AttributeError 被 except 吞 → **下拉永远空**。
- 教训: 类方法归属检查 — `grep -n 'def _refresh_deploy_models'` 若出现在多个类范围, 确认调用方类的实例有该方法。offscreen 实例化直接调方法 (去掉 try/except) 看 AttributeError 是最快定位法。
- `_saved_registry_path` 属 InferencePanel; TrainingModule 里要用 registry 路径就**自己拼 3 层 dirname**, 别调别的类的方法。

## 3. VEH.2 部署行布局定稿 (2026-08-09 老倪多次纠正后)
模式卡(26=端侧部署)下方一行, 用户最终拍板顺序:
```
[🔼 上传容器到远程(29)] [📥 推送到 Orin(28)] [📦 部署模型:下拉(27)] ← stretch
```
- **上传容器(29)最左, 推送到Orin(28)中间, 下拉(27)最右**。中间曾把推送放最右/最左都被否。
- 编号 VEH.2.27/28/29 是 `_veh2_apply` 按布局 y/x 排序自动给的 (deploy_row 内 addWidget 顺序 = 左→右编号)。
- `_btn_upload_ct` 从独立 rowc 行并入 deploy_row (原 rowc 已删) — 删独立行时确认无其他引用。

## 4. 推送到Orin 按钮联动 (端侧部署高亮才可点)
- `btn_deploy_orin` 初始 `setEnabled(False)`; `_ct_pick(key)` 里 `self.btn_deploy_orin.setEnabled(key == "deploy")` — 只有点选「📱 端侧部署」模式卡后才可点, 否则点击无反应 (用户报"点击没反应"的常见原因)。
- 按钮点击 → `_deploy_model_to_orin` (后台线程): ①模型源 (下拉 currentData → ckpt_edit → registry) ②ECS 连通性探测 (relay /status + SSH_OK, 用户要求"要看到 ECS 链路通不通") ③**分块上传 8MB 带百分比** (`cat >>` 追加前先 `rm -f` 防残留; 每 5% 打印 百分比+速率+大小 — 用户强烈要求详细反馈, scp 静默 2 分钟 = "没反应") ④chmod 644 ⑤URL HEAD 验证 ⑥下发 Mac 指令 + Orin 状态。
- 分块上传循环两个文件名 (版本化 act_<ts> + act_latest), 每次 cat >> 前先 rm 同名 (否则残留文件重复追加)。

## 5. SimCanvas._items 属主 (点击画布节点崩溃)
- `SimCanvas.mouseReleaseEvent` 里 `self._items.get(nid)` → **SimCanvas 没有 _items** (属主是 `SimulinkModule`, 2568 行)。正确: `self.module._items.get(nid) if self.module else None`。
- 表现: 拖动节点后点击画布, 每次点击刷一条 `AttributeError: 'SimCanvas' object has no attribute '_items'` — 用户报"点击没反应"。

## 6. 通用控件 ID 页识别 (VEH.N)
- 任何页要 VEH.N ID: 页类 `__init__` 加 `self.setObjectName("<页名>")` → `_holo_page_of` 认页 → 全局 `_holo_apply_all` 自动编号 (无需写 _vehN_apply)。
- 页内独立序号: `_holo_page_seq` dict 按页计数 (VEH.3.01 起, 不是全局 73 起)。见 references/veh-id-system.md。

## 7. offscreen 验证注意
- 独立验证脚本用 `QT_QPA_PLATFORM=offscreen` + 完整 StudioMainWindow 实例化 (TrainingModule 裸实例 parent 链断, `_holo_page_of` 返回 P00 → coords 空, 会误判"没编号")。
- PyQt5 只在 `/usr/bin/python3`, 子进程脚本要 shebang 或显式用 /usr/bin/python3, 别依赖嵌套脚本环境。
- **execute_code 里跑验证子进程的坑**: ①嵌套 heredoc/三引号字符串里再嵌三引号会 SyntaxError — 用独立 tempfile 写子脚本文件再 `subprocess.run(["/usr/bin/python3", path])`; ②子脚本里 `import PyQt5` 报 ModuleNotFoundError = 父进程环境 (uv python) 无 PyQt5, 子进程必须用 `/usr/bin/python3`; ③子脚本要 `import tempfile` 别依赖父作用域; ④验证脚本若含 `$(date +%s)` 之类 shell 展开, 单引号内不展开 → 用 Python `time.time()` 或双引号。
- **shell=True 命令里嵌套单引号冲突**: `sshpass ssh '...cat >> file...'` 内嵌 `{models_dir}/{name}` 时, f-string 外层单引号会与内层冲突 → 用双引号包 ssh 命令或用变量拼接。

## 8. ⚠️ 方法定义吞掉后续 __init__ 代码 (ConfigModule 真根因, 静默丢失 UI)
- 症状: offscreen 实例化 ConfigModule 后 `findChildren(QGroupBox)` 只有 2 个 (架构模式/UI风格), 基础配置/VLM/ActionHead/世界模型/预处理/优化器/预览全缺; 源码里 `self.cfg_chunk_size = QSpinBox()` 报 `NameError: name 'self' is not defined` (该行在**类级 4 空格**而非 __init__ 方法体 8 空格)。
- 根因: 类里 `def _on_style_changed` 定义后, 后续"基础配置"代码块缩进 8 空格 → Python 视为**方法体延续**, __init__ 实际在 style_group (`bl.addWidget(style_group)`) 就结束了。方法尾没有 return, try/except 结束后代码继续"属于"该方法, 永远不执行且引用 __init__ 局部变量 (`bl`/`self` 在类级) → 布局静默丢失。
- 诊断技巧: 实例化成功 (无异常) 但子控件大面积缺失 → 查类内 `def ` 列表, 看 __init__ 是否被后续方法"截断"; `grep -n 'def _on_style_changed'` 附近缩进分布 (8 空格为主 = 方法体吞块)。
- 修复: ①方法体尾 (except 后) 加 `return` ②被吞块从 8 空格 dedent 到 __init__ 级 (4 空格) ③或把整块搬到 `def _on_style_changed` 定义之前。**不要只改一处缩进** — 类级(4)与 __init__ 方法体(8)只差 4 空格, 用 `python3 -c "import ast; ast.parse(...)"` 验证语法通过≠逻辑正确, 必须 offscreen 实例化数 GroupBox/控件数量断言。
- 教训: **给现有类插入大段 UI 代码时, 先画类结构 (def 列表 + 缩进分布), 再定位插入点**; 插到方法定义后面 8 空格 = 进方法体, 这是最隐蔽的静默丢失。

## 9. 配置中心 Lerobot 标准参数总表 (VEH.6, 2026-08-09)
- 对标 VEH.2.17 配置通道表格形式: 分类分组 (类别行跨列) → 参数行 → 每模型一列。配置中心 = 最全参数 (非 7 模型横向对比, 是 3 模型 ACT/SmolVLA/VLA-JEPA 全参数)。
- `cfg_spec` 数据: 6 大类 (🏗模型架构 / 📷视觉编码 / 🎮动作解码 / ⚙️训练超参 / 📊数据预处理 / 🚀推理部署), 每类 3-6 参数行, 每模型 dict → 32×4 表 (表头 标准参数|ACT|SmolVLA|VLA-JEPA)。
- 表格样式复用 zoo_table: 深色 #161b22、类别行 #1f2733 背景 + #00d4aa 字、模型列 #58a6ff 表头、参数行 #9da7b3、列宽 170/110、双滚动条 AlwaysOff。
- 导出 Excel: `_export_excel` 用 pandas DataFrame + `df.to_excel` → `reports/config_center_<ts>.xlsx`。**依赖: pandas + openpyxl 需 `pip install --break-system-packages` (PEP 668 阻止普通 install)**; 系统 python 无依赖时按钮报 ImportError 提示安装。
- 插入位置: 配置预览组后、按钮区前 (preview_group.setLayout 之后)。

## 10. 部署行/参数表等新增 UI 的验证基线
- 新增表格/组后必须 offscreen 断言: `findChildren(QTableWidget)` 按 objectName 找、`rowCount/columnCount`、表头文本; 新增 GroupBox 按 title 列表数。
- 数控件数量防"静默丢失": 修复前 GROUPBOXES 2 个 vs 修复后 9 个 (基础配置组全回来) — 这类断言能抓住 #8 的缩进吞块。
