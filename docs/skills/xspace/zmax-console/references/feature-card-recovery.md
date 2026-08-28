# 功能卡恢复 / 一致性检查 (2026-08-09 实测: v1.8.0)

## 🪪 VEH-ID 体系 (2026-08-09 老倪: 对话指代 ID; 全控制台唯一 ID 命名)

**主页功能卡** (12卡左下角常显, 点号格式 `VEH.N`):
VEH.1 数据集管理 | VEH.2 模型引擎 | VEH.3 硬件工具箱 | VEH.4 系统架构 | VEH.5 Simulink模式 | VEH.6 配置中心 | VEH.7 全局数据空间 | VEH.8 实时监控 | VEH.9 评估分析 | VEH.10 插拔场景 | VEH.11 版本同步 | VEH.12 产品大屏
老倪说 "去 VEH.5" = 切到 Simulink 页。代码: ModuleCard(veh_id=...) 底部行左侧, studio.py `_modules_grid` 传 `f"VEH.{idx + 1}"`。

**页内控件** (点号 `VEH.卡号.序号`, 如 VEH.2.01): `_holo_seq_id` 返回 `VEH.{veh_n}.{seq:02d}`, 页→卡号映射 `_VEH_PAGE = {"P01":1,"P02":1,"P03":2,"P04":9,"P05":3,"P06":6,"P07":8,"P08":10,"P09":11,"P10":2,"P11":5,"P12":7}`。VEH.2 (模型引擎页) 用 `_veh2_apply` 按布局位置排序编号 (全局 y 优先上→下, 再 x 左→右; `_holo_abs_y/_holo_abs_x` 沿 parentWidget 累加)。

**样式铁律 (老倪 3 次纠正 + 1 次不可见事故; 最终定稿 v7 见 references/veh-id-system.md)**:
- 字体小: 主页卡 7px (`QFont("Consolas",7,Bold)`) + 灰色 `C_GRAY #8b949e`; 页内控件 10px 无背景纯灰字。**不要明显但要可见**
- **🚨 QSS 8 位 hex = #AARRGGBB, alpha 在最前 (2026-08-09 事故)**: 写 `#00d4aacc` 会被解析成 **alpha=0x00 全透明** (颜色变成 d4aaCC) → VEH ID 完全看不见 ("一个都看不到")。正确写法 `#cc00d4aa` (alpha CC 在前, 颜色 00d4aa)。**5px + #00d4aa88 也是全透明陷阱** (alpha=00 + 颜色 d4aa88)。改完必须肉眼确认窗口, 静态验证抓不到视觉问题
- **覆盖范围 = 所有 QWidget (老倪: "所有 layout 的所有对象都要有 ID")**: `_veh2_apply` 遍历 `root.findChildren(QWidget)` 全部, 含 QLabel/QFrame; 仅过滤 ①空文字 QLabel ②文字以 `VEH.` 开头的角标自身 (防递归)。**不要用类型白名单** (会漏掉 QLabel 标题如 "🔗 GPU 服务器:")。**⚠️ 必须排除容器类 QScrollArea/QScrollBar/裸 QWidget 壳 (`type(w) is QWidget`)** — 76→41 控件, 容器角标盖住子控件, 用户报 "一个ID都没有"
- **🚨🚨 最根本的坑: 父控件已显示时新建 QLabel 子控件默认 `isVisible()==False`** → 角标创建了但永远不显示。**`_holo_badge_overlay` 里 `lbl.raise_()` 之后必须 `lbl.show()`**; `_holo_sync_badges` 同步时补 `if not lbl.isVisible(): lbl.show()`。**验证方法 (offscreen 渲染像素级)**: `QImage + m.render(QPainter)` 后数 badge 文字色像素, >100 即成功; 修复前 0 个。静态断言抓不到这个 — 必须渲染验证
- **显示分流 (v5→v6→v7 定稿)**: v5 大窗口 (分组框/表格/面积≥20000) 常显 + 小控件 hover_only; **v6 收紧: QPushButton 一律 hover_only (按钮常显灰字很脏), 仅 QGroupBox/QTableWidget/面积≥60000 常显**; **v7: 首页 P01 按钮也 hover_only** (`hover_only = self._holo_page_of(w) in ("P01","P11")`), hero 区 8 按钮不再被污染。完整演化见 references/veh-id-system.md

