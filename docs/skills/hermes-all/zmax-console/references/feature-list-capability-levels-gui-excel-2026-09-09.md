# 功能清单 L2/L3/L4 消费端落地: GUI Tab / Excel 导出 / 网页 (2026-09-09 老倪两轮抓包)

## 背景: "功能清单按 L2/L3/L4 区分" 完成了但用户说"怎么还是没有"
- 三套分级语义别混: ① 画布能力档位 L2🔧/L3🚀/L4🏆 = `src/lerobot/verification/capability_levels.py`
  权威 (CAPABILITY_LEVELS, L2-A01 编号); ② 规范场三层 G1/G2/G3 = node_func_tree.py (dialog Tab1);
  ③ 产品作业 L1刚体/L2柔性/L3性能 = PRODUCT_TREE (dialog Tab2, 客户视角)。用户说 L2/L3/L4 = ①。
- **教训**: 数据源有清单 ≠ 完成。用户看的是**消费端** (GUI 节点对话框 / 导出 Excel / 网页) —
  三处必须都显式展示同一 capability_levels 内容, 漏一处就"还是没有" / "Excel 不是节点里的"。

## GUI: verification_dialog.py 第⑤ Tab 能力档位
- 构造末尾加 `self.trcap` 树 (3 列: 档位/功能, 编号, 说明) → `addTab("⑤ 能力档位 · L2🔧基础 / L3🚀高级 / L4🏆专家")`
  → `_populate_cap()`: 顶层 L2/L3/L4 三组 (黄/金/紫着色, 组标题 = 档位名 + 功能数 + tech 摘要),
  子项 = 每 func (fid + name + desc)。数据 `_load_cap()` (spec_from_file_location 加载, 同 _load_tree 模式)。
- `if mode == "feature": self.tabs.setCurrentIndex(4)` — 功能清单节点 (Feature) 双击默认就停在能力档位 Tab。
- QColor 需 from PyQt5.QtGui import QColor (文件原只 import QtCore/QtWidgets)。

## Excel: export_verif_excel 加「能力档位 L2-L3-L4」sheet
- 放**函数末尾 wb.save 前** (不能放函数头 — 见 openpyxl 坑②), 三档色块标题行
  (PatternFill 绿/橙/紫 + Font 白粗) + 每 func 一行 (档位/编号/功能/说明), `wb.active = _ws0`
  (打开 Excel 默认先见能力档位 sheet)。
- 验证: offscreen 导出 xlsx → load_workbook → sheetnames 含新 sheet; L2 11/L3 5/L4 11 计数;
  active.title == 新 sheet。

## 网页: gen_web_feature_pages.py function-list.html §0 能力档位章节
- §1 前插章节: 三档 h3 (着色) + tech/auto_ref note + 编号/功能/说明表; capability_levels 用
  spec_from_file_location 局部加载 (gen 脚本在 tools/, src 路径 = 上溯两级 + /src)。
- capability_levels.html 独立页另有 export_capability_web.py (生成 /tmp → reports/web) —
  部署需要 ZMAX_ECS_PW (本机 .env 没有; 22 端口密码不对; collect_upload_npz.py 里是 23 端口旧密码,
  连不通) — ECS 上传卡凭据时, 本地产物先交付并明示卡点。

## openpyxl 两坑 (2026-09-09 实锤)
1. **sheet 名禁 `/`**: `create_sheet("能力档位 L2/L3/L4")` → ValueError
   "Invalid character / found in sheet title"。用 `L2-L3-L4`。
2. **`create_sheet(name, 0)` 抢 wb.active**: Workbook() 默认 active (后面才改名"功能清单") 时,
   插入 index0 让 wb.active 指向新 sheet → 后续 `ws = wb.active; ws.title = "功能清单"` 把新 sheet
   改名覆盖, 两套数据 (规范场 + 能力档位) 双写进同一 sheet 静默乱。
   **正解**: 新 sheet append 末尾 (`create_sheet(name)` 无 index), 最后 `wb.active = 新sheet`。

## 导出前后数字 (验收锚点)
- L2 11 项 (A01-A11) · L3 5 项 (B01-B05) · L4 11 项 (C01-C08 + C09 抗干扰/C10 流形预测器/C11 记忆分层,
  v5.5.1 新增) — 节点树/Excel/网页三处一致。
- 相关: capability_levels.py 里 L4 funcs 的 groups 用 verification_layer 真实 t_ 前缀组,
  无对应组时 resolve_tests 返回空不崩 (可诚实标 desc 为训练/实测证据)。
