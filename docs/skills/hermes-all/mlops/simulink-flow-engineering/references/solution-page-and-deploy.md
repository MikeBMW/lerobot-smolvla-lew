# Z700 方案分页 + ECS 部署 (2026-08-12)

配套产物: 方案介绍分页(solution.html)与画布模型对齐 + PDF 下载。

## 方案与画布对齐铁律 (老倪纠正)

方案网页/PDF 里的模型描述必须与画布节点一一对应:
- 感知链写全: 🎯 YOLO 3D → 📐 2D→3D 解算 → 🔌 State Adapter ← 📍 Marker 触觉跟踪 → 43D
- 状态机 6 阶段(画布 dual_brain 是 6 动作节点): 接近→抓取→抬起→转移→插入→完成
  (记忆里的 "8 状态机 接近对位下降抓取..." 是完整版, 画布精简为 6 — 以画布为准)
- 双脑: LeftBrainMLP + RightBrainWM
改画布后必须同步更新 solution.md → 重新生成 PDF → 重新部署。

## v1.1 架构版 (2026-08-12 老倪: "方案介绍应该主要讲技术架构" + "每个节点是干什么的都要讲")

- 页面以**技术架构为主线**, 分 5 组把画布 20 个功能节点逐个讲职责(节点名=画布名, 加 role 标签):
  - 感知链(5): 📦 metaworld_peg(数据源) → 🎯 YOLO 3D(检测, mAP .994) → 📐 2D→3D 解算 → 📍 Marker 触觉跟踪(4D) → 🔌 State Adapter(39+4=43D)
  - 双脑(4): 📊 43D obs 输入(接口) / 🧠 左脑 LeftBrainMLP(动作生成器, 偏置接近) / 🧠 右脑 RightBrainWM(世界模型, contact 只喂状态机) / ❖ 接触判定(d<0.06 且 contact>0.5)
  - 状态机(7): ◉ LeftRightPolicy(策略总控) + 6 阶段卡(接近/抓取/抬起/转移/插入/完成 各带参数如夹持0.6/+8cm/容差5cm)
  - 训练交付(4): 🚀 训练 / ▶ 生成插拔视频 / 📄 PDF 报告 / 🌐 方案介绍
- 节点卡带 `.src` 源码路径标注(src/lerobot/policies/yolo_3d/ 或 left_right/)— 与右键"打开源代码"映射一致
- 成绩对比表: 双脑+状态机 8/8·7/8 / 官方专家 7/8(85% 锚点不排名) / MLP蒸馏 6/10·3/10 / 视觉BC·纯状态机 0/8
- 场景表降级为"简述 · 详见协议"(架构才是重点, 场景协议里有)
- 生成链路: solution.md → `lerobot-smolvla-lew/.venv/bin/python tools/gui/docs_pdf.py solution.md "Z700-方案介绍.pdf"` → scp 部署

## 文件位置

- 网站仓库: /home/xspace/zmax-website/
- 页面: zmax-website/solution.html(深色卡片风格, 顶部「📄 下载 PDF」+「← 返回主页」)
- 源文档: zmax-website/solution.md(可重新生成 PDF)
- PDF 工具: lerobot-smolvla-lew/tools/gui/docs_pdf.py(md→PDF, venv 跑)

## ECS 部署 (git push 不自动部署!)

**git push 到 GitHub 不会自动上线(线上 404)** — 必须手动 scp:

```bash
# 凭据在 zmax-website/orin_stream.sh 与 deploy/deploy.sh: ECS_PASS=Nix19789
cd /home/xspace/zmax-website
sshpass -p 'Nix19789' scp -o StrictHostKeyChecking=no solution.html "Z700-方案介绍.pdf" \
  root@39.102.211.79:/www/wwwroot/datadrive.world/
sshpass -p 'Nix19789' ssh -o StrictHostKeyChecking=no root@39.102.211.79 \
  "chmod 644 /www/wwwroot/datadrive.world/solution.html '/www/wwwroot/datadrive.world/Z700-方案介绍.pdf'"
```

注意:
- ECS = root@39.102.211.79:22, web 根 /www/wwwroot/datadrive.world/(宝塔 nginx)
- sshpass 直接 ssh 之前遇到 Permission denied — 用 deploy.sh 同款 `sshpass -p '...' ssh -o StrictHostKeyChecking=no` 就通(参数顺序差异)
- 中文文件名 PDF 在 scp/curl 里要 URL 编码: Z700-%E6%96%B9%E6%A1%88%E4%BB%8B%E7%BB%8D.pdf
- 下载按钮: `<a href="/Z700-方案介绍.pdf" download>📄 下载 PDF</a>`
- .gitignore 忽略 pdf(交付件不入库, Git 精简铁律)— 页面+md 入库, PDF 只部署线上

## 验证

```bash
curl -s --max-time 8 "https://datadrive.world/solution.html" | grep -oE "State Adapter|6 阶段执行|下载 PDF"
curl -s -o /dev/null -w "%{http_code}\n" "https://datadrive.world/Z700-%E6%96%B9%E6%A1%88%E4%BB%8B%E7%BB%8D.pdf"  # 200
curl -s -o /dev/null -w "%{http_code}\n" "https://datadrive.world/"  # 主页 200 不受影响
```