**取消 Pxx 系统 (2026-08-09)**: 旧 ID `P03.01.05` 全废, 统一 VEH 点号。simulink_module.py 节点 nid `P11.xx` → `VEH.5.xx`。改完 grep `P0[0-9]\\.` 必须零命中 (注释里的示例文字也算残留, 一并改)。

**VEH.2 页全覆盖编号 (2026-08-09 老倪: "所有ID都得改, 原来的 M-01 B-03 都改成 VEH.2 加顺序号")**:
- **移除所有手动 `_holo_badge(w, \"B-xx\"/\"M-xx\")` 包装** (start_btn/stop_btn/_btn_upload_ct/三模式卡共 4 处): 改回直接 `layout.addWidget(控件)`, 视觉 ID 全由 `_veh2_apply` overlay 统一出
- 模式卡按钮文字里的 `[{mid}]` 后缀一并去掉 (`f"{title}\\n{sub}"`)
- `_veh2_apply` targets 扩到全控件类型: `(QPushButton, QCheckBox, QRadioButton, QComboBox, QLineEdit, QAbstractSpinBox, QTableWidget, QGroupBox)` — **数值控件 (spinbox) 也必须编号**; QAbstractSpinBox 要在模块级 import
- `_holo_name/_holo_type/_holo_state` 补 QAbstractSpinBox 分支 (显示 `数值 x` / 状态=value)
- **btn_map 执行映射保留** (B-01/M-01 → 真实控件) 供 `_holo_act` 兼容, 只删视觉层
- 验证: `grep -c 'self._holo_badge(' tools/gui/studio.py` == 0 (手动包装零残留) + `[M-0x]` 零命中

## 坑: 页面在, 卡片消失 (用户报障 "三层架构的功能卡哪里去了")

**根因**: 2026-08-08 提交 dac21aea "删除 Architecture 功能页" 同时删了 4 处:
1. 主页 `_modules_grid` 卡片列表里的 `("architecture","🏗️","系统架构",...)` 元组
2. `self.modules` 字典 `"architecture": 1`
3. `self.stack.addWidget(ArchitectureModule())`
4. `_on_nav` 状态栏 names 列表

后来"恢复架构页"只补了 **2 和 3**(modules 字典 + addWidget), 注释还写着"恢复架构页 (三层架构功能卡)", **唯独漏了第 1 处主页卡片列表** → 主页看不到三层架构卡, 但页面/导航都正常。用户打开控制台发现卡没了。

**排查要点**:
- 页面存在 ≠ 主页有卡。三个地方独立: 卡列表(_modules_grid) / 页面注册(modules 字典+stack) / 导航(names)
- 删功能页时必须 4 处同步删, 恢复时必须 4 处同步恢复
- 附带坑: names 列表删改时容易错位 (v1.8.0 发现 14 项 vs 字典 13 项, names[1]="架构" 实际是数据集)

## 解法: tools/ci/integrity_check.py (v1.8.0 保护更新)

```bash
cd ~/lerobot-smolvla-lew && python3 tools/ci/integrity_check.py
# ✅ Z-MAX v1.8.0 完整性检查通过 → 才允许 commit
```

