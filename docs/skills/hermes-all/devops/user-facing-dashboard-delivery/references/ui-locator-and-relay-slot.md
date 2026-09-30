# 界面定位指纹 + 单槽位中转语义（本轮尾部新增）

补 `SKILL.md` 的「第 0 步：先定位 artifact」——本轮在猜错 4 次之后，
靠下面两招才真正定位到用户看的是哪个界面。

---

## 一、神级判据：拿用户看到的**原话**去全库 + 全分支搜

用户描述里的**界面文案**（按钮字、提示语、状态词）是最强的指纹。

本轮用户说：**「app 上的 4060 一直显示『等待上报』」**

```bash
# ① 全库搜（排除 .git / site-packages）
grep -rln '等待上报' --include=*.html --include=*.py .
# ② 全分支搜
for b in main mac web; do git grep -l '等待上报' origin/$b; done
# ③ 线上页面也 curl 下来搜
curl -s https://datadrive.world/state-3d.html | grep -c '等待上报'
```

**结果：0 命中。**

### 这个 0 命中的含义（关键推论）
```
⇒ 这个页面**根本不在我的仓库里**（也不在任何分支、不在我已知的两个线上页面）
⇒ 它是**另一个 agent（@web / @xspace）做的**页面，它写好了 4060 硬件区，
   在**等 4060 往它那条数据通道上传数据**
⇒ 策略立刻改变：不是"改我的页面"，而是"**往它等的那条通道喂数据**"
```

### 反面教训
不能用「我改了 A、用户说还是没有」来推断「A 做错了」——
**用户看的可能压根不是 A**。必须先证明「他在看谁」，再动手。
本轮为此白发了 4 个版本（v5.15.1~v5.15.5）。

---

## 二、第三类界面：手机 APP = WebView 套壳（loadUrl 定位法）

「APP」除了「网页」和「桌面程序」，还可能是**打包好的安卓壳**——
它不加载本地文件，而是 `loadUrl(某个公网 URL)`。

```bash
# ① 找 APK 工程
find ~ -maxdepth 4 -name 'AndroidManifest.xml' -not -path '*/android-sdk/*'
# ② 看它加载哪个 URL —— 这一行就是"真正的界面"
grep -rn 'loadUrl' ~/<app_project> --include=*.java
# ③ 已构建的 APK
find ~ -maxdepth 4 -name '*.apk' -not -path '*/android-sdk/*'
```

本轮结果：
```
~/state3d_app/  (ZMAX-State3D.apk / ZMAX-3D-AOI.apk)
MainActivity.java: private static final String URL = "https://datadrive.world/state-3d.html";
```
→ **手机 APP 的"真正界面" = ECS 上的 `state-3d.html`**；
  本地源是 `tools/gui/state_3d_mobile.html`（标题一致、体积接近即可确认是同一份）。

### 由此得到的两个行动原则
1. **改那个 URL 上的页面 = 手机 APP 立即变，手机侧无需重装**（WebView 壳的特性，
   见技能 `android-webview-shell-apk`）
2. 但页面若在**别人的服务器**上（如 ECS），**改它需要服务器权限** ——
   这时己方唯一能做的是**喂数据**，并把「需要什么权限」明确抛给用户

### 「APP 看不到数据」的分层排查表
| 卡点 | 表现 | 你能做的 |
|---|---|---|
| 没喂数据 | 显示「等待上报 / 无数据」 | 往它的数据通道上传（不用改代码）|
| 页面没这个字段 | 有数据但无该卡片 | 改页面（需该文件的写权限）|
| 通道被顶掉 | 时有时无 | 见第三节 |
| 装的是旧版 | 界面里没有该区域 | 才轮到"发新版 + 让用户覆盖" |

---

## 三、「最新包覆盖」型中转：多端上传互相顶掉

中转只有 `POST /upload` + `GET /latest` 这种**单槽位**语义时
（即"只留最新一个包"，**不是按机器名分别存最新状态**），
**两端各自上传会互相覆盖** → 页面间歇性显示「某台机器 等待上报」。

本轮实测：
```
我 6s 一次、对方 30s 一次 → 连续 4 次读 /latest:
  第1次 machines=['4060','mac'] ✅
  第2次 machines=['mac']        ← 被对方的包顶掉
  第3次 machines=['4060','mac'] ✅
  第4次 machines=['4060','mac'] ✅
```

### 不能改服务端时的缓解（治标 —— 必须对用户说明是治标 + 给根治选项）
1. **提高己方上传频率**（如 6s 级），使己方包成为"最新"的概率占优
2. **在己方包里顺带转发对方的真实值** —— 从 `GET /latest` 读出对方那段**原样**并入自己的包，
   这样无论用户读到谁的包，两台机器都在：
   ```python
   mk, mv = fetch_other_latest()          # 读 /latest，找 backend=mps 的那台
   machines = {"4060": collect_mine()}
   if mk:
       machines[mk] = mv                  # ★ 只搬运、不改一个数字
   payload = {"meta": {"machines": list(machines.keys()), ...}, "data": {"machines": machines}}
   ```
   **红线：只搬运、不修改**对方的值；字段名/单位一律照抄，
   绝不"顺手补全"成编造值（那会变成生产视图里的假数据）。
3. 根治 = **服务端按机器名存槽位**（需要服务器权限）→ 明确向用户索要或请对方改

### 判断"要不要转发"的快速问句
```
这个包里多出来的字段，是不是别人采集、我只是搬运？
  → 是：可以带，但必须原样、且 meta 里标明 machines 全名单
  → 否（我自己算出来的）：绝不能带，那就是编造
```

---

## 四、上传频率的落地

- 6s 级频率**不适合 cron**（cron 最小 1 分钟粒度）→ 用**后台常驻进程**跑
  （`nohup`/后台 shell + `--watch 6`），并把它记进交付说明
- 低频（每 2 分钟）的才挂 `no_agent` cron（如写 GitHub raw JSON 那条链路）
- 两条链路可以并存：**cron 保"零安装网页"，常驻进程保"手机 APP 的中转槽位"**
