# Z-MAX 工程路径整治 · 全局一致性 (2026-09-29)

老倪: 「需要将这几个文件夹整合成一个工程 … 现在就要做好工程一致性工作, 把路径统一了, 所有代码都统一到
zmax 工程路径里 … 以后推送代码、调试代码都到 /home/ubuntu/zmax … 文件夹太多不好管理, 你来精简;
但要保证以前的环境变量、工作路径可以兼容 … 同时要构想好全局数据空间, 所有数据都要被观察。」

## 1. 测绘(实测, 2026-09-29 18:2x)

### 1.1 三棵树同属一个仓库 `MikeBMW/lerobot-smolvla-lew`

| 路径 | 分支 | 大小 | 说明 |
|---|---|---|---|
| `/home/ubuntu/zmax` | **mac-hw** | 53G | 同时是 **.git 本体所在处**; 落后 origin/main 1753 / 领先 536; 内有 gui-venv311 等 venv 与数据 |
| `/home/ubuntu/zmax` → 现为软链 | main | 1.5G | 原 main 工作树, 本次正名为 `/home/ubuntu/zmax` |
| `/home/ubuntu/zmax_train` | detached | 7.4G | 训练侧工作树(游离 HEAD) |

### 1.2 仓库外的代码(必须收口的"两个地方")

* `/home/ubuntu/zmax/dds_publisher.py` / `zmax_dds_ss_daemon.py` / `zmax_dds_aggregator.py` / `zmax_dds_ss_verify.py`
* `/home/ubuntu/zmax/dds/{zmax_node.py, zmax_types.py, ss_types.py, cyclonedds_unicast.xml(0 字节)}`
* `/home/ubuntu/zmax_hw_uploader.py` + 根目录其它脚本 15 个(`dl_*.sh`/`gw_*.sh`/`chain_v2.sh`/`prep_reacher.sh`/…)
* `ss_bridge_node.py`: main 树里**有**, mac-hw 树里**没有**(与 dds_link_bus.py 相反的方向)

### 1.3 引用旧路径的活体(改动前)

* systemd(系统级): `zmax-dds-pub` · `zmax-dds-ss` · `zmax-dds-agg` · `zmax-hw-upload` · `ss-bridge`(挂 mac-hw/tools)
  · `ss-local-infer`/`zmax-dataspaces-*`/`sam3-seg` 等已指 zmax_rel
* systemd(用户级): `zmax-studio`(WorkingDirectory=/home/ubuntu/zmax/tools/gui, 且 `gui-venv311` 是 → mac-hw 树)
* cron: `auto_loop.py` 跑在 mac-hw 树 · `publish_live_url.py`/`tunnel_keepalive.sh` 指 zmax_rel
* `~/.bashrc` / `~/.profile`: **无**旧路径(环境变量侧风险低)

## 2. 目标布局(单一工程根 + 兼容软链)

```
/home/ubuntu/zmax/                 ← ★ 唯一工程根(分支 main): 写代码/调试/提交/推送都在这里
  src/lerobot/{dataspace,policies,engineering,verification}/   ← 逻辑代码(含 DDS 类型与状态灯)
  tools/dds/{publisher,ss_daemon,aggregator,ss_verify}.py      ← DDS 本体(本次收口)
  tools/gui/  tools/systemd/*.service  dds/{zmax_node,zmax_types,ss_types}.py  dds/cyclonedds_unicast.template.xml
  docs/design/  reports/(证据)  flows/  data/

/home/ubuntu/zmax         → 软链 → /home/ubuntu/zmax      (旧路径兼容)
/home/ubuntu/zmax/dds         → 软链 → /home/ubuntu/zmax/dds   (旧 import 路径兼容)
/home/ubuntu/zmax/dds_*.py    → 软链 → tools/dds/*.py          (旧脚本路径兼容)
/home/ubuntu/zmax_hw_uploader.py → 软链 → tools/hw_uploader.py
```

**兼容原则: 旧路径一律保留软链, 不删不改名; 新写的代码只认 `/home/ubuntu/zmax`(可用 `ZMAX_REPO` 覆盖)。**

## 3. 本次已完成(带证据)

| # | 动作 | 证据 |
|---|---|---|
| 1 | main 工作树正名 `/home/ubuntu/zmax` → `/home/ubuntu/zmax` | `git worktree list` 显示 `/home/ubuntu/zmax 69b8a2d9 [main]`; 旧名软链保留 |
| 2 | DDS 四个脚本 + 三个类型文件收进工程 | `tools/dds/*.py`(编译通过) · `dds/{zmax_node,zmax_types,ss_types}.py` 与仓库外逐文件 md5 一致 |
| 3 | 单播配置从 mac-hw 树取回并**改名 template** | `dds/cyclonedds_unicast.template.xml`(2501B, 实测可用版); 不带 `--cfg` ⇒ 保持当前多播发现(=实测可用状态) |
| 4 | 脚本内路径改单一工程根 | publisher/aggregator/ss_verify/ss_daemon 共 12 处; `ss_daemon.REPO` 由 **误指 mac-hw** 改为 `ZMAX_REPO` |
| 5 | 三个 DDS unit + `zmax-hw-upload` + `ss-bridge` + 用户级 `zmax-studio` 全部改指 zmax | `systemctl cat` 实测; 全部 `active`; ss-bridge 容器 `桥节点就绪` |
| 6 | 旧路径全部留软链 | `/home/ubuntu/zmax/dds` 下 `import zmax_node` 实测 OK(13 个类型) |
| 7 | cron 正名(备份留存) | 备份 `zmax_data/backups/crontab_20260929_pre_consolidation.bak`; 现无一行引用旧路径 |
| 8 | unit 进版本库 | `tools/systemd/{zmax-dds-pub,zmax-dds-ss,zmax-dds-agg,zmax-hw-upload,ss-bridge}.service` + `zmax-studio.service.user` |