检查 6 项:
1. 版本号 5 处一致 (studio.py 窗口标题+侧栏 QLabel / update_checker.py CURRENT_VERSION / docs_sync.py version+zmax_version)
2. 主页 12 功能卡 == EXPECTED_CARDS (含 architecture, 12 张填满 4×3 网格)
3. self.modules 字典 13 键顺序 == EXPECTED_MODULES (home=0 ... architecture=12)
4. stack addWidget 顺序 == 字典索引对齐 (处理 `self.model_engine` 等 Attribute 实参 → 别名映射)
5. 页面类存在 (class 定义或 import 引用)
6. _on_nav names 13 项与字典顺序一致 (len 必须 == 13, 首项"首页", 含"架构总览")

**改版本号** (中版本迭代 v1.7.0→v1.8.0): 5 处
- tools/gui/studio.py: `setWindowTitle("XSpace Studio — Z-MAX vX.Y.Z [W-01]")`
- tools/gui/studio.py: 侧栏 `QLabel("Z-MAX vX.Y.Z")` (~229 行)
- tools/gui/update_checker.py: `CURRENT_VERSION = "vX.Y.Z"`
- tools/gui/docs_sync.py: ver dict 里 `"version"` + `"zmax_version"` (两处, 相邻)

**负向自测** (改完检查器后必做): 临时改 EXPECTED_CARDS / EXPECTED_VERSION 为错误值 → 检查器必须报错退出非 0; 改回后必须通过。证明检查器不是摆设。

## 版本迭代完整流程 (v1.8.0 实操)

1. 改 5 处版本号 (上面)
2. `python3 tools/ci/integrity_check.py` 通过
3. 生成中版本报告: `tools/gen_report_v180.py` → `docs/CICD_REPORT_v180.html` (9 项功能表 + 模型表 + 链路表 + SHA)
4. 更新技能 zmax-console 版本迭代节 (坑+流程)
5. commit: `release: Z-MAX v1.8.0 — <特性摘要>`
6. `git tag -a v1.8.0 -m "..."` + `git push origin main --tags`
7. GitHub Release (REST API, token 从 ~/.git-credentials 提取) + 上传报告 HTML 附件
8. 汇报: Release URL + tag SHA + 附件 + 功能表 + 保护检查结果

## 附带坑 1: patch 工具双转义 \n (2026-08-09 实测)

studio.py 的 QLabel 字符串满是 `\n` 换行转义。用 patch 工具改含 `\n` 的字符串字面量时,
new_string 里写 `\n` 会被双转义成字面 `\\n` → 显示成 "\n" 文本而非换行。
**必须**: 改完立即 read_file 核验目标行; 若见 `\\n` 用 follow-up patch 把 `\\n` 改回 `\n`。
同一文件多处同串时 patch 报 "4 matches" → 带上下文 (相邻行) 定位唯一。

## 附带坑 2: ~/.zmax_ssh.json 凭据可能过期 (2026-08-09 实测)

GPU 服务器 (223.109.239.36:24340) 连接失败排查顺序:
1. 先探端口: `timeout 5 bash -c 'echo > /dev/tcp/<host>/<port>'` → 通/不通
2. 读 ~/.zmax_ssh.json 看当前凭据 — **json 里可能是旧密码** (曾存 da9eo7yo, 实际 ahWat3se)
3. 用已知密码逐个实测 (sshpass -o Port= 方式, -p 参数被吞须用 -o Port=)
4. 实测成功密码后**回写 ~/.zmax_ssh.json**, 防下次再踩
注: 记忆里的密码可能比 json 新 — 两者都试, 以实测为准。

## 附带坑 2b: ~/.zmax_ssh.json 结构错位 — 连接按钮连不上 (2026-08-09 实测, VEH.2.08 报障)

**双 GPU 结构 (2026-08-09 起)**: json 从扁平改为**嵌套**:
```json
{"gpu_v100": {"host":"223.109.239.36","port":"24340","user":"root","pwd":"ahWat3se"},
 "gpu_4090": {"host":"223.109.239.30","port":"15032","user":"root","pwd":"johzoo4o"}}
```
(4090 = 新 RTX 4090 24G 训练机, ubuntu22, 已有 zmax-train 镜像 + nvidia-container-toolkit)

