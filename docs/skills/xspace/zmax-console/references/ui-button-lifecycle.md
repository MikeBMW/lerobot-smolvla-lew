# UI 控件生命周期 / 删按钮 / 训练行为 (2026-08-09 实测: v1.8.0)

三个用户反馈驱动的修复, 全部发生在 Model Engine (TrainingModule) / Model Zoo 队列:

## 1. 删 UI 控件必须清 4 处引用 (老倪: 删掉恢复默认按钮)

**坑**: 删"🔄 恢复默认"按钮 (defaults_btn + _reset_defaults 方法) 时, 只删创建处不够。
grep 必须零残留才算完。删按钮/开关/控件需同步清:

1. **创建处**: QPushButton 定义 + 样式 + clicked.connect + btn_layout.addWidget
2. **全息 ID 按钮注册循环** (studio.py ~4072): `for key, nm in [("start_btn",...), ...]` 里的元组
3. **_holo_coord_register 坐标注册** (~4108): `if hasattr(self, "defaults_btn"): self._holo_coord_register("P03", "01", "03", ...)`
4. **btn_map 执行映射** (~4212): `{"B-01": "start_btn", "B-02": "stop_btn", "B-03": "defaults_btn", ...}` — 删掉后**后续编号顺移**: 后面的 _btn_upload_ct 从 B-04 → B-03, 且其 `_holo_badge(..., "B-04")` 角标字符串也要同步改 B-03 (否则 ID 执行失灵)
5. **方法定义**: _reset_defaults 整个函数体删除

验证: `grep -n 'defaults_btn\|_reset_defaults\|恢复默认' tools/gui/studio.py` → 零输出 (注释里的说明文字也算残留, 验证脚本会抓到)。

## 2. 队列训练必须管理按钮生命周期 (老倪: stop 不好使)

**坑**: _start_training 有两条分支 — 旧单模型分支 (走参数收集+subprocess) 里
`stop_btn.setEnabled(True)` 只在训练成功后才执行; 而 **Model Zoo 分支 (训练队列) 启动队列后直接 return,
从未 enable stop_btn → stop 全程灰色, 用户点了没反应**。

**修法** (Model Zoo 队列四态按钮管理):
- 队列启动 (_start_training Model Zoo 分支): `start_btn.setEnabled(False)` + `stop_btn.setEnabled(True)`
- 队列完成 (_zoo_next 空队列分支): start 恢复 + stop 灰
- 全部跳过 (while 跳过循环清空队列): start 恢复 + stop 灰
- 手动停止 (_stop_training): 已有点位 (清 _zoo_queue + 停 _zoo_timer + pkill lerobot_train/train_awe_zflow + simulink.on_stop + 按钮恢复)

**教训**: 新增训练/执行路径时必须同步处理按钮状态, 不能假设只有旧路径会 enable。
排查 stop 不好使: 先 `grep -n 'stop_btn.setEnabled(True)'` 看所有 enable 点是否覆盖新路径。

## 3. 训练完不弹窗 + 自动交付 (老倪: 烦死啦 → 我要视频+PDF自动发飞书)

**坑**: _zoo_next 队列完成分支原代码自动调 `self._simulink.on_infer_video()` → 训练一结束就**弹视频窗口**,
用户强烈反感 ("赶紧停掉, 烦死啦")。

**演变 (两步)**:
1. 第一版修法: 删掉 on_infer_video, 训练完只生成报告 (on_pdf_report), 日志提示
   "🎬 视频未自动生成 (需要时点推理/视频节点手动生成)"。
2. **最终版 (老倪后续要求: "训练完看到最后的视频输出个pdf报告, 自动发到飞书群里")**: _zoo_next 完成分支
   改调 `self._simulink._auto_finalize()` — 后台线程跑 rollout 视频 + mp4 拼接 + PDF → 自动发飞书 dataworld 群。
   **不弹任何窗口** (日志进度, 无模态/非模态弹窗)。

**铁律**: 自动弹窗 (视频/对话框) 是负反馈源头 — WSLg 下弹窗假死 + 用户嫌烦。**自动交付 ≠ 弹窗**:
生成+发送可以全自动, 窗口必须手动开。

## 3b. 自动交付链路 _auto_finalize 要点 (simulink_module.py)

- 入口: `_zoo_next` 空队列分支 → `self._simulink._auto_finalize()` → 后台线程 `_auto_finalize_work`
- 顺序: ① rollout 各模型 (容器 zmax-std, 60帧, --task peg-insert-side-v3 --camera corner2 --rotate-ccw)
  → ② ffmpeg 帧→mp4 → ③ 拼接对比 → ④ generate_report.py PDF → ⑤ 发飞书 (对比视频 + 各模型视频 + PDF)
- **按训练开关过滤 rollout 模型** (2026-08-09): `pols` 只保留 `_zoo_sw` 里 isChecked 的模型,
  日志 "🎛 自动交付: 仅训过的模型 [...]" — 避免只开 ACT 却白跑 5 个模型 rollout
