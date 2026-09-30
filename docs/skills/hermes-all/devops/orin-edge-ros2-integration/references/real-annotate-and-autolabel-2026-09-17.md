# 真机 YOLO 标定工位 + 位姿真值 + 机器人动作自动标注 (2026-09-17 会话沉淀)

归属: `orin-edge-ros2-integration` (Orin 真机链路)。本文件是该会话全部实测坑与验证数字。
配套代码: `tools/real_truth.py` · `tools/real_autolabel.py` · `tools/yolo_annot_dataset.py` ·
`tools/gui/yolo_input_viewer.py` · `tools/gui/yolo_label_widget.py` ·
设计文档 `docs/design/real_autolabel_by_robot_motion.md`。

---

## 1. 类名口径: 真机必须 `peg` (不是 `optical_module`)

- **唯一口径源** = `src/lerobot/policies/yolo_3d/frame_source.py:40`
  `CLASS_MAP = {"hand": "hand", "peg": "光模块", "hole": "hole"}` —— 注释明写「peg→光模块; 类 id 顺序不许改」。
  下游 `tools/real_yolo_perceive.py` 按**业务名**取值: `det3d.get("hand") / det3d["光模块"] / det3d["hole"]`
  → 写进 obs39 的 `[0:3]`(hand) / `[4:7]`(光模块) / `[36:39]`(hole)。
- 用 `optical_module` 当类名 → CLASS_MAP 无此条目 ⇒ 权重训练得再好也**接不进感知链**(光模块那一路恒空)。
- **类别 ≠ 型号**: 100G / 400G 若外观一致就归一类(分两类只会让每类样本更少、互相打架);
  型号区分交下游业务/元数据, 不塞进检测类别。
- **⚠️ 未知类名会被 `save_sample` 自动追加进 `classes.txt`**:
  `cid = names.index(c) if isinstance(c, str) and c in names else add_class(root, c)`
  ⇒ 工程师在下拉里手打(`100G平`/`400G`)或旧默认名, 在**保存那一刻**就多出一类, id 顺序被改。
  **救回三步**: ①`classes.txt` 清回单类 `peg` ②把所有 `labels/*.txt` 行首 class id 重映射成 0
  ③`meta.json` 的 `classes` 同步。**`annotations.jsonl` 是追加式审计流水, 保持原样不改**(历史就是历史)。
- 旁证: 现役 `peg_v1`(`{0:hand,1:peg,2:hole}`)对真机帧 conf≥0.25 **0 检出** ⇒ 必须真机数据重训,
  所以类名与现役口径严格对齐价值最大 —— 训出的 `best.pt` 可直接顶掉 `peg_v1`, 代码零改。

## 2. 标定工位两个 Qt 真 bug (offscreen 取证, 手工测不出)

### 2.1 「左键拖不出框」= 拖拽锚点被每帧鼠标移动覆盖
- `yolo_label_widget._edit_drag()` 新建框分支写成 `self._drag = ("new", start, pt, -1)`,
  而 `start` 是 index2 = **上一次鼠标移动点** ⇒ 每动一次就把**按下那一点冲掉**;
  松开(`mouseReleaseEvent`)时算出的矩形只剩最后一小段位移(通常 <4px) → 被 `(x2-x1)<4` 判成"误点"丢弃
  (偶尔拖出个 20×15px 碎片)。表现完全等价于"拖不出来"。
- **修**: 锚点恒为按下点 —— `self._drag = ("new", box, pt, -1)` (index1=锚点, index2=跟随鼠标)。
- **取证(唯一可行方式)**: offscreen 合成鼠标事件 `press(100,100) → move(140,130)/(180,160)/(220,190)/(260,220) → release(260,220)`,
  断言框 == 显示坐标换算回原帧像素。实测: 修前 `(110.0, 95.0, 130.0, 110.0)`(只剩最后一段),
  修后 `(50.0, 50.0, 130.0, 110.0)` ✅; 旋转窗 180° 同测 → `(189,129,269,189)`(自动换算回原始坐标, 标签不镜像)。
