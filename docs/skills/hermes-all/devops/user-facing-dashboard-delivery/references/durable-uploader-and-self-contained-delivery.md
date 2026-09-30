# 上传进程的常驻化 + 目标页面能力预检 + 自包含交付（本轮尾部新增）

本文补 `SKILL.md` 与 `references/ui-locator-and-relay-slot.md`。
其中**第一节修正了 ui-locator-and-relay-slot.md 第四节里的错误做法**（那里写的是
"用 nohup/后台 shell 跑秒级上传"——本轮实测该做法会导致数据静默中断，必须改成 systemd 常驻）。

---

## 一、★ 秒级上传必须做成常驻服务（修正旧文档）

### 错误做法及其三种死法
```bash
nohup python3 tools/hw_upload_relay.py --watch 6 &     # ← 不要这样
```
1. **临时进程随会话/父 shell 一起死** → 用户看到的就是"停了 / 等待上报"
2. 脚本放在**仓库里**，而你会切分支、或用 `git stash -u` → 文件被切走/吞进 stash
   （本轮脚本"消失"过两次；systemd 日志里刷满
   `can't open file '/…/tools/hw_upload_relay.py': [Errno 2] No such file or directory`）
3. 没有自启 → 机器重启后彻底静默，而你以为它还在跑

### 正确做法
```ini
# /etc/systemd/system/zmax-hw-upload.service
[Unit]
Description=Z-MAX hw uploader (relay)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu
ExecStart=/usr/bin/python3 /home/ubuntu/zmax_hw_uploader.py --watch 3   # ★ 仓库外稳定路径
Restart=always
RestartSec=5
StandardOutput=append:/var/log/zmax-hw-upload.log
StandardError=append:/var/log/zmax-hw-upload.log
[Install]
WantedBy=multi-user.target
```
```bash
# ① 先把脚本落到仓库外（关键！切分支不会动它）
git show main:tools/hw_upload_relay.py > /home/ubuntu/zmax_hw_uploader.py
# ② 装服务
sudo cp /tmp/zmax-hw-upload.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now zmax-hw-upload
# ③ 三连验证（缺一条都可能"以为在跑其实没跑"）
systemctl is-active  zmax-hw-upload      # active
systemctl is-enabled zmax-hw-upload      # enabled（开机自启）
tail -3 /var/log/zmax-hw-upload.log      # 真有时间戳在推进
```

### 频率与进程形态的对应关系
| 需求频率 | 用什么 | 理由 |
|---|---|---|
| 秒级（3~6s，抢中转槽位） | **systemd 常驻服务** | cron 最小 1 分钟粒度，做不到；临时进程会死 |
| 分钟级（2 分钟，刷公网 JSON） | `no_agent` cron | 够用且自带日志/告警 |

两条链路**可以并存**：cron 保"零安装网页"的 raw JSON，常驻服务保"中转槽位"的秒级新鲜度。
交付说明里要写明"已做成开机自启服务"，用户才知道它不依赖你的会话。

---

## 二、★ 动手前先验证「目标页面到底有没有这个能力」

本轮最大的时间浪费：为一个**根本不具备该能力**的页面反复喂数据。

```bash
curl -s https://<host>/<page>.html > /tmp/p.html
grep -cE 'vram|显存|gpu|利用率|hardware' /tmp/p.html   # 0 = 页面里连显示代码都没有
grep -oE '[a-z_]+\.(php|json)' /tmp/p.html | sort -u   # 它真正读的数据源有哪些
curl -s https://<host>/<that>.json | head -c 400       # 那个数据源里有哪些字段
```

本轮实测：
- 页面里 `vram` / `显存` / `gpu` 命中 **0**
- 它读的 `ss3d_live.json` 只有 `{run_id, playing, i, n, done, dist, beat}`
  —— **纯运控状态，无任何硬件字段**

**推论（省下几小时）**：页面**没有渲染代码** + 数据源**没有该字段**
⇒ **无论往任何通道上传多少数据，这个页面都不可能显示它。**

**判据/止损**：喂数据一轮后用户仍说"等待上报" → **先做这个能力预检**，
不要再加大上传频率、不要再发版本。出路只有两条：
1. 拿到该页面的**写权限**（直接加卡片）
2. **自己交付一个能显示的东西**（见第三节）

---

## 三、★ 终局：目标界面不在你手上 → 自己交付一个「内嵌页面」的 APP

**触发条件（三条同时成立就走这条，别再修别人的页面）**：
1. 目标页面在**别人的服务器**上（你只有读权限，改要密码）
2. 已试过喂数据 + 发版本，用户仍在催（"还是没有" / "快点解决"）
3. 用户要的是**某台特定机器的实时数据**（数据源在你这、展示端不在你这）

**做法（本轮全流程验证通过）**：
```
① 写一张自包含的移动端页面，数据源指向**你能写的公网 JSON**
   （自己的分支 raw.githubusercontent.com/<owner>/<repo>/<branch>/<path>.json，用 cron 保新鲜）
   页面里做多源回退: [raw.githubusercontent, jsdelivr 镜像] —— 单域名被限流/被墙不影响可用性
② 放进 Android 工程: app/src/main/assets/index.html
③ MainActivity: webView.loadUrl("file:///android_asset/index.html")
   （不是 loadUrl(公网URL) —— 页面在包里，不依赖任何托管/权限/对方配合）
④ 沿用既有工程的图标(5 密度)与签名参数，按 skill `android-webview-shell-apk` 的 CLI 流程打包
```

**共存技巧**：换 `package`（如 `com.zmax.state3d` → `com.zmax.hw`）+ 换 `android:label`
→ 新 APP 与用户旧 APP **并存**，不用卸载旧的（旧 keystore 只与旧包名绑定）。
签名密码别猜：**去既有工程的 build 脚本里 grep**（`grep -nE 'storepass|ks-pass' *.sh`）。

**打包后必须自证（三条，缺一条都可能交付一个装不上/显示不出来的包）**：
```bash
aapt2 dump badging X.apk | grep -E '^package:|launchable-activity|application-label'
unzip -l X.apk | grep -c 'assets/index.html'     # ★ 页面真的进包了（=1）
node -e "fetch('<公网JSON>').then(r=>r.json()).then(d=>console.log(d.hardware.vram_used_mb))"
#   ↑ 模拟 APP 内 fetch，证明它真能拿到目标字段（而不是"理论上能"）
```

**交付话术**：直接把 `.apk` 当附件发给用户（飞书 `MEDIA:/abs/path.apk`），
附一句"提示未知来源时选允许"；**并同时给出根治选项**
（"更好的办法 = 把那个页面的写权限给我，我直接把卡片加进去"）——
**给绕路方案时必须同时给根治方案**，否则等于把技术债留给用户。

**为什么比继续修别人的页面强**：修别人的页 = 依赖 ① 权限 ② 对方配合 ③ 用户手动更新，
每多一环多一次失败机会；自包含 APK = **你自己能验完的闭环**，交付那一刻就确定能显示。

---

## 四、用户催促下的行为纪律（本轮教训）

用户连说多次"还是没有 / 快点解决"时，**唯一正确动作是换路径，不是加大力度重复**：
- ❌ 不要：再发一版、再解释一遍原理、再问一次"你看到的是哪个界面"
- ✅ 要：跑一次**能力预检**（第二节）→ 若页面不具备能力，**立刻转自包含交付**（第三节）
- ✅ 汇报时**先给可安装/可打开的东西**，再讲根因；用户要的是结果不是推理过程
- ✅ 每一轮都必须产出**一个用户能自己验证的动作或文件**（链接 / 附件 / 一条 curl）
