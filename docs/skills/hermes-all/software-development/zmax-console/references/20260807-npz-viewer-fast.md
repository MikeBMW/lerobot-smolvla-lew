# 2026-08-07 数据集查看器 npz 修复链 + 大文件截断事故

## 一、数据集查看器 (dataset_viewer.py) 系列修复 — 老倪逐个点出的坑

### 环境事实 (GUI 用系统 python3, 非 .venv)
- 系统 python3 有: PyQt5 / numpy / PIL / cv2 5.0.0 (cv2 曾漏装, 老倪质问"怎么不提前安装" — 环境依赖一次配齐)
- 系统 python3 没有: pandas / pyarrow → **parquet 内嵌图像读不了** → 本地数据必须走 npz 路径 (numpy)

### 本地数据格式差异 (数据集管理里两个插销数据集的区别)
- `metaworld_peg_v2` = 原始采集 npz (30 eps / 5850 帧) — 查看/数据源用
- `metaworld_peg_lerobot` = npz_to_lerobot 转出的 parquet (24 eps / 4800 帧) — 训练管道用
- 两者同源; peg_lerobot 无 train.npz → 查看器无图 → **cp peg_v2/train.npz 过去即可** (同数据)

### 修复链 (按发现顺序)
1. **exec_ 模态 WSLg 弹不出** → `viewer.show()` 非模态 (WSLg 弹窗零容忍)
2. **本地数据不在 HF 缓存** → DatasetViewer 加 `local_root`/`local_npz` 参数 (项目 data/ 目录)
3. **parquet 无 pandas** → npz 读取路径 `_load_npz_frame` (numpy 直读, 系统环境可靠)
4. **AV1 mp4 cv2 解码失败** (metaworld_act 的 videos/ 是 AV1) → 报"帧 0 超出范围" →
   **有 local_npz 时 npz 优先于视频** (`_load_video_frame` 开头先判 npz)
5. **frame_slider 初始 maximum=0** → 必须先点"加载帧"才能翻 → **打开查看器 QTimer.singleShot(0, _load_video_frame) 自动加载第一帧** (maximum 就位)
6. **滑块变化只改数字不换图** → `_on_frame_changed` 里触发 `_load_video_frame()`
7. **图像反了 → 180° 旋转 (⚠️ 后修正为条件旋转)**: 插销数据 (peg_v2/peg_lerobot, corner2 采集与视频同源) 需 `np.rot90(rgb, k=2)` 与视频一致; **metaworld_act 是 MT50 官方数据 (方向本来就正确) → 无条件旋转反而转反** (老倪: "套环图像反了")。最终: `if "peg" in (self.local_npz or ""): rgb = np.rot90(rgb, k=2)` — 按数据集来源条件旋转, 别一刀切
8. **翻帧 1.5s/帧 (慢!)** → 根因: **压缩 npz 的 NpzFile 数组访问是 lazy 解压**, 每帧 `d["observations"]` 都重新解压 →
   首次 load 时 `_np.array(d["observations"])` 提取到内存 ndarray → **翻帧 0-1ms** (提速 1500 倍)
   (注意: 压缩 npz 首次解压 ~1-2s/900MB, 属正常; 缓存 NpzFile 不够, 必须提取数组)
9. **缓存状态显示"—"** (metaworld_mt50) → `_is_cached` 的 glob 需**递归** (`**/*.parquet`, parquet 在 chunk-000/ 子目录)
10. **任务数列误填帧数 (老倪: "为什么显示 4800个/696个")**: 本地数据集是**单一任务演示集** (无"任务数"概念), `_local_datasets` 的 `tasks` 字段曾填 `frames` → 任务数列显示 4800/696 荒谬 → 改 `"tasks": "—"` (帧数/eps 在描述列); HF 云端多任务条目 (MetaWorld MT50) 才填真任务数 50
11. **peg_v2 vs peg_lerobot 重复 (老倪问两次区别)**: 同源插销数据两格式 (v2=原始 npz 30eps/5850帧, lerobot=训练 parquet 24eps/4800帧) — 数据集管理**只留训练用的 peg_lerobot**, v2 是中间产物不显示 (老倪: 重复直接删); 解释口径: eps=演示次数 (24 次成功插拔示范), 帧=总图像张数
12. **GUI 重启必须精确 PID kill**: `pkill -f 'studio.py'` 的命令行自身含 "studio.py" → **自匹配自杀 (exit -15) 且可能没杀到 GUI** → 旧实例还在跑新代码没加载 (多轮踩坑: 改了代码老倪看不到效果)。可靠流程: `ps aux | grep '[s]tudio.py'` 拿 PID → `kill -9 <PID>` → 确认 `ps` 无残留 → `terminal(background=true)` 重启 → sleep 14 后确认新 PID + 磁盘