- 教训(通用): **拖拽类交互的"锚点"必须是不可变值, 任何每帧 reassign 都可能吃掉它**; 这个 bug 截图看不出、
  手工拖也可能"偶尔成功", 只有合成事件序列能稳定复现。

### 2.2 「改选中类别/删选中/撤销 按钮不好使」= 两窗只同步框集合、不同步选中项
- `_sync_boxes(src, dst)` 在**框集合相同**时直接 `return`; 而在旋转窗里点选一个框只改 `_sel`、不改框集合
  ⇒ 左窗 `_sel` 仍 `-1`, 而这三个按钮当时全绑 `w_orig.selected()` → 取不到选中 → 用户眼里"按钮坏了"
  (只在日志里留一行"没有选中框")。
- **修**: ①两侧 `selectionChanged` 互相同步选中索引(`_mirror_sel`, 带防递归标志)
  ②这几个键改走 `_active_pane()`(谁有选中就作用于谁)。
- 取证: offscreen 造两个窗 → 在 `w_rot` 置 `_sel=0` + `_emit()` → 断言 `w_orig.selected()==0`
  (修前恒 -1) → `_relabel_selected()` → 断言两窗类别都变。

### 2.3 offscreen 验证 GUI 的三条硬约束
- **模态弹窗必须桩掉**: `QMessageBox.information/warning/critical/question` 在无头环境**永久阻塞**
  (症状: 脚本超时 / exit 124 / `timeout: the monitored command dumped core`)。
  桩法: 三个静态方法 setattr 成记录函数; 要验"确认后才执行"就把 `question` 分别返回 `No`/`Yes` 各跑一遍。
  **产品代码保留弹窗**(人要看得见), 只在测试里桩。
- **可见性断言前必须 `show()` + `app.processEvents()`** —— 未 show 时子控件 `isVisible()` 恒 False。
- **替身对象接口要给全**: 用 `lambda *a, **k: None` 顶替采集线程 → 调用方 `.start()` 立刻 AttributeError,
  而异常发生在 QTimer 槽里 = qFatal **整个进程中止**(不是脚本报错, 是 core dump)。
- **别用管道掩盖退出码**: `python verify.py | tail -5` 报的是 `tail` 的 exit code(恒 0)。

## 3. 数据层级与删除 (用户的"删了图留下标注"就是层级混淆)

| 路径 | 是什么 | 能删吗 |
|---|---|---|
| `sessions/<会话>/{frames,labels}` | **原始标注**(图+标签成对) | 删了真没了 |
| `dataset/` | 生成物(图/标签/data.yaml/stats/truth) | 随便删, `--build` 重建 |
| `classes.txt` / `meta.json` / `annotations.jsonl` | 类别表 / 索引 / 审计流水 | 别删 |

- 窗口新增「🗑 丢弃当前帧」(`delete_sample`, 图+标注**成对删**)/「🗑 清空本会话」(`clear_session`, 弹确认)。
- CLI: `--clean`(只清**孤儿标注**: 有 .txt 没图; **有图没标注默认保留** —— 那可能是刻意留的背景负样本)
  / `--reset --yes`(清空 sessions+dataset, 保留 classes.txt 与审计流水)。
- 实测(临时根): 3 图 3 标(1 对孤儿) → `--clean` 删孤儿标注、保留孤儿图、正常配对不动 ✅;
  `--reset --yes` 清 19 文件、classes.txt 保留 ✅。
- **删图不删标注的修法**: `--clean`(清孤儿标注) 再 `--build`(从 sessions 重建 dataset)。
- 样本 ≥8 后 `--build` 的 val 变成**真留出集**(文件名哈希划分), <8 时 val 复用 train 并在 `stats.json`
  显式标 `val_overlap_train=true` —— 那时 mAP 不可信, 只能证明管线通。

