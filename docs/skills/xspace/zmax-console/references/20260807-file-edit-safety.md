# 大文件编辑安全 + 曲线/视频解析坑 (2026-08-07 实战)

## 1. 🚨 studio.py 截断事故 (最重教训)

**事故**: 用 execute_code 字符串索引删 DATASETS 条目(12→1)时, 定位索引错位
(`seg.index('        },\n    ]', meta_end)` 匹配到错误位置), 写回后 studio.py
从 8057 行 → **1266 行** (90% 文件丢失, 误删 TrainingModule/DataSpaceModule/
StudioMainWindow 等全部后续代码)。

**恢复路径** (有效):
1. `git log --oneline -3 -- tools/gui/studio.py` → 确认 HEAD (当天 15:52 提交,
   含上午全部改动) → `git checkout tools/gui/studio.py` 恢复
2. 重应用 HEAD 之后的所有 patch (本会话 8 处: _is_cached 分支/非模态查看器/
   当前数据集卡片/_local_datasets/_populate_table 本地行/信息按钮本地分支/
   DataSpaceModule/modules 注册/首页卡片/DATASETS 删减) — 逐处 patch 工具重放
3. 每次 patch 后语法检查 (`python3 -c "import ast..."` 或 patch 自带 lint)

**铁律**:
- **大段删除/编辑一律用 patch 工具** (old_string 精确匹配, 自带 lint + 失败回滚),
  绝不用 execute_code 字符串索引写回大文件
- execute_code 只用于: 读文件分析 / 生成独立新文件 / 纯计算
- 改大文件前先 `git add -A` (随时可 checkout 回滚); 恢复时 HEAD 版本 + 重放
  工作区 patch 列表 (本会话 patch 记录是重放清单)
- 同源旧教训: simulink_module.py 大文件 write_file 全量写曾截断 → 只用 patch 小改

## 2. lerobot 日志 step:K 解析 (2K/3K/4K 坑)

`step:1K` 展开只处理了 1K → 4000 步训练只解析到 1995 (曲线 399 点尾=1995)。
**必须展开全部**: `re.sub(r"step:(\d+)K\b", lambda m: f"step:{int(m.group(1))}000", log)`
再匹配 `step[:=]?\s*(\d+)\b.*?loss[=:\s]+([\d.eE+-]+)`。
验证: 解析后 act 尾=(5000, 0.453) 而非 (1995, x) — 步数=训练步+偏移(微调+1000)。

## 3. 曲线 ts 字段陷阱 (触发视频重新生成白屏)

**坑**: 重写 train_curve_*.json 时 ts 写 `strftime("%Y%m%d_%H%M%S")` 当前时间 →
simulink_scope `_check_newer_ckpt` 判定"新 checkpoint" (曲线 ts > 视频帧 mtime+60s)
→ 每次打开视频对话框都触发 7 模型重新 rollout → 生成中白屏/卡顿。

**修复**: 曲线 ts 必须写**真实训练完成时间** (从训练日志/目录时间), 不是重写文件的
当前时间。残缺曲线 (<100 点) 不触发重生成 (已加固)。改完曲线后统一重新 rollout
(帧 mtime 更新 → 不再误判)。

## 4. QFontMetrics 需要 QApplication

验证脚本里 `QFontMetrics(QFont(...)).horizontalAdvance(...)` 在无 QApplication
时 **Segmentation fault (139)**。offscreen 验证必须: 先 `QApplication.instance()
or QApplication(sys.argv)` 再创建 QFontMetrics。

## 5. 数据源字样统一 + YOLO 文字像素自适应

- 数据源节点名统一: `patch replace_all '"📦 metaworld 数据"' → '"📦 metaworld_act 数据"'`
  (name + links 全部同步, 与左侧功能块数据集组字样一致 — 老倪"好几个不知道用哪个")
- YOLO 文字截断根因: `len(name) > 16` **字符数截断** (emoji/中文计数失真) →
  改**像素宽度自适应字号**: `for pt in (9,8,7): if fm.horizontalAdvance(name) <= avail: break`,
  兜底 `fm.elidedText(disp, Qt.ElideRight, avail)`。视频节点(宽160px)长名 8pt 放得下;
  普通节点(130px) "🎯 YOLO 3D 检测" 9pt=106px 完整显示。

## 6. 数据集管理瘦身 (老倪: 只留 metaworld)

DATASETS 12 条 HF 条目 → 只留 `lerobot/metaworld_mt50`; `_local_datasets()` cands
只留 4 个 metaworld (peg_lerobot/peg_v2/act/mt50), 删 orin 4 项 (磁盘数据保留,
仅列表移除)。表格 = local_rows + DATASETS, 首行本地光模块。信息按钮本地分支跳过 HF API。
