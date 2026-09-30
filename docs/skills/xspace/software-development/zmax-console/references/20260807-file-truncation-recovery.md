# 2026-08-07 文件截断事故 + GUI 重启铁律 + 最小解读

## 1. 大源文件禁止 execute_code 字符串切片 (事故全记录)

**事故**: 用 execute_code 的字符串 index/slice 删除 studio.py 里 DATASETS 的非
metaworld 条目, 索引错位 → **studio.py 从 8057 行被截断到 1266 行** (DatasetModule
之后所有类 — TrainingModule/DataSpaceModule/StudioMainWindow — 全部消失)。
语法检查 ast.parse 通过 (截断点在类边界), 但文件内容只剩 1/6。

**恢复流程 (实测成功)**:
```bash
git log --oneline -3 -- tools/gui/studio.py     # 确认 HEAD 新鲜度
git log -1 --format=%ci -- tools/gui/studio.py  # HEAD 时间
git checkout tools/gui/studio.py                # 恢复 HEAD 版 (15:52 提交含当天大部分改动)
wc -l tools/gui/studio.py                       # 验证行数回到 ~7800
python3 -c "import ast; ast.parse(open('tools/gui/studio.py').read())"
grep -c "def _local_datasets\|class DataSpaceModule\|class StudioMainWindow" tools/gui/studio.py
```
然后**重应用 HEAD 之后的全部补丁** (本案例 8 处: _is_cached metaworld 分支 /
_on_view_dataset 非模态+local_root / 当前数据集卡片 / _current_dataset_html /
_local_datasets / _populate_table 本地行 / _show_dataset_info 本地分支 /
DataSpaceModule + modules dict + 首页卡片)。每处用 patch 工具 (有 lint), 全改完
跑 fresh 验证 (行数>7500 + 关键方法存在 + 运行时构造)。

**铁律**:
- 大源文件 (studio.py 7K+ 行) 的删除/重构 **只用 patch 工具** (old_string 精确匹配),
  禁止 execute_code 字符串切片重建。
- 批量改动前先 `git log -1 --format=%ci -- <file>`: HEAD 新鲜 (当天提交过) 则
  checkout 恢复代价低; HEAD 旧则先手动 commit 再动工。
- 改完必验: `wc -l` (行数量级不变) + ast.parse + grep 关键符号。
- 大段删除用 `execute_code` 读→算边界→打印边界→确认→再写 (两步), 别一步到位。

## 2. GUI 重启: kill 精确 PID, 禁止 pkill -f 'studio.py'

`pkill -f 'studio.py'` 的**命令行自身含 "studio.py"** → pkill 匹配到自己 → 自杀
(exit -15), 且可能没杀到真正的 GUI → 新旧实例并存、旧代码继续生效
("重启了么?"/"没重启" 的元凶之一)。正确流程:

```bash
ps aux | grep '[s]tudio.py' | awk '{print $2, $9}'   # 拿全部实例 PID + 启动时间
kill -9 <pid>                                          # 精确杀 (kill -9 跳过 closeEvent, 不误杀 lerobot_train 续训)
sleep 2; ps aux | grep '[s]tudio.py'                  # 确认无残留 (输出空 = 已停)
# 后台启动:
cd ~/lerobot-smolvla-lew/tools/gui && ZMAX_AUTO_RUN=1 DISPLAY=:0 bash run_studio.sh
# (terminal background=true, 不是 nohup/disown)
sleep 14
ps -o lstart= -p <新PID>                               # 确认启动时间 = 刚刚
df -h / | tail -1                                       # 磁盘不涨
pgrep -f 'lerobot_train'                                # 训练进程存活 (kill -9 不触发 closeEvent pkill)
```
验证"新实例真的在跑新代码": `ps -o lstart= -p <pid>` 启动时间必须 == 重启时刻,
且 `ps aux | grep '[s]tudio.py' | wc -l` == 1 (无旧实例残留)。

## 3. 老倪"删掉XX" = 最小解读 (沟通铁律)

- "YOLO 3D, 删掉检测" = **把名字里的"检测"两个字删掉** (YOLO 3D 检测 → YOLO 3D),
  **不是**删 YOLO 功能/节点/背景。
- 我误解成"删功能"→ 又误解成"删背景行大字"→ 把背景行的大字模型名+小标都删了
  → 老倪连纠三次: "就是删掉检测两个字" / "别删多了" / "你干啥呢"。
- **规则**: 用户说"删掉 X"时, 默认 = 从名字/文本里删 X 字词 (replace_all 改名),
  绝不默认删节点/功能/整块代码。做了超出范围的事立即还原 (git show HEAD 拿原始
  代码段 patch 回去)。
- 顺带: 用户中途连发短消息纠正时, 先停手回看最新消息再动手, 别在错误方向上继续。

## 4. Qt ad-hoc 验证脚本: QFontMetrics 前必须先建 QApplication

验证节点文字宽度 (horizontalAdvance) 的 offscreen 脚本, 不先建 QApplication 就调
QFontMetrics → **Segmentation fault (exit 139)**。模式:
```python
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)   # 必须先于 QFontMetrics
from PyQt5.QtGui import QFont, QFontMetrics
fm = QFontMetrics(QFont("Arial", 9, QFont.Bold))
```
节点文字截断修复范式 (YOLO 3D 检测 9pt 106px 在 110px 可用宽内完整显示):
字符数截断 (len(name)>16 → name[:15]+"…") 是坏设计 — 改**像素宽度自适应字号**
(9→8→7pt 逐级降, 仍超宽才 elidedText 兜底), 且要删掉旧字符截断 (含 emoji 时
len 与像素无关)。

## 相关
- 曲线 ts 必须写真实训练时间 (防 _check_newer_ckpt 误触发白屏): lerobot-act-training
  的"训练曲线 json 是易失资产"节
- stats 39D-3D 广播补零 / obs dict 解包 / 插销数据集: lerobot-act-training
  `references/rollout-inference-fixes.md`
