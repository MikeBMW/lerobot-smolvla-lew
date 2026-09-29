# 修: /overlay「删除轨迹」删不掉历史轨迹 (2026-09-29)

老倪报: `http://10.163.146.78:8791/overlay` → 点删除/清除轨迹, **历史轨迹删不掉**。

## 查到的三条真根因(每条都能单独让按钮变哑巴)
1. **按钮打的不是本页的服务**: `/overlay` 的 `▶显示 / ⏸隐藏 / 🧹清除 / 📜全部历史` 在
   `tools/web/scene-overlay.html` 里写死 `var AR_PORT = 8797`, 打的是 **AR 轨迹台**;
   而 `ss -ltnp | grep 8797` **空** —— 这个服务当时根本没在跑, 因为它**没有任何 systemd 单元**
   (人工起一次, 重启即失)。页面只在角标写「轨迹台 :8797 连不上」, 不注意看不出来。
2. **「清除」只改了清除线, 真删折线靠下一轮发布**: `/api/traj/clear` 只做 `set_state(baseline_n=n)`,
   真正把折线挪出叠加规格的是 `live_trace_publisher.py`; 而它要读**容器内录制器**落的
   `/tmp/live_trace.json`, 录制器一停它只打一行「还没有轨迹数据(录制器起了吗?)」就退出。
   ⇒ 规格里那条折线一个像素不动 = 用户眼里"点了没用"。(实测复现: 删掉容器内该文件后点清除,
   发布器确实报`还没有轨迹数据`, 而 `in_spec.trace` 仍是旧的 1076 点。)
3. **整条采集链自己退了没人管**: 录制器 `--seconds 3600`、发布器 `--seconds 5400` 到点自退,
   且都是人工起的。实测停机 8 小时后页面还显示「已录 26479 点」, 画面上一直重画那条
   **13:46 冻结的旧轨迹** —— 看起来像实时的。

## 修法
| 处 | 改动 |
|---|---|
| `tools/tcp_ar_server.py` | ① `clear` 在服务侧**直接** `traj_display.strip_origins(["trace"])` 把折线挪出规格(可恢复缓存), 不再依赖发布器; ② `baseline(n=0)`(全部历史)反向 `restore_origins` 兜底; ③ `/api/traj/state` 新增 `trace_age_s`(发布产物文件龄=整条链的心跳) |
| `tools/live_trace_publisher.py` | 新增 `--stale-s`(默认 120s)**停摆守卫**: 源龄超阈值就把画面上的轨迹撤掉, 不把冻结的旧轨迹当实时画; 并打印「⚠️ 轨迹源已停 N 分钟」 |
| `tools/web/scene-overlay.html` | ① 轨迹台连不上时角标变红写「⚠️ 轨迹台(:8797) 未运行 —— 轨迹按钮点了没反应」并**禁用四个按钮**; ② 链停 >60s 时角标显示「⚠️ 轨迹链已停 N 分钟」(读 `trace_age_s`) |
| `tools/traj_rec_up.sh`(新) | 录制器的启动壳: 等容器→按 200MB 轮转容器内 jsonl→**把清除线归 0**→起录制器。归 0 是因为录制器重启后它自己的计数 n 从 0 重来, 而清除线按 n 记, 不归 0 会把画面上的轨迹**永久夹成 1 个点** |
| `tools/systemd/zmax-traj-{ar,rec,pub}.service`(新) | 三件套全部 systemd 托管(仓库 tools/systemd/ 是真源); rec 带 `ExecStop=docker exec … pkill`(实测 `systemctl stop` 杀不掉容器内进程) |

## 实测验收(都是真跑的)
- `ss -ltnp` → `0.0.0.0:8797` 有进程; `/api/traj/state` 回 `ok:true`。
- 链活了: 发布器日志 `[21:21:13] 轨迹 N 点(原始 …, 清除线 0, 抽稀后 N) → cameras.arm origin=trace`;
  `reports/moveit/live_trace.json` mtime 每 1.5s 滚(心跳)。
- **真浏览器**打开 `/overlay` 点「🧹 清除轨迹」: 角标 `已录 265 点`、`baseline_n` 258、四个按钮均可用;
  点「📜 全部历史」→ 清除线回 0、`in_spec.trace` 27 点。
- **复现原故障**(容器内删掉 `/tmp/live_trace.json`, 即录制器从没起来过)再点清除:
  发布器报 `还没有轨迹数据`, **兜底直连 `{'moved': 1}`**, `in_spec` 里 trace **消失**(只剩 plan 航路) —— 这正是老倪要的效果。
- 叠加图黄像素 158 → 68(余下的是清除线之后新走过的点, 属正常)。

## 红线
未下发任何真机动作; 只动叠加层与轨迹显示状态, **录制历史数据一个字节没删**
(`/tmp/live_motion.jsonl` 50Hz 配对数据保留, 那是后面拟合 MoveIt 零位偏移要用的)。
