# 「自己会退」的常驻链必须托管 + 心跳可视

适用: 一条由「页面按钮 → 另一个端口的服务 → 可选的采集/发布子进程」组成的链路,
用户报「点了没反应」而每个服务 `is-active` 都正常。

## 症状
用户在网页上点「🧹 清除轨迹」没反应, 报「删除轨迹，无法删除历史轨迹」。
页面其他部分正常, 服务 `is-active` 也正常 —— 看不出哪坏了。

## 真根因(三条, 每一条都能单独造成“点了没反应”)
1. **按钮打的是另一个端口上的服务, 而它没有任何 unit**。页面JS 里 `var AR_PORT = 8797`,
   而 `ss -ltnp \| grep 8797` 是空的 —— 该服务是人工起一次、重启就没了。
   ⇒ 定式: **只要有“页面按钮 → 另一个服务”这条边, 那个服务就必须有 systemd 单元**
   (除非它是用户的 GUI, 那属另一回事)。
2. **`--seconds` 型脚本到点自己 exit**, 而且没人托管:
   录制器 `--seconds 3600`、发布器 `--loop --seconds 5400` 都是“定时炸弹”。
   ⇒ 单元给 `Restart=always`, 并把 `--seconds` 抬到 12~24h(重启本身也要带代价, 别让它天天退)。
3. **`systemctl stop` 杀不掉 `docker exec` 起的容器内进程**: 停掉的只是宿主机上的客户端,
   容器里 python 还挂在 containerd-shim 下活着 ⇒ 再 start 就会出现**两个实例写同一个文件**。
   ⇒ 单元加 `ExecStop=-/usr/bin/docker exec <c> pkill -f <脚本>[.]py`。

## 两个验证细节
- **`pkill -f` 的模式不能出现在自己这条命令行里** —— `docker exec X bash -lc 'pkill -9 -f foo.py; rm -f Y'`
  会把自己那条 bash 先 SIGKILL, 后面的 `rm` **根本不执行**(实测: 还以为文件删了, 实际还在,
  排查时得到错误结论)。模式写 `foo[.]py` 包在单引号里。
- **判“链还活着”看产物文件 mtime, 不看进程**: 录制器写 `/tmp/live_trace.json`(容器内),
  发布器每 1.5s 把它落到 `reports/moveit/live_trace.json`(宿主机) —— 后者的 mtime 就是整条链的心跳。
  ⇒ 把它**下发到页面**: “轨迹: 开 · 已录 N 点 · ⚠️ 轨迹链已停 M 分钟”。

## 「删除」按钮的真实语义(用户会把它当“删了”)
只改“清除线/开关”而不动被渲染的数据 ⇒ 用户看到的坐标一点不变 ⇒ 必然被判“删不掉”。
完整定式(服务端直接改规格落盘 + 反向按钮 + 页面写明作用域)见 `sim-real-scene-overlay`。

## 单元文件放仓库, 不要只活在 /etc
`tools/systemd/*.service` 是仓库里的真源, 部署时 `sudo cp tools/systemd/<u>.service /etc/systemd/system/`
再 `daemon-reload`; 并在 `docs/skills/xspace/systemd-boot-services/references/local-units.md`
补一行(单元 / 形态 / 干什么 / 核验点), 否则下一个人(或下一个我)不知道这台机器上有哪些常驻。

## 自检清单(交付这类故障修复前)
1. `ss -ltnp \| grep <按钮打的端口>` —— 服务在不在;
2. 真浏览器点按钮, 读 DOM 角标 + 回后端查状态是否真的变了(**不只看 toast**);
3. 如果动作的可见结果依赖下游某一环, **把下游杀掉再点一次**, 看用户到底能不能得到他要的结果;
4. 补心跳字段并在页面上显示, 下次失败要能“一眼看出来”。