**🚨 坑: 代码读写结构必须与文件一致, 否则密码静默丢失**。旧代码 `_cred.get("pwd")` 只读扁平;
外部(我)把文件改成嵌套后, 加载端 `_cred.get("pwd")` 返回 None → 密码框空/残留旧值 → 点连接 `⚠ 请填主机/用户/密码` 或带错密码连不上。
**且运行中的控制台 `_connect_gpu` 会用当前输入框值**覆盖 dump 整个 json (旧代码 `_json.dump(扁平)`) → 把我写的嵌套结构冲掉。

**修复 (双向兼容, 已入 studio.py)**:
- 加载端: `if "host" in _cred: _c=_cred (扁平) else: _c=_cred.get("gpu_4090") or _cred.get("gpu_v100") or {}` — 优先 4090 (最近连接)
- 保存端: 读旧 json → 扁平自动归入 `gpu_v100` → `_old.setdefault("gpu_4090", {}).update(new)` → 合并写回 (不再整文件覆盖)
- **教训: 改凭据文件格式时, 必须同步改 GUI 的读端+写端; 只改文件会被运行中控制台覆盖或读不到**

**排查顺序 (连接按钮连不上)**: ① 探端口 ② `cat ~/.zmax_ssh.json` 看结构是扁平还是嵌套、pwd 是不是被覆盖成了怪值 (如 `ssh root@... -p ...` 整条命令塞进 pwd 字段 = 某次手动填错被 dump) ③ 修文件 + 改代码兼容 ④ 重启控制台 (运行中实例会再次覆盖) ⑤ offscreen 实例化断言 `m.ssh_pass.text() == 正确密码` + 真实 sshpass 冒烟。

## 删除篇: 删控件/按钮的零残留清单 (2026-08-09 实测: 删「恢复默认」按钮)

老倪: "删掉 X 按钮和功能"。**一个控件在 studio.py 里至少 5 处引用**, 漏一处就崩或残留。以删 defaults_btn (恢复默认) 为例:

1. **控件创建**: `self.defaults_btn = QPushButton(...)` + setToolTip + setStyleSheet + clicked.connect + `btn_layout.addWidget(...)` — 整段删
2. **全息ID按钮列表** (~4072): `for key, nm in [("start_btn",...), ("stop_btn",...), ("defaults_btn",...)]` — 从元组列表删
3. **坐标注册** (~4108): `if hasattr(self, "defaults_btn"): self._holo_coord_register("P03","01","03", ...)` — 删整个 if 块
4. **btn_map 按钮ID映射** (~4212): `{"B-01": "start_btn", "B-02": "stop_btn", "B-03": "defaults_btn", "B-04": "_btn_upload_ct"}` — 删项
5. **方法定义**: `def _reset_defaults(self): ...` 整个方法体删

**⚠️ B-xx 编号顺移坑**: B-xx 由按钮列表动态编号 (B-01=第1个按钮...), 删中间按钮后**后续按钮编号全部前移**。本例删 B-03 后 `_btn_upload_ct` 从 B-04 → B-03, 但它的 `_holo_badge(self._btn_upload_ct, "B-04")` 角标是**写死的** → 必须同步改成 B-03, 否则 ID 角标与 btn_map 不一致, 全息ID执行功能错乱。

**验证纪律**: 删完 grep 残留 (`defaults_btn|_reset_defaults|恢复默认` 必须 0 命中) → 语法检查 → `python3 tools/ci/integrity_check.py` 必须仍绿 → 重启 GUI 看实际效果。负向自测可选: 临时改坏检查器确认它能报错。

## 训练链路坑 (2026-08-09 实测: 本地训练)

### 坑 1: 数据源默认拉 relay → closed_loop 无 parquet → FileNotFoundError

**症状**: 点开始训练, 终端只有 `[HH:MM:SS] FileNotFoundError: Provided directory does not contain any parquet file: /app/data/closed_loop/data`, ACT 曲线存了个空文件。老倪: "你到底干没干活"。

