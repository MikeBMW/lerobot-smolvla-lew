# 打包版运行时陷阱 — frozen 子进程 / macOS GL / 运行时脚本缺失 (2026-09-10 实测)

补 SKILL.md 的 CI/打包章节与 `references/packaging-completeness-and-ci-verification.md`。
本文记录 mac 用户报「**点运行就重启**」这类**打包版独有、源码模式完全正常**的故障链,
以及批量改代码后必须做的语法自检。

---

## 1. frozen 应用里 `sys.executable` = app 二进制本身 (最隐蔽的"反复重启")

**症状**: 打包版 GUI 里点「▶ 运行」→ app 退出又启动, 看起来像"反复重启"。源码模式不复现。

**根因**: PyInstaller 冻结后 `sys.executable` **不是 python, 而是 app 可执行文件**。
GUI 用 `[sys.executable, "tools/gen_xxx.py"]` 起子进程 → 实际是**又启动了一个 app 实例**
→ 表现为重启。PYZ 内的代码优先于外部同名 `.py`, 所以**在 mac 上就地热修无效**(实测确诊)。

**判别**:
```bash
grep -rn 'sys\.executable' tools/gui/*.py
```
分类看用法 — 两类混在一起, 别一把梭:
- ❌ **子进程启动** `[sys.executable, script]` → 必须换真 python
- ✅ 找 exe 所在目录 `os.path.dirname(sys.executable)` (docs_sync / update_checker / 自更新)
  → **这是正确用法, 不要改**

**修复**: 新增 `tools/gui/runtime_env.py`
```python
def resolve_python() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable            # 源码模式: 不变
    for name in ("python3", "python", "/opt/homebrew/bin/python3",
                 "/usr/local/bin/python3", "/usr/bin/python3"):
        p = shutil.which(name) if not name.startswith("/") else (name if os.path.exists(name) else None)
        if p:
            return p
    return "python3"                      # 兜底: 报清晰的 not found, 而不是静默重启 app
```
替换所有**子进程启动**处 (本次 6 处: `simulink_module.py`×5 + `node_logic.py`×1),
并顺便干掉对开发 venv 的硬编码 (`os.path.join(root, "gui-venv311", "bin", "python")`) —
打包机没有那个 venv, 同样会炸。

**插入 helper 的坑 (踩了两次)**: 不要拿裸 `import os` 行当锚点插入代码 —— 文件里可能是
`import os as _os_mod` (跨行续写), 插入后会把语句劈成 `import os` + ` as _os_mod` → IndentationError。
**稳妥做法: 把 helper 追加到文件末尾**(模块级函数, 调用点在函数体内执行时早已定义),
或选一个不可能续行的锚点。

## 2. `--add-data` 指向**不存在的路径** = pyinstaller 步骤硬失败

```
ERROR: Unable to find 'D:\a\...\src\lerobot\skills' when adding binary and data files.
##[error]Process completed with exit code 1.
```
**依赖装好了、前面的步骤都过了, 只因为加了一个仓库里并不存在的目录, 打包整步失败** →
双平台 job 全挂 → Release 无资产(用户表现为"新版下载不到")。
**动作: 加每一条 --add-data 前先 `ls -d <path>` 确认存在**; 本次误加 `src/lerobot/skills`
(原子技能源码其实在 `policies/left_right/state_space/skills`, 已被父目录整体打进去)。

## 3. 运行时才按路径加载的脚本也要 --add-data (dest 必须是包根)

引擎用 `importlib.util.spec_from_file_location` 在运行时按路径加载 `tools/gen_*.py`;
frozen 下它算出的目录 = **包根 (`Contents/` / `_MEIPASS`)** → 缺文件时报
`No such file or directory: '/Applications/App.app/Contents/gen_l4_demo_video.py'`。
```yaml
# 两个 job 都要加 (win 分号, mac 冒号; dest = 包根 ".")
--add-data "<repo>/tools/gen_l4_demo_video.py;."
--add-data "<repo>/tools/gen_l4_demo_video.py:."
```
**判别**: 报错路径里出现 `.app/Contents/xxx.py` 或 `_MEIPASS/xxx.py` = 该脚本没打包, 不是路径算错。

## 4. macOS 离屏 GL: 后端选择 + 线程亲和 + 打包 GL 共享库

- `MUJOCO_GL=glfw` 在 mac 上裸报 **`Failed to load GLFW3 shared library`**(系统无 GLFW3)。
  要么 `--collect-all glfw` 把 GL 共享库带进包, 要么换 `cgl`(CoreGL, 系统自带)。
  **统一解法: 按平台选自适应后端** (darwin→glfw/cgl, win32→wgl, linux→glfw|egl), 写成
  `tools/gui/mujoco_gl.py` 的 `setup_mujoco_gl()`, 各处 `setdefault` 调用并保留"用户已设则不覆盖"。
- **GL 上下文绑创建线程**: 引擎在 worker 线程调 `env.render()` 会 native segfault
  (macOS 的 CGL 更严格, 要求主线程) → **整个 app 崩**, 且 native 崩溃 try/except 抓不到。
  **务实修法: 加一层 `_render_frame()` 安全渲染** —— mac 上直接返回黑帧占位
  (R0 演示/轨迹/3D 全不受影响, 只有"渲染图像"不可用), 其余平台正常渲染, 并留
  `SS_MAC_RENDER=1` 逃生开关。把所有 `env.render()` 调用点统一收口到这一层。
- 打包补 GL/环境依赖的**共享库与数据文件**(光 pip install 不够, 静态分析看不到):
  `--collect-all glfw --collect-all gymnasium --collect-all imageio` (+ 已有 metaworld/mujoco)。
  注意别顺手 `--collect-all ultralytics`(拖 torch, 包体积爆炸到 GB 级) — 除非明确要 mac 跑 YOLO。

## 5. 批量替换后必须做**全量语法自检** (本次连挂两版)

用脚本批量改多文件(缩进/import/字符串)极易留下 `IndentationError` / 劈开的 import 语句。
**提交前一条命令兜底**:
```bash
gui-venv311/bin/python -c "
import ast, glob
bad=[(f,e.lineno) for f in glob.glob('tools/gui/*.py')+glob.glob('tools/*.py')
     for f,e in [(f,None)] if (lambda: (ast.parse(open(f,encoding='utf-8').read()), False) )()[1] ] if 0 else None
# 简明写法:
import ast, glob
bad=[]
for f in glob.glob('tools/gui/*.py')+glob.glob('tools/*.py'):
    try: ast.parse(open(f, encoding='utf-8').read())
    except SyntaxError as e: bad.append((f, e.lineno))
print('❌', bad) if bad else print('✅ 全部语法通过')
"
```
本次 v5.5.13 因 `model_tree.py` 缩进错(24 空格 vs 12)被判语法错 → **GUI 启动即崩**,
只能再发 v5.5.14 热修。全量 `ast.parse` 只要几秒, 能挡掉整次返工。

## 6. 定位 mac 侧问题的高效顺序

用户报 mac 故障时, 先在**打包清单/运行时绑定**上找, 别去猜业务逻辑:
① 缺模块 → `--hidden-import`/`--collect-all`(懒加载 import 是盲区)
② 缺文件 → `--add-data`(报错路径带 `.app/Contents/` 就是这条)
③ 缺共享库 → `--collect-all <pkg>`(GL 类)
④ 崩溃/重启 → `sys.executable` 子进程(见 §1) 或线程里的 GL 上下文(见 §4)
⑤ 构建失败 → 先看**更早的步骤**(依赖安装/验证行), 别假设是打包步骤本身
