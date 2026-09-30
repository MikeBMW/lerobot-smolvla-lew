# PPT 指令引擎 (Z-MAX Console)

PPT 作为系统总控指令源，用户写 PPT → 控制台解析 → 驱动动作。

## 架构

```
tools/gui/ppt_engine.py — 解析引擎
静界/00-指令/             — 指令存储目录
  ├── Z-MAX指令控制模板.pptx  — 模板文件
  └── ...                    — 用户自定义指令
```

## 指令格式

每页 PPT = 一条指令。
- **标题**: `动词: 指令名称` (如 `CREATE_FILE: Z700F操作指南`)
- **正文**: 参数 (JSON 或 键值对)

### 支持的动词

| 动词 | 动作 | 示例 |
|------|------|------|
| CREATE_FILE | 创建文档到静界/ | `路径: 01-培训/Z700F操作指南.md` |
| RUN_CMD | 执行系统命令 | `lerobot-train --config ...` |
| TRAIN_MODEL | 记录训练任务 | `数据集: pusht, 步数: 500` |
| GIT_COMMIT | 提交并推送 | `信息: feat: 第3轮完成` |
| DEPLOY | 部署到 ECS | `目标: 39.102.211.79` |
| EVAL_MODEL | 评估模型 | `模型: SmolVLA v2` |
| UPDATE_CONFIG | 修改配置 | `参数: batch_size=8` |

## GUI 集成

菜单: **帮助文档 → 🎯 PPT 指令控制**
- 📝 生成指令模板 PPTX → 调用 `ppt_engine.create_template()` 生成带示例的 .pptx
- ▶ 解析并执行当前 PPT → 文件选择器 → `ppt_engine.run_all()` 执行所有指令
- 📂 打开指令目录 → 打开 `静界/00-指令/`

## 使用流程

1. 点击「生成指令模板 PPTX」→ 获得 Z-MAX指令控制模板.pptx
2. 在 PPT 中按格式写指令（每页一条）
3. 点击「解析并执行当前 PPT」→ 选择 PPTX → 自动执行
4. 执行日志通过 QMessageBox 展示

## PPT 标记约定

用户在 PPT 右上角写特定标记，静静检测后自动处理：

| 标记 | 含义 | 行动 |
|------|------|------|
| `V 静` | 在这页画 Z-MAX 三层架构图 | 用 PPT 横线布局 + 文本内容重建 |
| `V 指令` | 执行指令 | 解析并执行该页内容 |

**IMPORTANT**: 标记是 `V 静` 不是 `▶ 静`。标记框使用浅橙色底 (`#FFF0E0`) + 橙色边框 (`#F7A90B`)。

### 画架构图的工作流

1. 使用 `横线` 布局 (Master 1 Layout 4): `prs.slides.add_slide(prs.slide_masters[1].slide_layouts[4])`
2. 不要画形状！只添加文本内容（文本框），背景和布局由模板提供
3. 如果用户有手绘布局：读取形状参数 → 完全复制（位置、大小、颜色、文字）
4. 配色使用模板色板：标题 #002060, 正文 #000000, 强调 #0070C0 / #F7A90B

## 依赖

- `python-pptx` — 需在 PyInstaller build 中 pip install
- `--add-data \"ppt_engine.py;.\"` — 作为本地模块打包
