# 版本号迭代纪律（studio.py 中版本/小版本升级）

> 实测 2026-09-25：用户「中版本迭代, 发布 windows mac 版本」→ v5.14.0 → v5.15.0。
> 过程中我的升级脚本**差点改写变更历史**，被自建守卫在写盘前拦下。

## 核心风险：同一个版本串出现在两类位置

`studio.py`（约 12,000 行）里 `v5.14.0` 这类串出现在：

| 类别 | 例子 | 该不该改 |
|---|---|---|
| **① 界面显示位** | `ver = QLabel("Z-MAX v5.14.0")`、`setWindowTitle("XSpace Studio — Z-MAX v5.14.0 [W-01]")` | ✅ 该改 |
| **② 历史变更块标题** | `# v5.14.0: v5.14.0 (中版本): ① ...（长段历史）` | ❌ **绝不能改** |

盲写全局替换：
```python
src.replace("v5.14.0", "v5.15.0")     # ❌ 同时命中两类 → 历史块被改名 = 篡改历史
```
实测 `grep -c 'v5.14.0'` 命中 **5 处**，而显示位只有 **3 处** —— 多出来的 2 处正是历史块。
更阴的是：替换后再去找锚点 `"# v5.14.0:"` 会**找不到**（已被自己改名），此时若没有守卫就会
一路写盘，把历史悄悄改掉。

## 正确做法：写成脚本，一次跑完，自带校验

```python
OLD, NEW = "Z-MAX v5.14.0", "Z-MAX v5.15.0"   # ★ 按"显示模式"匹配, 不用裸版本号

# 1) 改前备份 + 处数断言
src = open(P, encoding="utf-8").read()
n = src.count(OLD)
if n != 3:                      # 多于预期 → 模式太宽, 立即中止
    return 2
# 2) 只替换显示位
src2 = src.replace(OLD, NEW)
# 3) 新增变更块用"插入", 不是替换
anchor = "# v5.14.0:"           # 上一版变更块标题
src2 = src2.replace(anchor, ENTRY + anchor, 1)   # ENTRY 以 "# v5.15.0: ..." 开头
open(P, "w", encoding="utf-8").write(src2)

# 4) 写盘后四条校验 (缺一不算完成)
chk = open(P, encoding="utf-8").read()
assert chk.count(NEW) >= 3                      # 显示位都升了
assert "# v5.14.0:" in chk                      # ★ 历史块原样保留 ← 防篡改关键断言
assert chk.count("Z-MAX v5.14.0") == 0          # 显示位旧串清零
import ast; ast.parse(chk)                      # 12000 行文件手滑一次就崩
```

**校验不过就不要写盘**（或从备份回滚）。

## 配套要点

- **先备份**：`cp tools/gui/studio.py /tmp/studio_v5140_backup.py`。
- **变更块格式对齐既有风格**：历史块是 `# vX.Y.Z: <一句话标题> — <用户原话引用> ①...⑩...`，
  新块照此写，否则未来 grep 会漏。
- **顺序**：新块插在上一版之前（最新的在最上面），插完 `grep -n '^# v5\.1[45]\.'` 确认顺序。
- **触发发布**：`git tag -a v5.15.0 -m "..."` + `git push origin v5.15.0`
  → `.github/workflows/build-win-exe.yml` 自动并行出 **Windows .exe + macOS .app**，
  两个 job 挂到同一个 Release（tag 决定 exe 文件属性里的版本号，不再是 0.0.0）。
- **复核发布**（用户要"发布"就得给可下载链接 + HTTP 证据）：
  `curl -sIL <release asset url>` 应为 200；三个链接都测：发布页 + `.exe` + `-macOS.zip`。
- **`release.yml`(PyPI) 会被 skip** 是正常的：它比对 tag 版本与 `pyproject.toml` 的库版本
  （应用系列 `v5.x` vs 库 `0.5.2`），不匹配就跳过 —— 别当成失败去修。
- **Docker/ACR job 失败**先查历史：`gh`/API 看该 workflow 最近若干个 tag 的结论，
  若**一直都失败**（实测 v5.11.1 起全部 failure，卡在 `Log in to Alibaba Cloud ACR`），
  就是既有凭据问题、与本次改动无关 —— 如实说明，别顺手去改发布流程。用户当时也明确说「不用管 ACR」。

## 推广

任何"全局替换版本号/标识符"的任务，动手前先问：
**这个 token 是否同时出现在「显示位」和「历史/记录位」？**
是 → 收窄到显示模式 + 用"历史位仍在/仍在原处"做断言。
**能自证没改错的脚本，比改得快的脚本值钱。**