⚠ 踩坑(记下来): `write_file` 对**已存在且本任务未读过**的文件会拒绝写入(返回错误但外层循环没检查),
导致 `ss-bridge.service` 仍是旧挂载 ⇒ 容器起不来。**改 unit 后必须 `systemctl cat` 实测内容, 不能只看"写成功"。**

## 4. 观测覆盖清单(「所有数据都要被观察」的现状与计划)

观测三层: ① 每条 topic 一盏状态灯(绿/红/黄/黑) ② 探针落 `live.json`+`trace.jsonl`(2s) ③ 闭环九环证据(`loop.json`, 15s)。
"量产不序列化" ⇒ 数据不常驻总线, 但**工程上随时可切档/回灌**探测。

| 数据源 | 是什么 | 现在能被观察吗 | 落点 |
|---|---|---|---|
| 硬件状态(4060 GPU/内存/温度/盘) | 系统状态 | ✅ topic `zmax/hw_state` 0.33Hz | live.json + 状态灯 |
| 心跳 | 进程活着 | ✅ `zmax/heartbeat` | 同上 |
| 训练进度 | 训练状态 | ✅ `zmax/train_prog`(有话题, 暂无训练) | 同上 |
| 真机状态/动作(tcp_pose 50Hz / ss_state / ss_action) | 输入输出信号 | ⚠ 话题在, 数据源断了(Orin 不可达) | 状态灯=黑(无信号) |
| 标定(手眼/TCP/闸门) | 质量门输入 | ✅ `zmax/ss_calib`(当前 🔴 valid=0 真故障) | 状态灯 + 规则 |
| 自检诊断 | 系统健康 | ✅ `zmax/ss_diag` | 同上 |
| 画布节点间连线(182 条) | 节点间数据 | ✅ `zmax/link_value`(工程回灌可随时点亮全图) | 状态灯墙 74 模块 |
| 部署指令 | 控制输入 | ⚠ 话题 `deploy_cmd` 无发布端(S7 只能走审计台账) | 待补发布端 |
| 自测/标定用例 | 验证 | ✅ `ss_test`(test 档) | 同上 |
| 记忆层/宏观层 | 认知状态 | ✅ `ss_macro`(需档位) | 同上 |
| 数据集/训练产物/模型 sha | 交付物 | ⚠ 只有文件与 `loop.json` 证据, 无 topic | 闭环 S3/S5/S6 |
| AOI 检测结果(金手指/表面) | 产线质量 | ❌ 只有 HTTP 端点 + 审计文件 | **待加 topic** |
| ECS relay / 工位总览 / 网页 | 远程状态 | ❌ 只有 HTTP | **待加 topic**(只读转发) |
| Orin 侧遥测 | 边缘状态 | ⚠ 依赖产线网卡; 政策: 只读转发, 禁装程序 | 同上 |
| 日志/异常 | 运行健康 | ❌ 仅文件 | 计划: 摘要上总线(只发计数/最近一条) |

## 5. 剩余待办(编号; 带 ★ 的需要你点头)

1. ★ **mac-hw 工作树怎么收**: 它比 main 领先 536 提交、还有 9 个未提交改动。
   两条路: (a) 把 9 个改动提交进 mac-hw 分支并推送, 该树移到 `/home/ubuntu/zmax/.worktrees/mac-hw`
   (顶层少一个文件夹, 旧路径留软链); (b) 逐目录比对把 main 缺的代码搬进 main(今天已搬 2 个文件:
   `dds_link_bus.py`、单播配置), 之后该树只作历史保留。**建议 (a)+(b) 并行: 先提交保住改动, 再按需搬文件。**
2. ★ **`zmax_train`(detached, 7.4G)与 `INTACT-JEPA`(独立仓库, 11G)**: 是否并入/归档?
3. 根目录 15 个散落脚本(`dl_*.sh`/`gw_*.sh`/`chain_v2.sh`/`prep_reacher.sh`/`run_official_eval.sh` …)
   移进 `tools/oneoff/` 并留软链(纯搬移, 不影响运行)。
4. `gui-venv311` 仍指向 mac-hw 树(控制台在用它): 处理完 §5.1 后改为指向工程根下的 venv 或统一 venv 目录。
5. `deploy_cmd` 补发布端(闭环 S7 才有真实指令流)。
6. AOI/ECS/网页/日志 四类数据加 topic(见 §4 表末四行), 让"所有数据都被观察"闭环。
7. `auto_loop.py` 守护修复(它在 mac-hw 树里跑、配置路径失效、且把 DDS 硬件包当新数据; 训练自 09-16 未成功) —— 闭环 S4 的真拦路虎。