## 4. 真机位姿真值 (单一来源 `tools/real_truth.py`)

- 读采集容器落盘的 `$SS_OUT/state_YYYYMMDD.jsonl` **最后一行**(尾部 64KB 反向扫, 文件几百 MB 别整读)
  / `status.json` 兜底 → `tcp / tcp_quat / jpos / jvel / ft` + `age_s` + `fresh`(≤5s)。GUI 不引 rclpy。
- 每帧存档字段: `tcp_frame=base_link`; `tcp_quat` 顺序 = ROS `(x,y,z,w)`(采集端 `[o.x,o.y,o.z,o.w]`)。
- **metaworld 39D 段位 (权威 = `yolo_3d/yolo_state_aligner.py:317-328`)**:
  `[0:3]=hand` · `[4:7]=光模块(peg)` · `[7:11]=peg_quat` · `[18:21]=prev_hand` · `[22:25]=prev_peg` · `[36:39]=hole`。
  真机对齐: hand = TCP 真值(R1 契约: 末端取编码器); 光模块 = `TCP + R(quat)·夹具偏移`;
  hole = 现场几何示教的 goal 点。**夹具偏移/示教几何未标定时一律 null + 写原因, 绝不编造**。
- 落盘: 保存样本时写 `annotations.jsonl` 的 `truth` 字段 + 侧车 `sessions/<会话>/truth.jsonl`;
  `--build` 聚合成 `dataset/truth.jsonl`(每行 `stem/boxes/truth{TCP,quat,obs39_segments,dist}`)。
  删样本/清会话必须同步删 truth 侧车(`delete_sample`/`clear_session` 已带), 否则训练读到不存在的图。
- 面板: 「输入图像」窗口加 1Hz 真值行(末端/光模块 xyz · 距孔口 · 新鲜度), 拿不到的一律显示"— + 原因"。
  实测读数 `TCP=[0.43678, 0.32978, 0.222018] base_link`, age 0.02~0.04s, 关节/姿态齐全 ✅。

## 5. 机器人动作自动标注 (kinematic auto-labeling)

**核心: 机器人自己就是标定物和真值源** —— 不用棋盘格、不用人拖框。

- **S0 探针运动**: 夹着模块在视野内走 9~12 个位姿(四角+中心+2~3 个深度), 每点记 TCP 真值 + 一帧图。
  模块像素**不用人框**: 画面里只有夹爪+模块在动 → 相邻帧差分取最大运动连通域中心
  (静止的孔口/工装被差分天然排除)。
  ⚠️ 差分拿到的是"**两帧之间**"的位置 ⇒ 3D 必须配**两帧 TCP 的中点**(直接用后一帧会引入半个采样周期的滞后偏置);
  探针要**边走边采**, 静止点位差分不出东西。
- **S1 自标定**: N 对 (3D真值 → 像素) 解 **3×4 投影矩阵 P**(DLT + Hartley 归一化, 最少 6 对);
  `P = K·[R|t]` **已含内参×手眼外参**, 做 2D 标注已够; RQ 分解顺带得 `fx/fy/cx/cy` 做真实性判据。
  这就是仿真侧 `gen_yolo_data.project_3d_to_2d`(MuJoCo `cam_mat0/cam_pos/cam_fovy` 真值投影)的现场自标定版, 两边同口径。
- **S2 批量标注**: 模块中心 `= TCP + R·offset` → 8 角点(物理尺寸+姿态) → 投影 → AABB → YOLO 框(class `peg`);
  示教了 goal 点就同样投出 `hole`。**只在"夹住确认"的时段标**(判据 = 闭合后抬升随动, 与 L4 抬升试探同口径)
  → 不给"没夹住"的帧发标签。落盘复用 `save_sample` → `sessions/auto_<ts>/`, 与人工样本同结构。