- **单模型视频**: 拼接段原硬编码 `len(mp4s) == 5` (3+2 xstack); 单模型时 shutil.copy 该 mp4 当对比视频
- **飞书凭据**: ~/.hermes/.env `FEISHU_APP_ID=cli_a87851ffe46b500d` + SECRET;
  chat_id = env FEISHU_REPORT_CHAT_ID 或默认 `oc_c0b4048546145c5c581ddd1a9e8f565d`
  (发送函数: _send_file_to_feishu_work / _send_report_to_feishu_work, 上传 im/v1/files → 发 im/v1/messages)
- rollout 需显示环境: 容器内 metaworld 渲染要 GLFW/X, 无 X 时 roll 报
  `GLFWError: X11: Failed to open display` (容器需 DISPLAY 或 offscreen 渲染)

## 4. 点开始按训练开关过滤并提示 (老倪: 没有训练开关提示)

**需求**: 用户选了本地运行 + 只开 ACT 开关, 点开始期望立即看到"训哪些/跳过哪些"。

**修法** (_start_training Model Zoo 分支):
```python
sw = getattr(self, "_zoo_sw", {})
on = [p for p in self._zoo_queue if sw.get(p) is not None and sw[p].isChecked()]
off = [p for p in self._zoo_queue if sw.get(p) is None or not sw[p].isChecked()]
self._log(f"🎛 Model Zoo 训练启动 — 开关: 开 {on if on else '无'} | 跳过 {off if off else '无'}")
self._zoo_queue = on or list(self.ZOO_POLICIES)  # 全关 → 全部训练 (保险)
```

**教训**: 用户点击动作要有即时反馈 — 按钮状态 + 日志区一行明确输出 (开/跳过), 不能静默。
训练开关 (每模型 checkbox) 是队列过滤的唯一依据, 启动时过滤比跑到一半跳过更直观。

## 5. 训练数据源默认本地 metaworld_peg (老倪: 你要用本地metaworld数据源训练)

**症状**: 点开始训练, 日志只出现 `FileNotFoundError: Provided directory does not contain any parquet file: /app/data/closed_loop/data`,
随后 `📈 ACT 曲线已存` (曲线文件落了个空壳), 无任何真实训练输出。用户质问"你到底干没干活"。

**根因**: `_ensure_training_data` (simulink_module.py) 的数据源决策链:
1. 节点逻辑强制 (data_source 参数) → 画布 switch 节点 (`_switch_state`) → 激活数据源节点 (`_active_source`)
2. **以上全为空时落到"拉取 relay 真实数据"分支**: `GET https://datadrive.world/api/relay/latest` 有响应 → 把帧存成
   `data/closed_loop/orin_*.npz + pkg_*.json` **原始包** → 返回 closed_loop 作为数据集根
3. 但训练要读 parquet 数据集 (`root/data/chunk-000/file-*.parquet`), 而 closed_loop 里只有 npz 原始包 +
   残缺 meta (HF 缓存结构 meta/episodes/, 缺 data/ 目录) → **FileNotFoundError 必炸**

**修法** (2026-08-09, commit 20079295): 决策链的 else 分支 (无 switch/无激活源) 直接返回本地占位集:
```python
else:
    # 无 switch 时默认本地 metaworld (Orin 原始包未转 parquet 数据集, 拉 relay 会 FileNotFoundError)
    if os.path.isdir(placeholder):
        self.log_signal.emit("📦 数据源默认 [metaworld] → 本地占位集训练 (Orin 未转数据集前不用 relay)")
        return placeholder, "metaworld 占位集 (默认)", False
```
显式 orin (节点逻辑强制 / 画布 switch=orin) 仍走 relay, 回退逻辑保留。

**诊断口诀**: 训练报 `does not contain any parquet file: <path>` → 先看数据源决策走了哪条路:
`grep -o '"switch"[^,]*' tools/gui/flow.json` (画布 switch) + 确认数据目录结构
`ls data/<ds>/` 必须有 `data/` (parquet) + `meta/` (info.json)。npz 原始包 ≠ 可训数据集。
验证数据集完整性: `find data/<ds> -name 'file-*.parquet' | head` (需 data/chunk-000/ 下有文件)。

## 6. simulink 页 ID 角标改悬停显示 (老倪: 左下角ID不常显, 悬停才见)

**需求**: simulink 功能页所有按钮/控件左下角的青色 ID 小字太吵 — 不要常显, 鼠标悬停到控件时才看到 ID。

**改法** (studio.py + simulink_module.py, commit 15a45d84):
1. `_holo_badge_overlay(self, widget, h_id, hover_only=False)` 加 hover_only 参数:
   `hover_only=True` → 不叠加 QLabel 角标, 改为把 `[ID {h_id}]` 前缀塞进 `widget.setToolTip()` (悬停即见)
2. `_holo_apply_all` 遍历控件时按页判断: `hover_only = self._holo_page_of(w) == "P11"`
   (P11 = simulink 画布页; 其它页 P01-P12 保持左下角常显)