**根因**: `simulink_module.py _ensure_training_data` — 画布无 switch/source 节点时 `src=None` → 落到"尝试拉真实数据" → relay (datadrive.world/api/relay/latest) 有响应 → 把帧存成 `data/closed_loop/orin_*.npz + pkg_*.json` (原始包) → 返回 real_dir。但 `data/closed_loop/` 里**没有 parquet 数据集** (meta/episodes 是残缺 HF 缓存, 缺 data/chunk-000/file-*.parquet) → 训练脚本读不到 parquet 直接炸。

**修复 (老倪指令: "你要用本地metaworld数据源训练")**: `_ensure_training_data` else 分支 (无 switch) 加默认返回:
```python
else:
    if os.path.isdir(placeholder):
        self.log_signal.emit("📦 数据源默认 [metaworld] → 本地占位集训练 (Orin 未转数据集前不用 relay)")
        return placeholder, "metaworld 占位集 (默认)", False
```
显式 orin (节点逻辑强制/画布 switch) 仍拉 relay — 不动。

**排查顺序**: ①`ls data/closed_loop/` 看是 npz 还是 parquet 数据集 ②`grep -n '"switch"' tools/gui/flow.json` 看画布有没有 switch 节点 ③验证 metaworld_peg 完整性 (`data/metaworld_peg/data/chunk-000/file-*.parquet` 必须存在, `meta/info.json` episodes>0)。

### 坑 2: Model Zoo 训练中 stop 按钮灰的 (不好使)

**根因**: `_start_training` 的 Model Zoo 分支 (有 _simulink 时) 启动队列后直接 `return`, **从未走到** `stop_btn.setEnabled(True)` (那只在旧的单模型训练分支)。训练跑着但 stop 一直是灰的, start 还一直可点。

**修复**: 队列启动时 `start_btn.setEnabled(False)` + `stop_btn.setEnabled(True)`; 三处恢复点都要还原 (`_zoo_next` 完成分支 / 跳过清空分支 / `_stop_training` 本身)。**教训: 新增启动分支时必须同步管理按钮状态机, 别只在一个分支里 enable。**

### 坑 3: 训练完自动交付 (视频+PDF→飞书) 的触发点

**老倪需求**: "返回simulink功能卡后, 要看到最后的视频输出个pdf报告, 自动发到飞书群里"。但 "别总弹出视频" (弹窗烦)。

**正确链路**: `_zoo_next` 完成分支 → `self._simulink._auto_finalize()` (不是 on_pdf_report 也不是 on_infer_video):
- `_auto_finalize_work` (后台线程): ① rollout 各模型 60 帧 (容器 zmax-std, `--task peg-insert-side-v3 --camera corner2 --rotate-ccw`) ② 帧→mp4 (ffmpeg) ③ 拼接对比 (5模型=3+2 xstack / 1模型=直接 copy) ④ generate_report.py PDF ⑤ 发飞书 (对比视频 + 各模型 mp4 + PDF)
- **按训练开关过滤 rollout 模型**: `_auto_finalize_work` 开头读 `_zoo_sw`, 只 rollout 开关打开的模型, 不白跑全量
- 飞书凭据: `~/.hermes/.env` 的 FEISHU_APP_ID/SECRET + chat_id (默认 oc_c0b4048546145c5c581ddd1a9e8f565d), 代码 `_send_report_to_feishu_work` / `_send_file_to_feishu_work`
- 训练完**不自动弹视频窗口** (老倪: 烦) — 自动交付只发文件到飞书, 窗口留手动

**手动补跑交付** (训练已完成但当时代码没自动交付): 直接跑 `rollout_video.py --policy act --steps 60 --task peg-insert-side-v3 --camera corner2 --rotate-ccw --out reports/rollout_final_act` (容器) → ffmpeg 合成 mp4 → 发飞书。