### 验证手法
- 每次 patch 后 offscreen tempfile 验证: 构造 DatasetViewer → `_load_video_frame()` → `lbl_image.pixmap()` 非空 + `frame_slider.maximum()` 就位 + 耗时断言 (翻帧 <10ms)
- QFontMetrics 必须先建 QApplication, 否则 segfault

## 二、大文件截断事故 (studio.py 8057 → 1266 行) — 血泪教训

### 事故经过
删除 DATASETS 大段条目时用 **execute_code 字符串索引重建** (src[:i] + 新块 + src[j:]) —
字符串索引错位 (`seg.index` 找到错误位置 / 长度错) → **文件尾部 6500 行被截断**, 语法却 OK
(DatasetModule 之后的所有类消失: TrainingModule/DataSpaceModule/StudioMainWindow 全没了)

### 恢复路径 (当时奏效)
1. `git log --oneline -- tools/gui/studio.py` + `git log -1 --format=%ci` — 找最近 commit (HEAD 15:52 含当天大部分改动)
2. `git checkout tools/gui/studio.py` — 恢复 HEAD 版 (7787 行, 语法 OK)
3. **重新应用 HEAD 之后的全部改动** (8 处 patch: _is_cached 分支/非模态查看器/当前数据集卡片/_local_datasets/_populate_table 本地行/信息按钮本地分支/DataSpaceModule/modules dict/首页卡片/DATASETS 精简)
4. 补漏: HEAD 版没有 `_repo_root` 方法 (本会话加的) — 恢复后运行时 AttributeError → 补方法

### 纪律 (以后严格遵守)
- **>300KB 的 Python 文件 (studio.py ~350KB, simulink_module.py ~334KB) 只用 patch 工具逐块改**
- **execute_code 的字符串重建 (src[:i]+新块+src[j:]) 禁用于大文件删除** — 索引错位静默截断, 语法检查都发现不了
- 删除大段 → 用 patch (old_string/new_string 精确块) 或先 `cp file file.bak` 备份
- **patch 删重复行时注意相邻行** (08-07 晚二次事故): 删 `dl_btn.clicked.connect` 重复行时误删了相邻的
  `manual_btn = QPushButton(...)` 创建行 → NameError GUI 直接起不来 (启动日志才看得到)。删除时
  old_string 带足上下文 (含前后行), 删完 grep 确认引用还在。
- **studio.py 改动后必须完整启动验证**: 只 ast.parse 语法不够 — offscreen 构造完整
  `StudioMainWindow()` (会实例化 DatasetModule/DataSpaceModule/所有页) 才能抓 NameError/未定义类。
  启动失败先看进程日志 (`process poll` 的 output_preview 有 traceback)。
- 文件被"外部修改"警告时 (execute_code 写回未记录) → 立即重读全文件再动手
- git checkout 恢复 = 最后手段, 会丢未提交改动; 恢复后必须核对: 行数 / 关键类 grep / 运行时构造

## 三、指令最小化执行 (老倪多次纠正)
- "YOLO 3D, 删掉检测" = **删"检测"两个字** (改名 YOLO 3D), 不是删节点/删功能
- "背景字删掉" → 我先删了背景行大字, 老倪连纠 3 次: "就是删掉检测两个字 / 别删多了"
- 教训: **老倪的删除指令默认最小化理解 (改名/删字), 先做最小动作; 理解歧义时宁可先问一句**
- 误删的恢复: git show HEAD 提取原始代码块 → patch 还原 (背景行大字)
