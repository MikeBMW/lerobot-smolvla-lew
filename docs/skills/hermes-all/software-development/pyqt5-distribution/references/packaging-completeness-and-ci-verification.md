# 打包完整性 — GUI 引用的子目录必须全进 --add-data + CI 验证行不能假设属性 (2026-09-10 实测)

本文补 SKILL.md 的「Common CI failures & fixes」与 3D 打包章节, 记录一次**打包 app 功能缺失 + 双平台
构建全挂**的真实根因链。

## 1. 症状: 源码模式画布正常, 打包版「状态空间画布加载失败」

**根因**: GUI 在运行时要 import 的 `src/lerobot/<子包>` 没进 PyInstaller 的 `--add-data` 清单。
本次实锤: v5.5.1 新增的记忆分层 `src/lerobot/memory`(mem_nodes.py / memory_store.py) 与
`src/lerobot/skills`(原子技能源码) 只加进了仓库源码, **没加进双平台 workflow 的打包清单** →
打包版 GUI 加载状态空间画布时 `ImportError` 静默失败 (源码模式一切正常, 极易误判成"画布文件坏了")。

**判别法 (先做这一步, 别去翻画布 JSON)**:

```bash
# GUI 真正引用哪些 src 子目录
grep -rhoE 'src/lerobot/[a-z_0-9]+' tools/gui/*.py | sort -u
# 与 workflow 里的 --add-data 清单逐条比对 (Windows 分号 / macOS 冒号)
grep -o 'src[^"]*lerobot[^"]*' .github/workflows/build-win-exe.yml | sort -u
```

本次比对发现缺口: `memory` / `skills` / `datasets` → 补 `memory` + `skills` 即修。
注意 GUI 里 `simulink_module.py` → `node_logic.py` → 各节点逻辑这条 import 链会拖进很多子包,
**新加一个 src 子包时, 同步更新两个 job 的 --add-data** 才是完整的动作。

## 2. 懒加载 import 是 PyInstaller 的盲区

为省启动时间, 引擎把重依赖放在**函数体内** import (如 `metaworld` 在模块级懒加载单例函数里) —
PyInstaller 静态分析看不到这种 import → 打包版一旦走到「真实化运行」就报 `No module named 'metaworld'`
(画布/演示部分却完全正常, 所以报错看起来像"只有真实化坏了")。

```yaml
# 两个 job 的 Install dependencies 都要补
pip install mujoco metaworld
# pyinstaller 加
--hidden-import metaworld --hidden-import mujoco --collect-all metaworld --collect-all mujoco
```

## 3. CI 验证行不能假设属性存在 — 否则整条流水线无声失败

```yaml
# ❌ 崩: AttributeError: module 'metaworld' has no attribute '__version__'
python -c "import metaworld, mujoco; print('metaworld', metaworld.__version__, '| mujoco', mujoco.__version__)"
# ✅ 安全: hasattr / getattr 兜底
python -c "import metaworld, mujoco; print('metaworld/mujoco OK:', hasattr(metaworld, 'ML1'), mujoco.__version__)"
```

后果极重: 该行让 **`Install dependencies` 步骤 exit 1** → 两个平台都在打包前挂掉 →
`Build Desktop (Windows .exe + macOS .app)` 整体 failure → **Release 里只有 tag、没有 app 资产**,
用户侧表现是"新版下载不到 / 构建失败但看不出原因"。依赖本身其实装好了 (日志里
`Successfully installed ... metaworld-3.1.1 mujoco-3.3.0`), 纯粹是验证行把自己搞崩。

**排查顺序 (Release 无资产时)**: ① `GET /actions/runs?per_page=N` 找 tag 对应的 run →
② 看 conclusion=failure 的 workflow → ③ `GET /actions/runs/<id>/jobs` 看**哪个 job 的哪个 step** 挂 →
④ `GET /actions/jobs/<job_id>/logs` 拉日志。**别假设是打包步骤本身的问题** — 本次就是更早的依赖步骤。

## 4. 版本号与重建流程 (本次实践)

- 版本号四处同步 (studio.py 的 UI 字符串 / update_checker.py / version_sync.py / docs_sync.py) +
  VERSION.md 追一行; **studio.py 里只改 UI 版本串 (`Z-MAX vX.Y.Z`), 别动历史注释行** (注释是版本历史)。
- 走 tag 触发正规 Release 构建: `git tag vX.Y.Z && git push origin main vX.Y.Z`。
- `workflow_dispatch` 手动触发仅作应急 (Release 资产名/版本标注不干净), 正式发版用 tag。
- ghproxy 类代理只代理 GET, **API 的 POST (workflow dispatch) 会被 403 拒绝** → 直接打
  `https://api.github.com/...` (实测 HTTP 204 = 触发成功)。
