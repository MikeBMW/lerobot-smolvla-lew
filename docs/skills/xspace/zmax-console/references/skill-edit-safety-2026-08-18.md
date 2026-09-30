# 技能文件编辑安全 — write_file 覆盖事故 (2026-08-18 实测)

## 事故
往已有 references/gui-discipline.md 追加经验时误用 skill_manage action=write_file
→ **原内容被整体覆盖丢失** (含 2026-08-09/08-10 的摄像头轮询坑), 靠 session_search 恢复。

## 铁律
- **已有文件追加/修改 → action=patch (old_string/new_string)。禁止 write_file。**
- write_file 只在创建**全新**文件时使用。
- 给 reference 文件加内容时, 先想清楚: 是"已有文件加一节" (patch) 还是"新主题新文件" (write_file)。

## 恢复渠道 (覆盖后)
session_search 搜文件名 (如 `gui-discipline.md`) → 找该文件创建/更新时的
skill_manage write_file tool 结果 → 其 arguments 含完整 file_content → 复制回来。
(会话历史里的 tool 调用会保留 file_content 原文。)

## 审查轮限制 (背景 curator 自动更新时)
read-before-write guard: 修改已加载过的文件前必须 skill_view 返回完整内容;
但 skill_view 对已加载文件返回 dedup (content_returned: false) → guard 永不满足 → 修改被拒。
**绕过: 新建独立 reference 文件承载新学习点 (创建新文件无 read-before-write 要求),
并在回复里说明哪个旧文件该吸收该内容, 留给前台会话/后续合并。**