3. 画布节点自绘 ID (simulink_module.py CICDStageItem ~1047 / SimNodeItem ~1880):
   paint 里 `if getattr(self, "_hover", False):` 才画左下角青色小字 —
   两节点类都有 hoverEnterEvent/hoverLeaveEvent 置 `self._hover`, 天然支持

**坑**: _holo_page_of(w) 靠 objectName 前缀匹配 ("simulink" → P11), 新增页面必须注册到
`_holo_page_of` 的页名映射, 否则 ID 落到 P00 且 hover_only 判断失效。
**2026-08-09 演进**: Pxx 体系已全废 → VEH 点号 (`VEH.卡号.序号`, simulink=VEH.5); 样式/位置规则
见 refs/feature-card-recovery.md「VEH-ID 体系」节。VEH.2 (模型引擎页) 控件按布局序编号
(`_veh2_apply`: 全局 y 上→下 + x 左→右), 需 TrainingModule 设 `setObjectName("model_engine")` 供页识别。

## 7. 排查套路汇总 (2026-08-09 三个用户报障)

- "stop 不好使" → `grep -n 'stop_btn.setEnabled(True)'` 看所有 enable 点是否覆盖新增路径
- "没有训练开关提示" → 用户点击动作必须日志即时反馈 (开/跳过清单), 不能静默
- "训练报 no parquet" → 数据源决策链 + `ls data/<ds>/` 结构检查 (npz 原始包 ≠ 可训数据集)
- "左下角 ID 太吵" → hover_only 机制 + _holo_page_of 页注册
- **"ID 一个都看不到" (2026-08-09 事故)**: QSS 8 位 hex 是 **#AARRGGBB alpha 在前** — `#00d4aacc` = alpha 0x00 全透明 → 完全不可见。正确 `#cc00d4aa`。视觉改动必须重启 GUI 肉眼确认, 静态 AST 验证抓不到。另注: 老倪每次报"看不到"时先确认**窗口是否真的重启过** (旧进程还在跑旧代码, 用户看到旧行为) — 重启纪律见 SKILL.md「重启: pkill -f 后重拉, 验证进程数==2」
- **"ID 一个都没有" 第二根因 (2026-08-09 末轮)**: 即使样式/编号全对, 父控件已显示时新建的 QLabel 子控件默认 `isVisible()==False` → 角标创建了但从不渲染。**必须 `lbl.show()`** (overlay + 同步定时器两处)。像素级验证: offscreen render 数 #00ffd0 像素 >0 才证明真画出来 (修复前 0 像素, show 后 850 像素); 注意按钮自身也有 #00d4aa 边框色会误报, 以 `lbl.isVisible()` 断言为主。完整字号迭代史 (5px→7px→14px→10px 无背景→**10px 灰字定稿** + **v5 大窗常显/小窗悬停分流**) 见 refs/veh-id-system.md

## 8. ID 显示全局定稿 (2026-08-09 末段, 老倪: 所有ID都改悬停 / VEH.0.01也不要显示)

**用户多轮迭代的最终规则 — 所有控件 ID 一律悬停 tooltip, 无任何静态常显**:
- 演进: P01/P11 悬停 → VEH.2 页全悬停 (`_veh2_apply` 去掉 `_is_big` 常显逻辑, 41 控件全 hover) → **主循环 `_holo_apply_all` 全页 hover_only=True** (不再区分页面)
- **VEH.0.x 兜底 ID**: 页面 objectName 未注册 (如 HomeWidget 缺 `setObjectName("home")`) 时 `_holo_page_of` 返回 P00 → ID 编号 VEH.0.xx。**HomeWidget 补 `setObjectName("home")` 后首页按钮才进 P01 hover_only 分支** — 报"首页按钮还是常显"时先查页面 objectName 是否注册 (首页按钮原判定 P00 不走悬停分支)
- 常显白名单: **主页 12 功能卡徽标 VEH.1~VEH.12 保留** (老倪明确要的对话 ID) — 其余页面控件全部悬停
- 验证: offscreen 实例化 TrainingModule → 断言所有 badge `hover_only=True` / 0 常显角标对象 + tooltip 含 `VEH.x.xx — 控件名`

## 9. VEH.2 配置表高度/滚动条 (老倪: VEH.2.17 默认加载全部, VEH.2.01 取消拖动条)

- **根因1**: `showEvent` 用"屏幕高/3"覆盖 param_scroll 最小高度 (offscreen/小窗 = 200px, 表格 18 行全高 ~534 被截) → 默认折叠要拖
  - 修: showEvent 固定 `param_scroll.setMinimumHeight(600)` (表格全高 + 余量), 不再屏幕 1/3; 同时 log_text 最小 600→200 腾空间 (日志可折叠)
- **根因2**: 表格区域 QScrollArea 垂直滚动条 AsNeeded → 内容略超视口出滚动条 → 修: `setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)` (表格全高已展开无需滚; 页面整页滚动保留, 下方按钮/日志仍需可达)
- 教训: 改控件高度/滚动时先算内容真实全高 (表头30 + 类别行26×4 + 参数行28×13 ≈ 534), 别用屏幕比例拍脑袋

