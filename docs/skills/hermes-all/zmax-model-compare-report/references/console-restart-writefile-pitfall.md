# 控制台 (studio.py) 启动/重启实录 — 2026-08-06

老倪要求"控制台你重启一下, 我看看"时的完整排查链。归属: zmax-console 技能已超 100KB 上限无法写入, 此文件挂 zmax-model-compare-report 下作为共享参考。

## 启动命令 (关键)

```bash
# ✅ 正确 — PyQt5 在系统 python, 不在项目 .venv
DISPLAY=:0 /usr/bin/python3 tools/gui/studio.py &

# ❌ 错误 — 直接 python3 会报 ModuleNotFoundError: No module named 'PyQt5'
#    PATH 里的 python3 是 hermes venv (Hermes Agent 自带) 或项目 .venv (训练用), 都没有 PyQt5
```

环境探测 (逐个测哪个 python 有 PyQt5):
```bash
/usr/bin/python3 -c "import PyQt5; print('OK')"   # ✅ 唯一 OK 的
.venv/bin/python -c "import PyQt5"                 # ❌ No module named 'PyQt5'
```

## 重启流程

1. 找旧进程: `ps aux | grep studio.py` (有 bash -lic 壳 + python3 studio.py 两个 PID)
2. 杀: `kill <pid1> <pid2>`; 等 2s; `ps aux | grep studio.py | grep -v grep | wc -l` 应 0
3. 启动: `DISPLAY=:0 /usr/bin/python3 tools/gui/studio.py` (terminal background=true, 禁 nohup 前台包装被 Hermes 拦截)
4. 验证: `process(action=poll)` 看 status=running; 日志 `Unknown property cursor` 是无害 Qt QSS 警告 (样式表里不存在的属性), 不是崩溃

## 启动失败分级排查

| 报错 | 根因 | 修复 |
|---|---|---|
| `ModuleNotFoundError: No module named 'PyQt5'` | 用了错误 python (hermes venv / 项目 venv) | 换 `/usr/bin/python3` |
| `ImportError: cannot import name 'SimulinkModule' from 'simulink_module'` | simulink_module.py 被截断/类丢失 (write_file 事故) | git 恢复完整版 (见下) |
| `IndentationError: expected an indented block after 'if' statement on line NNNN` | 文件尾部被截断 | `git checkout` 或 `git show HEAD~N:... > 文件` |
| 窗口不弹出 / 假死 | DISPLAY 未设 | `export DISPLAY=:0` (WSLg) |

## 不弹窗验证 (offscreen)

```bash
QT_QPA_PLATFORM=offscreen /usr/bin/python3 -c "
import sys; sys.path.insert(0, 'tools/gui')
import simulink_module as sm
print(hasattr(sm, 'SimulinkModule'))  # True = 可加载
"
```

## ⚠️ simulink_module.py 截断事故 (2026-08-06 差点丢整个 GUI)

**事故链**: 用 `read_file(path, limit=2000)` 读大文件 → 内容被 limit 截断 (文件实际 5423 行, 只读到 1771 行附近) → `write_file` 全量写回 → **文件尾部丢失**, SimulinkModule 类 (在 1553+ 行) 全没 → 控制台启动崩 `cannot import name 'SimulinkModule'`。

**教训 (铁律)**:
- 大文件 (GUI 模块 1500+ 行) 修改**一律用 patch (old_string/new_string)**, 禁止 read_file+write_file 全量回写
- execute_code 里若必须读写: read_file 不要传 limit (全量读), 或直接 open(path).read()
- 改完必验: `ast.parse` 语法 + `wc -l` 对比行数 (应比改前多插入行数, 不能少)
- **先 git commit 再编辑** — 出事能 checkout; 未提交 = 永久丢失

**恢复方法**: 从 git 历史找完整版
```bash
git show HEAD~3:tools/gui/simulink_module.py > /tmp/simulink_full.py
wc -l /tmp/simulink_full.py        # 5423 (完整) vs 1771 (截断)
cp /tmp/simulink_full.py tools/gui/simulink_module.py
# 然后重新应用所有未提交的 patch 修改
```

## Simulink 画布节点插入 = 连线索引全错位

- 节点列表顺序 = 连线索引基准。前部插入节点 (如 YOLO 开关/检测/2D→3D/StateAdapter 插在数据节点后) → 所有后续索引 +N → 原连线全部错位, **且错位不报错** (画布照常渲染但数据流错误)
- **布局数组用节点名匹配 (插入安全), 连线数组用索引 (插入即碎)** — 机制不同!
- 修法: 插入节点后**重写整个连线段** (数清新索引: 0=数据, 1=YOLO开关, 2=YOLO检测, 3=2D→3D, 4=StateAdapter, ACT 5-11, SmolVLA 12-15, LEW 16-20, VLA-Touch 21-26, AWE 27-32, Scope=33, 推理=34, 视频 35-39, PDF=40), 感知链显式加 (0,1,"图像"),(1,2,"开=39D"),(2,3,"2D框"),(3,4,"3D坐标")
- 新节点类型要 4 处注册: ① 类型字典 (simulink_module.py L37 附近, NODE_STYLE dict) ② node_logic.py `_reg()` ③ 渲染分支 (`elif t == "xxx_gate"` 画 checkbox) ④ simulink_ci.py NODE_TYPES set
- 模块库 (LIBRARY) 与布局行数组也要同步加 — 只加节点定义不加布局行 = 画布不显示 (老倪铁律: "新模板须显眼工具栏按钮 + 新节点须注册node_logic")
