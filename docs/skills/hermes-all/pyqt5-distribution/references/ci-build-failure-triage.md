# CI 构建失败判读 + 打包清单遗漏 (2026-09-10 v5.5.8→v5.5.9 实测)

配套 `references/windows-exe-data-packaging.md` (v3.2.1 flows/ 遗漏)。本文补 2026-09-10 的两个新根因
+ CI 失败判读方法。

## 1. 症状 → 根因映射 (先查打包清单, 别先怀疑代码)

| 用户报的症状 | 真实根因 | 修 |
|---|---|---|
| 打包版「状态空间画布加载失败」(主窗口能开) | `src/lerobot/memory` (记忆分层) + `src/lerobot/skills` 没进 `--add-data` → ImportError | 双平台补 `--add-data` |
| 打包版点某功能报 `No module named 'metaworld'` | 引擎**函数内懒加载** `def _make_env(): import metaworld` → PyInstaller 静态分析看不见 | `--hidden-import` + `--collect-all` |
| CI 双平台都 fail 在名为 `Install dependencies` 的步骤 | **探针行**崩, 不是装依赖崩 —— `metaworld.__version__` 属性不存在 → AttributeError | 换 `hasattr(metaworld,'ML1')` |

## 2. 审计: GUI 引用的 src 包 vs CI 打包的 src 包

打包清单是手工维护的, **repo 每新增一个可 import 的 `src/` 子目录就必须同步 CI**, 否则源码模式正常、
打包版挂。一条命令对齐两边:

```bash
cd <repo>
grep -rhoE 'src/lerobot/[a-z_0-9]+' tools/gui/*.py | sort -u            # GUI 实际用到哪些
grep -oE 'src[\\/]lerobot[\\/][a-z_0-9]+' .github/workflows/*.yml | sort -u   # CI 打了哪些
```

分隔符: Windows `src\lerobot\X;src\lerobot\X` (分号), macOS `src/lerobot/X:src/lerobot/X` (冒号)。
写错不报错但资源丢 → 现象仍是运行时 ImportError。

典型 CI 打包行 (双平台, 供对照):
```
# Windows (单行, 分号)
--add-data "$env:GITHUB_WORKSPACE\src\lerobot\policies\left_right;src\lerobot\policies\left_right"
--add-data "$env:GITHUB_WORKSPACE\src\lerobot\memory;src\lerobot\memory"
--add-data "$env:GITHUB_WORKSPACE\src\lerobot\skills;src\lerobot\skills"
# macOS (多行, 冒号)
--add-data "$GITHUB_WORKSPACE/src/lerobot/memory:src/lerobot/memory" \
--add-data "$GITHUB_WORKSPACE/src/lerobot/skills:src/lerobot/skills" \
```

## 3. 懒加载模块 → hidden-import / collect-all

模块级 `import` 会被 PyInstaller 收集; **函数体内的 `import` 不会**。后者在打包版表现为
"平时好好的, 一用这个功能就 ModuleNotFoundError"。修:

```bash
--hidden-import metaworld --hidden-import mujoco \
--collect-all metaworld --collect-all mujoco
```
并在同一 job 的 `pip install` 补 `mujoco metaworld`。
注意 `mujoco` 有 `__version__`, `metaworld` **没有** —— 探针别写 `metaworld.__version__`。

## 4. CI 失败判读 (steps 的名字会骗人)

失败步骤名可能是 `Install dependencies`, 但真正崩的是你塞进去的探针 `python -c ...`。步骤名只标"哪一步",
不标"哪一行"。取日志两步:

```bash
TOKEN=$(python3 -c "import re;s=open('~/.git-credentials-expanded').read();m=re.search(r'https://[^:]+:([^@]+)@github',s);print(m.group(1) if m else '')")
# ① 找失败的 job 与具体 step
curl -s -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/<owner>/<repo>/actions/runs/<RUN_ID>/jobs" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);[print(j['name'],j['conclusion'],[ (s['name'],s['conclusion']) for s in j.get('steps',[]) if s.get('conclusion') not in ('success','skipped',None)]) for j in d['jobs']]"
# ② 拉该 job 日志, 抓 error 上下文
curl -sL -H "Authorization: token $TOKEN" \
  "https://api.github.com/repos/<owner>/<repo>/actions/jobs/<JOB_ID>/logs" | grep -iE 'error|failed|Traceback' | tail
```

实测证据 (build 34421966900) 日志末三行:
```
Successfully installed ... metaworld-3.1.1 mujoco-3.3.0 ...   ← 依赖其实装成功了
AttributeError: module 'metaworld' has no attribute '__version__'   ← 我的探针崩了
##[error]Process completed with exit code 1.
```

## 5. 发布/触发注意 (国内网络)

- `ghproxy.net` 只代理 **GET**, 用它 POST `/actions/workflows/*/dispatches` 会 403/Invalid input。
  **直接用 `https://api.github.com`** 发 dispatch → HTTP **204** = 成功。
- 正式发版走 tag (`git tag vX.Y.Z && git push ... main vX.Y.Z`) 触发正规 Release 构建;
  workflow_dispatch 只适合验证性重跑 (标签会是 dev/手动值, Release 号不干净)。
- push 大文件走 ghproxy 会断, 但 push 少量改动/标签稳定可用。
