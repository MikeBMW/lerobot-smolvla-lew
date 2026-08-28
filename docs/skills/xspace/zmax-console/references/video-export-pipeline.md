# 状态空间视频导出管道 (gen_state_space_video.py)

`_start_video_export` 用 `sys.executable`（= gui-venv311 Python 3.11）跑子进程渲染，
Pillow 画帧 → ffmpeg 合成 → sshpass scp 上传 ECS。四类依赖缺一即失败，报错各不相同。

## 依赖链（缺一即失败）

1. **Pillow** 必须在 gui-venv311 里（报错 `ModuleNotFoundError: No module named 'PIL'`）：
   `~/.hermes/bin/uv pip install --python /home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python Pillow`
   （numpy 已在 gui-venv311；系统 python3 有 Pillow 但无 numpy —— 勿混用解释器）
2. **CJK 字体** — 脚本 `_FONT` 原硬编码 wqy-microhei.ttc，U盘 live 环境只有 NotoSansCJK。
   已改成 `_FONT_CANDIDATES` 候选列表自动探测（wqy→wqy-zenhei→NotoSansCJK-Regular→Bold→
   DroidSansFallback→uming）。新环境加字体就往列表里加，不用改逻辑。
3. **ffmpeg** — `sudo apt-get install -y ffmpeg`（报错 RuntimeError: ffmpeg 失败 rc=...）
4. **sshpass** — `sudo apt-get install -y sshpass`（报错 `No such file or directory: 'sshpass'`）

## 上传链路

```
sshpass -p Nix19789 scp reports/state_space_sim.mp4 root@39.102.211.79:/www/wwwroot/datadrive.world/
sshpass -p Nix19789 ssh root@39.102.211.79 "chmod 644 /www/wwwroot/datadrive.world/state_space_sim.mp4"
```
公网验证：`curl -I https://datadrive.world/state_space_sim.mp4` → 200。

⚠️ **ECS 密码 Nix19789 有效**（08-22 实测 AUTH_OK）。08-13 曾误判"失效"——实为网络被墙，
认证握手超时被当成密码错误。**结论凭据失效前，先确认网络连通再下结论**（网络好了先 curl
github.com / baidu 探测，再试 ssh）。

## 画布字体 DPI 坑（同类问题会复发）

画布/列表字号是按 WSLg 192 DPI 调的（代码注释里大量 "192DPI"）。U盘 live 环境是 **96 DPI**，
同样 pt 值物理尺寸只有一半 → 用户反馈"字太小"。

判断依据：`xdpyinfo | grep resolution` 看实际 DPI，别信代码注释里的旧 DPI 假设。

放大三处（正则批量，**先替换 bold 完整版再替换非 bold，避免前缀误伤**）：
- 画布节点：`simulink_module.py` 的 `SimNodeItem.paint()` / `CICDStageItem.paint()` 里
  `QFont("Arial", 9...)` → 11、`7` → 9、`Consolas 8` → 10、标题递减序列 `(9,8,7)`→`(11,10,9)`、
  row_bg `fs=9`→`fs=11` 下限 `6`→`8`。
- 左侧库 LibraryPanel（QSS `font-size:6pt`→`8pt`，区间约 3441-3650）。
- 右侧 model_tree.py（全部 `font-size:Npx` +2，约 40 处）。

## 验证

改完 `ast.parse` 两文件 → `kill -9` 重启（**不能 `pkill -f "studio.py"`，会匹配命令自身 -9 自杀，
须 `ps aux | grep "gui-venv311/bin/python studio" | grep -v grep | awk '{print $2}' | xargs kill -9`）
→ 后台启动 → `xwininfo -root -tree | grep "XSpace Studio"` 确认窗口坐标正常（非 -32692 飞屏坏态）。
