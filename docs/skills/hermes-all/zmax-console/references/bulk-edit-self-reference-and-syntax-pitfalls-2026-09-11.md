# 批量替换/插入的自我引用与语法坑 (2026-09-11 实锤, 代价 = 整条模型路线被误判为失败)

本会话在维护 `tools/gui/*.py` 时连踩两个**同源**的批量改码坑: 用脚本批量
find-and-replace / 插入 import 时, 替换命中了"刚写进去的新代码自身"。两次都造成过
以小时计的错误排查和**错误结论**。

## 坑 1 (最贵): 批量把 `self.env.render()` → `self._render_frame()` 时命中了 `_render_frame` 自己的函数体

先加了一个包装方法 (mac 安全渲染):

```python
def _render_frame(self, h=480, w=480):
    ...
    return np.ascontiguousarray(self.env.render())   # ← 这一行也被替换了
```

然后用脚本全局替换:
```python
c = c.replace("self.env.render()", "self._render_frame()")   # 无差别全局替换
```
→ `_render_frame` 内部变成 `return self._render_frame()` = **调用自身无限递归**
→ RecursionError 被 `except Exception` 吞掉 → **永远返回全黑帧**
→ L3/VLA 推理拿到的图像全是黑的 → "模型被蒙眼" → 闭环必然失败
→ 我据此连续得出「模型路线不可行 / L3L4 联合无增益 / 0/6·0/15」等结论, **全部作废**
→ 另一会话靠"接管失败(卡转移 2318 帧)"逆向定位到黑帧, 修复后 insert 341 步 / full 865 步接管完成 + AOI PASS

**教训 (硬性)**:
1. 引入包装方法后做全局替换, **必须先在新方法体内把原调用换成不会自命中的写法**:
   `_rf = getattr(self.env, "render", None); return np.asarray(_rf())` — 属性取值法天然免疫。
2. **替换后立刻两项检查**: ①`grep -c "def _render_frame" -A3` 看函数体里是否出现自己的名字;
   ②加一个"输出非退化"的探针 (见下)。
3. **任何"包装/代理"类批量替换, 替换前先把被包装的原始调用点在脑中标出, 替换后用
   `ast` + 关键字扫描确认 helper 内部不含自身调用**。

## 坑 2: 以 `import X` 为锚点插入代码 → 劈开续行 import

批量在 `import os` 后插入 import 块, 但文件里是**续行 import**:
```python
import os
 as _os_mod                 # ← 原意是 import os as _os_mod, 被劈成两行
```
→ `IndentationError: unindent does not match any outer indentation level`
→ 本会话在 `simulink_module.py` / `node_logic.py` / `model_tree.py` 三次踩到, 并且
**坏语法被提交进 tag 发出去了** (v5.5.13 → 必须热修 v5.5.14)。

**教训**:
1. **禁止以 `import X` 行做插入锚点** — 它可能是 `import X as Y` / 续行 / 括号 import 的一部分。
   正解: 追加到**文件末尾**(模块级函数定义), 因为在函数体内被调用的 helper 只要在**调用时**
   已定义即可; 或选一个真正唯一的整行锚点并核对上下文。
2. 每次批量改码后**立刻 `python3 -c "import ast,glob; [ast.parse(open(f).read()) for f in ...]"`**
   全量语法校验 (本会话后期形成习惯: 一次校验 tools/gui/*.py + tools/*.py 全部 199 个文件)。
3. **语法坏文件绝不能被 tag 发版** — 发版前跑全量 ast 校验, 崩在启动路径上的语法错 =
   GUI 直接打不开 (用户看到"反复重启")。

## 通用防呆: 批量改码五步法

1. 备份/`git status` 确认工作区 (多分身共享仓库, 见 SKILL.md 陷阱节)
2. 替换用**窄上下文** (含前后行), 不用裸函数名/裸调用串
3. 替换后扫 helper 自身是否自命中 (`grep -n "<helper>" -A8 <file>`)
4. **全量 `ast.parse`** (所有 python 文件)
5. **输出非退化探针**: 拿真实输入跑一次关键路径, 断言输出**不是常数/全零**
   (`img.std() > 1`、`z.std() > 0`)。本会话的教训是——**"跑通了没报错"不等于"拿到真数据"**,
   RecursionError 被吞 + 兜底返回黑帧, 表现就是"安静地全错"。

## 与"静默兜底"的联合坑

`except Exception: return np.zeros(...)` 这类兜底会把"功能全废"伪装成"有输出"。
凡是包 try/except 的关键路径: 要么抛出, 要么**打日志 + 计数**, 并且在调用方
**断言输出非退化**。本次两个坑 (递归 + 静默兜底) 叠加, 导致连续多轮实验在"全黑输入"上
跑出"合理但错误"的结论。