### 验证基线 (实现 `tools/real_autolabel.py --selftest`, 全绿)
| 项 | 实测 |
|---|---|
| DLT 反解 12 对点 rms | **1.358e-13 px**(精确可逆) |
| 由 P 反推内参 | fx=**610.000** / fy=**607.000** / cx=**318.00** / cy=**242.00** (真值 610/607/318/242) |
| 加 1px 高斯噪声 | rms **0.811 px**(不放大误差) |
| 框几何自洽(薄片绕光轴转 90°) | 14.5×37.5px ⇄ 37.7×14.4px(宽高正确互换) |

### 两个数学坑
1. **AABB 有厚度时"旋转 90° 宽高互换"不成立**: 沿光轴的深度分量会污染包围盒(实测 40×16×12mm 件
   0° 得 28.5×39.2、转 90° 得 25.8×59.8 —— 看着像错其实是正确的透视行为)。**自检要用薄片(厚度 0)**,
   否则会误判成 bug 去改对的代码。
2. **从 P 估内参必须用 RQ 分解**(Hartley 那套: `P = flipud(fliplr(·))` + `qr((P@A).T)` + 翻回),
   裸 `linalg.qr(inv(M))` 解出来 fx 会是 1.24 这种垃圾值(实测踩到)。

### 诚实边界 (不达标不进默认档)
- 框尺寸靠**实测**模块物理尺寸(`--size`, 占位默认值必须在输出里标 pending) —— 不猜;
- 夹具偏移未标定时先按 0 解 P; rms 偏大 ⇒ 把 offset 纳入最小二乘(探针里姿态在变, 二者可辨识), 不收敛就如实报;
- **自动标注绝不能当 val** —— 评估必须在**人工标注留出集**上做, 否则是自证循环。

## 6. 运维: 采集容器停不掉 / 半行

- **收包全 0 先做三态诊断, 别一律当 DDS 假死**:
  ①`ip -4 addr show <USB网卡名>` —— **设备不存在 = 网卡拔了/未接**; ②`ping` Orin 不通 = 源头不在线;
  ③两者都正常、容器自己 `count_publishers`=0 才是 DDS 假死(修: `docker restart`)。
  实测: 拔掉 USB 千兆网卡后 `enx...` 设备消失 + ping 100% loss → 收包 0 是**源头不在**, 重启容器白搭。
- **容器"停不掉"不是故障 = 系统级服务在包裹它**: `/etc/systemd/system/ss-remote-tap.service`
  (`enabled` · `Restart=always` · `RestartSec=5` · `ExecStartPre=docker rm -f ss-remote-tap`)
  → `docker stop` 后 **5~6 秒就被重建**(`docker events` 实测 stop/die/destroy → 6s 后 create/attach/start);
  `docker inspect` 里 `RestartPolicy=no` 会误导你以为不是 docker 干的。
  要真停链: `sudo systemctl stop ss-remote-tap`(开机仍会自启, 因为 enabled)。
- **控制台 `zmax-studio` 反复重启根因 = `Restart=on-failure` + X 断**:
  journal 实证 `The X11 connection broke (error 1). Did the X11 server die?` → 退出码 1 → 5s 后又被拉起。
  老倪要求"别自动重启" ⇒ 改 `Restart=no`(正常关窗也不再弹回); 手动起: `systemctl --user start zmax-studio`。
- **被 kill 在写盘中途 → jsonl 末行是半行**: 判据 = 逐行 `json.loads` 数坏行(读尾 200KB 足够, 好行全在),
  确认只有最后一行坏 ⇒ `data.rfind(b"\n")` 截断末行(别整文件重写)。
- 停机前收尾三连: ①归档 (采集流用 `tools/ss_archive_remote_data.py` 出一致性快照 + MANIFEST;
  标定数据连 `data/yolo_annot` 一起拷到 `~/zmax_data/` 并写 MANIFEST/ sha256) ②小版本迭代 + commit/push/tag
  ③说清开机自启项(谁会自动起、谁要手动起)。
