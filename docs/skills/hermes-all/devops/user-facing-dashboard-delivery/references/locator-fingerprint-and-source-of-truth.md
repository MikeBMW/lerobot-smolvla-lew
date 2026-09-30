# 定位指纹修正 + 数据源真相 + git 引用陷阱（补 SKILL.md「第 0 步」与

`references/ui-locator-and-relay-slot.md`）

> ⚠️ 本文**修正** `ui-locator-and-relay-slot.md` 第一节的错误结论。
> 那一节写的是「搜『等待上报』0 命中 ⇒ 页面不在我仓库 ⇒ 是别的 agent 做的页面」——
> **这个推论是错的**，它让我去猜别人维护的接口，又白烧了好几轮。
> 真相：那句文案**是我自己写的**，只是我在文件里写的是「等待 **4060** 上报」（中间夹了字），
> 拿整句当锚点自然搜不到。

---

## 一、用户引文 0 命中时的正确顺序（先怀疑自己）

```bash
# ① 关键词**拆开**搜，不要整句 ——「等待」「上报」分别搜再与
grep -rn '等待' --include=*.html --include=*.py . | grep -E '上报|上传'
# ② 全仓 + 全分支（含 tools/ docs/，别只搜根目录）
git grep -n '等待' $(git branch -r) 2>/dev/null | head
# ③ ★ 连"我自己的占位文案"一起搜 —— 占位串几乎总在 UI 里
grep -rn '未上报\|等待上报\|等待上传\|暂无数据\|未检测到' --include=*.html .
```

**判据**：
- 命中**任何一个你自己的文件** ⇒ 那就是你的界面，直接改它；**别去猜别人的接口**
- ①②③ 都 0 命中 ⇒ 才转向"这是别人做的页面 / 需要对方权限"

**最快的一招**：让用户**粘原文**。本轮他贴出
「🍎 Mac（小芳·备份端） · MPS / 等待上报 / Mac 未上报（小芳需跑 …）」——
一次就锁定是我的卡，而且这几行同时暴露了真正的 bug（见第二节）。

---

## 二、★ 读错数据源 = 永远「等待上报」（本轮真 bug）

**这台机器的数据由它自己上报到哪里，就要去哪里读。**
不要假设所有节点都会汇到你本机的桥。

本轮实测：
```
本机 DDS 桥 `/…/dds_latest.json`  → nodes = ['4060']        ← 我读这里（❌ 没有 Mac）
ECS relay `/api/relay/latest`     → machines = ['4060','mac'] ← 小芳真正上报的地方（✅）
⇒ Mac 永远显示"等待上报"（不是没数据，是我读错了地方）
```

**先确认"对方的数据到底在哪"——两个候选来源都打一遍，别只看一个**：
```bash
python3 -c "import json;print(list(json.load(open('/…/dds_latest.json'))['nodes']))"
curl -s https://<relay>/api/relay/latest \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(list(d['data']['machines']))"
```

**修法两条**：
1. 改读对方**真实的落点**（本轮：从本机 DDS 桥改读 ECS relay）
2. 读取端**加重试** —— 中转是"最新包覆盖"型，单次可能抓到不含对方的包 → 写入 `null`。
   本轮给 `mac_section()` 加了 **6 次重试**才稳定（否则页面上"有时有、有时没有"）。

**通用判据**：`某台机器 等待上报` 有三种成因，必须先分辨：
| 成因 | 分辨方法 | 修法 |
|---|---|---|
| 没上报 | 对方那台机器上有没有在跑上报进程 | 让对方跑/起服务 |
| **读错源** | 换一个源读，看数据在不在 | 改读取端（本节）|
| 被顶掉 | 连读 N 次，看是否时有时无 | 见 `ui-locator-and-relay-slot.md` 第三节 |

---

## 三、★ `git show <branch>:` 读的是**本地引用** —— 从 detached worktree 推完必须更新本地

本轮最隐蔽的一次"推了但没生效"：

```bash
# 我在 detached worktree 里把修复推到了远端
git worktree add -q -f --detach /tmp/wt origin/main
cd /tmp/wt && git commit … && git push origin HEAD:main     # ✅ 推送成功
# 但主工作区的**本地 main 引用没动**，而我的脚本读的是:
git show main:tools/<tool>.py > …                            # ❌ 拿到的还是旧版本
# ⇒ 日志显示"已推送"，但跑起来的行为仍是旧的（静默失败，最难查）
```

**修法**：
```bash
git fetch origin main && git branch -f main origin/main      # 同步本地引用
# ★ 更稳: 脚本一律读远端引用, 不要读本地分支名
sed -i 's/git -C "$REPO" show main:/git -C "$REPO" show origin\/main:/g' <脚本>
```
**判据**：验证"修复真的生效"时，别只看 `git log`/推送输出，
要**在消费者那一侧回读实际内容**：
```bash
git show origin/main:<file> | grep -c '<你新加的标志串>'     # 0 = 没生效
```

---

## 四、其它本轮踩到的静默坑（简记）

| 坑 | 现象 | 修法 |
|---|---|---|
| `git stash -u` 吞掉自己的新脚本 | 脚本"消失"，后续 `git show main:` 报 `can't open file` | `git stash list` 找回；新脚本**落到仓库外**（如 `~/`）再被服务引用 |
| 跨分支的 venv 是对方平台的 | `gui-venv311/bin/python` 指向 `/Users/xxx/.venv/…` | 跨分支跑脚本用**系统 python3**，或让脚本用绝对路径 |
| 中转「最新包覆盖」多端互顶 | 连读时有时无 | 提高己方频率 + **原样转发**对方值（红线：只搬运不改数字）|
| `data/` 目录 git 里带小文件挡住软链 | `ln -sfn` 静默不生效，仍读不到数据集 | 先 `mv data data_bak_$(date +%s)` 再软链（**不删**）|
