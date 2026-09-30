# 容器重建恢复 + 会话取证重建 (完整版 runbook, 2026-08-18 实测)

> 本文件是完整版; 同名早期版 references/container-recovery.md 是精简版, 内容被本文件覆盖(可删)。

## ⚠️ 首要教训

**容器重建 = 未 commit/push 的代码改动全部丢失** (08-18 实测: 当晚「🧮 状态空间」画布+按钮+六层源码模块整晚工作全丢, 因为没 push; 老倪追问"状态空间怎么没了")。
**纪律: 功能做完当天必须 commit + push** (CICD 节奏 commit→push→tag, 不许攒到收工)。

## 一、恢复步骤

1. **clone 大仓库** (605MB, 5-10 分钟):
   ```bash
   cd /root && git clone --depth 50 https://github.com/MikeBMW/lerobot-smolvla-lew.git
   ```
   background=true + notify_on_complete, 别干等。clone 失败留残缺 .git (branch master 无 commit) → `rm -rf` 重来。
   ⚠️ `git clone | tail -2; echo RC=$?` 拿的是 tail 的退出码, 掩盖 clone 失败 — 用 `${PIPESTATUS[0]}`。

2. **重建 git 配置** (容器重建后全丢):
   ```bash
   git config --global user.name "MikeNi"
   git config --global user.email "mikeni@zmax.local"
   git config --global credential.helper store
   TOKEN=$(grep -oP '(?<=^GITHUB_TOKEN=).*' /root/.hermes/.env | head -1)
   printf 'https://MikeBMW:%s@github.com\n' "$TOKEN" > /root/.git-credentials
   chmod 600 /root/.git-credentials
   ```
   token 在 `~/.hermes/.env` 的 `GITHUB_TOKEN=` (40 字符)。

3. **重建运行环境** (venv/字体/系统库全丢):
   ```bash
   /root/.hermes/bin/uv venv /root/gui-venv --python /usr/bin/python3
   /root/.hermes/bin/uv pip install --python /root/gui-venv/bin/python PyQt5 numpy grpcio protobuf
   apt-get install -y libxcb-xinerama0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0 \
     libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xkb1 libxkbcommon-x11-0 \
     libxkbcommon0 libgl1 libegl1 libxcb-cursor0 libxcomposite1 libxdamage1 \
     libxfixes3 libxrender1 libxtst6 libxi6
   apt-get install -y fonts-wqy-microhei fonts-noto-cjk && fc-cache -f   # 不装=豆腐块
   apt-get install -y x11-utils xdotool                                   # 查窗口用
   ```
   验证: offscreen `import PyQt5` + `import studio` + `update_checker.CURRENT_VERSION`。
   VcXsrv 探测: `timeout 2 bash -c 'echo > /dev/tcp/host.docker.internal/6000'` — 不通让用户跑
   `Start-Process 'C:\Program Files\VcXsrv\vcxsrv.exe' -ArgumentList ':0','-ac','-multiwindow','-clipboard'`。
   重建后首次启动慢属正常 (冷缓存); "Unknown property cursor" 是 QSS 无害警告。

4. **小版本迭代**: 版本号 5 处 (studio.py 标题+侧栏 / update_checker / docs_sync ×2 / integrity_check) →
   `integrity_check.py` 通过 → commit → push main → tag → push tag。

## 二、从会话历史重建丢失代码 (session forensics, 08-18 实测恢复状态空间整功能)

未 push 的代码从磁盘消失, 但 **Hermes sessions 库存着每次工具调用的完整参数** —
write_file 的完整 content、patch 的 old/new 字符串、生成的 JSON 全都在, 可 100% 重建:

1. `session_search(query="<功能关键词>", sort="newest")` 找实现会话 (文件名/按钮名/函数名做关键词; FTS5 默认 AND)
2. `around_message_id` + `window` 滚动翻到实现段落; **工具调用参数就是源码**:
   - write_file 的 `content` 参数 = 完整文件内容 (直接重建文件)
   - patch 的 `new_string` 参数 = 改动后的代码 (重新 apply)
   - 会话里可能有"吞函数头"等中途失误, 以修复后的最终 diff 为准
3. 按依赖顺序重建: JSON 画布 → GUI 代码 patch → 源码模块
4. 重建后 offscreen 冒烟验证 (按钮存在/画布加载/方法存在) → **立刻 commit + push**

### 状态空间功能重建清单 (08-17 晚做、未 push、08-18 从会话恢复)

- `flows/state_space_obs.json` — 14 节点 13 连线 (S1感知→S2并行快慢分离→S3认知决策→执行闭环), row_bg 带 source 映射
- `tools/gui/simulink_module.py` 5 处: 🧮状态空间按钮(mk_btn) + tl.addWidget + open_state_space/_state_space_hint + on_node_activated 双击分发(state_space→_show_state_space_detail) + _show_state_space_detail 方法(六层 HTML 详情) + 右键"打开源代码"无条件显示 + open_node_source 无 source 提示
- `src/lerobot/policies/left_right/state_space/` — perception/parallel/dynamics/cognition/safety/execution 六层模块 (右键源码视图目标)

## 三、坑 (全部 2026-08-18 实测)

- **tag 误建**: `git commit | tail -1` 管道掩盖 commit 失败, `&& git tag vX` 仍执行 → tag 指向旧 HEAD。修复: `git tag -d vX && git tag vX && git push origin vX --force`。
- **git config 写不进**: rm -rf 删了 shell cwd → getcwd 失败后续命令全挂。修复: terminal 的 workdir 参数换目录 (/tmp)。
- **push 卡死**: `git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push origin main`。
- **管道吞退出码**: 要真实 RC 用 `${PIPESTATUS[0]}` 或不用管道。
