# 2026-08-07 大文件编辑安全 + 指令最小化执行 (事故复盘)

## 🚨 事故: execute_code 字符串操作截断 studio.py (8057→1266 行)

删除 DATASETS 列表条目时用 execute_code 做 `src[:i] + ... + src[i+len(seg):]`
字符串拼接, 索引错位导致文件被截断到 1266 行, TrainingModule/DataSpaceModule/
StudioMainWindow 全部丢失。

**恢复流程** (救命的):
1. `git log --oneline -3 -- tools/gui/studio.py` → HEAD 时间 (老倪工作仪式推代码,
   15:52 提交含大部分当日改动)
2. `git checkout tools/gui/studio.py` → 恢复 HEAD 版 (7787 行)
3. 重新应用 HEAD 之后的改动 (patch 工具逐处, 每处验证)
4. 恢复后 fresh 验证: 行数 > 7500 + 关键类存在 + 运行时构造

**铁律**:
- studio.py (357KB) / simulink_module.py (334KB) **只用 patch 工具小改**
- **绝不用 execute_code 字符串拼接改大文件** (index 操作截断风险)
- 大段删除: patch 工具 old_string 精确匹配, 或 execute_code 只做"定位→替换
  完整块"且替换后立即 ast.parse + 行数检查
- 频繁 git commit (老倪工作仪式) 是唯一保险 — 当日多次提交可精确定位恢复点

## ✂️ 指令最小化执行 (老倪 08-07 三次纠正)

用户说 "YOLO 3D, 删掉检测" — 我依次误理解成: 删 YOLO 节点 → 删背景行大字 →
删背景小标, 用户连续纠正: "不是让你删掉功能" / "背景字删掉" / "就是删掉检测
两个字" / "别删多了"。

**正确语义**: 删节点名里的 "检测" 两个字 (YOLO 3D 检测 → YOLO 3D)。

**规则**:
- "删掉 X" 默认 = **改名/删字**, 不是删功能/删节点
- 动手前先确认范围: grep 该词出现位置, 最小改动 (replace_all 精确词)
- 删除类操作先做最小版 (只删明确指出的字/词), 用户说不够再扩

## GUI 重启方法 (pkill 自匹配自杀)

`pkill -f 'studio.py'` 的命令行自身含 "studio.py" → pkill 匹配自己 → exit -15,
GUI 可能没被杀 → 重启后旧实例还在跑旧代码。

**正确**: `kill -9 <PID>` (ps aux | grep '[s]tudio.py' 拿 PID) → 确认无残留 →
background 启动。kill -9 也跳过 closeEvent 的 pkill 训练, 保住后台训练。

## 节点名显示不全 (字符数截断 → 像素自适应)

旧: `if len(name) > 16: name = name[:15] + "…"` (emoji 算字符, 长名截断)。
新: 像素宽度自适应 — 9pt→8pt→7pt 降字号直到 fit, 兜底 fm.elidedText。
验证: QFontMetrics.horizontalAdvance 须在 QApplication 创建后调用 (否则段错误)。

## 曲线 ts 字段 = 真实训练时间 (防视频白屏)

写曲线 json 时 ts 用了当前时间 (17:2x) → _check_newer_ckpt 判定曲线比视频帧新 →
每次打开视频触发 7 模型重生成 → 白屏。修复: ts 写训练完成真实时间 (16:18/16:49/
17:24), 视频帧更新后不再触发。残缺曲线 (<100 点) 不触发重生成 (已有保护)。

## 系统 python3 (GUI) 缺库 → npz 直读路径

GUI 用 /usr/bin/python3 (有 PyQt5/numpy/PIL/cv2 5.0.0, **无 pandas/pyarrow**)。
- dataset_viewer 读 parquet 内嵌图像会 "No module named 'pandas'" → 本地数据集
  行配 local_npz (train.npz, numpy 直读), 帧显示 np.rot90(k=2) 与视频方向一致
- lerobot 格式数据集 (npz_to_lerobot 产物) 无 train.npz → 从同源 npz 复制
  (peg_lerobot ← peg_v2/train.npz)
- 新装库后记入记忆 (环境依赖一次配齐)

## 插销数据集链路速查 (本会话打通)

1. `tools/gen_peg_data.py --eps 30` (官方专家 SawyerPegInsertionSideV3Policy 采样,
   只留成功轨迹, corner2 视角, 128px, 失败轨迹 150 步提前终止)
2. `tools/npz_to_lerobot.py --npz train.npz --out data/..._lerobot` → parquet
3. 训练 config root 指向 lerobot 目录 (缩进 `  root:` — 正则须 `^\s*root:`)
4. rollout: obs dict 解包 (V3 env), stats 维度补零 (39D vs 3D 广播), --camera
   corner2 --rotate-ccw 与专家视频一致
