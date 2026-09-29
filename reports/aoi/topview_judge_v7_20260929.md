# 工控机 topview 改成「判据图」口径 —— AOI 金手指程序 v7 (2026-09-29)

## 老倪的原话
> 「工空机的金手指，当我 http://10.163.146.78:8793/station 点击 请求检测后，在工控机保存的 topview图片，
>   不是我在 判据图 的样子；改成 判据图 的样子」

## 差在哪(实测量, 不是估)
| | 工控机保存的 topview (改前 v6) | 4060 网页「判据图」 |
|---|---|---|
| 尺寸 | **960x960 方图**(把 1455x70 的条带纵向拉 ~13.7 倍填满方框) | **900x332**(原比例条带 + 纵向×2 + 反倾角 + 定尺) |
| 内容 | 只有金手指本身那条, 上下留白被拉伸 | 过曝带切掉、含焊盘排/缝/金带、死白列裁掉 |
| 灰度均值 / 饱和 | — | 173.0 / 25.3% |
同一张原图(工控机 `?kind=origin` 2448x2048)走两条口径 ⇒ 肉眼看就是两张完全不同的图。这就是他说的"不是判据图的样子"。

## 改法(工控机程序 v7, 只改 10082 金手指)
1. **落盘/对外展示的 topview 改判据图口径**: 把 4060 侧 `tools/aoi_exposure_fix.py` 的口径**逐条移植**进工控机程序
   (`render_judge`): 过曝带切除 → 只留金手指条 → 列方向裁死白列 → 短边×2 → 按实测倾角反旋(白底) → 定尺 **900x332**。
   ⚠️ 灰度加权必须 `0.299R+0.587G+0.114B`(进出各转一次颜色) —— 喂 BGR 会裁错行, 4060 侧踩过。
2. **模型输入逐位不变**: YOLO 仍吃原来那张 960x960 模板法规整图(`imgsz=960`, 召回不受影响), 另存
   `Finger_ModelIn_W960_H960_No_*.png` 并送检; `/last_result` 同时报 `topview`(判据图, 人看的) 与
   `model_input`(模型吃的), 追溯不断。
3. `/picture?kind=crop|topview` 给的就是判据图 ⇒ 页面「同口径透传」模式与「本地 canonical」模式**看到的是同一张**。
4. `/crop_info.judge` 出台账: 保留行区间/切掉多少过曝行/列裁区间/倾角/定尺/饱和比; 渲染失败时**回退 + 打警告**, 不硬裁一张错的。
5. 保留上限: 新增 `Finger_ModelIn_*` 加入 `_PRUNE_PATTERNS`(与原图同档)。

## 证据(全部实测)
**离线(桩相机喂真实原图, 不碰产线)** `~/aoi_v4/test_v7_judge_offline.py`:
```
✅ POST /capture_detect → 200        ✅ 落了 Finger_TopView_W900_H332_*  ✅ 落了 Finger_ModelIn_W960_H960_*
✅ 顶视图 900x332                    ✅ 模型输入仍 960x960
✅ ②b 直调 render_judge(同一张原图) vs 网页判据图 **r=0.9973**(保留行[632,766] 列裁[440,1896] 定尺[900,332])
✅ 送检路径 = 最新 Finger_ModelIn_*   ✅ /last_result.topview=判据图 · model_input=960图
✅ GET /picture?grab=1&kind=crop → 900x332       ✅ grab 不落盘(3→3)      ✅ /crop_info.judge 台账齐全
```
**现场(真机, 部署后)**: 一次 `POST /capture_detect` 后
```
/last_result:  topview=Finger_TopView_W900_H332_No_35.png   model_input=Finger_ModelIn_W960_H960_No_35.png   count=0 OK  1618ms
/crop_info.judge: kept_rows[613,764](151行) 切过曝528行(25.8%) 列裁[441,1311] 倾角-0.5° 定尺[900,332] sat_after=0.2696
工控机侧文件尺寸自检(经反向通道读):  saved_topview=900x332  ✅
工控机 ?kind=crop(900x332) vs 4060 网页判据图帧(900x332):  灰度均值 188.1 vs 188.1 · **r=0.9847** · 行剖面 r=0.9971
拼图: /tmp/aoi_cmp/live_side_by_side.jpg (左=工控机保存的, 右=网页判据图)
```
模型输入未变的旁证: 送检文件仍是 960x960(`Finger_ModelIn_*`), 检测回执正常(count/verdict/ms 都有)。

## 回滚
`D:\xspace\ultralytics_AOI\cam_finger_10082_work_v6.py.bak` = **v6**(已用仓库 v6 覆盖回真 v6, 不是 v7 覆盖后的假备份);
它也在 `docs/deliver/v6/cam_finger_10082_work_v6.py`。回滚 = 把 .bak 拷回 + 重启(老倪/我可经反向通道一键做)。

## 反向通道"死了"的三根因(顺带修好, 否则这次压根推不上去)
现象: `aoi_remote_deploy.py` 卡在「通道没回执」; `aoi_watch.sh` 报「工控机 agent 已 N 分钟没轮询」。
抓包(tcpdump -A)看到真相: **工控机每 5s 都在请求** `GET /agent/cmd?t=ZMAX_AOI_KeepAlive`,
而我们回了 **403 (token 不对)** —— 客户端活着, 是主节点这头三重故障:
1. **hub 没托管**: 8794 上没人监听(手工启动过, 一断就没了) ⇒ 建 `zmax-agent-hub.service`(enabled, Restart=always)。
2. **队列放在 /tmp 被内核拒写**: 服务以 root 跑、队列文件属主是 ubuntu, root 去重写 sticky 目录下的他人文件被
   `fs.protected_regular` 拒 ⇒ `PermissionError: /tmp/zmax_agent_cmd.jsonl`, 队列取不走(表象"通道断了") ⇒
   运行态统一搬到 `~/zmax_data/agent_hub/`(cmd.jsonl / out/ / hub.log / beat)。
3. **两端 token 不一致**: 工控机上那条循环带的是 `ZMAX_AOI_KeepAlive`, 脚本里写的是 `zmax-7ce74c7f` ⇒
   hub 支持**多 token**(逗号分隔), 两个都认。
修完实测: 入队 `echo/$env:COMPUTERNAME/whoami` → 回执 `ZMAX_PROBE_OK / DESKTOP-NV6ATND / nt authority\system`
⇒ 通道恢复, 本次 v7 才推得上去。
新增工具 `tools/station_cmd.py "PowerShell 命令"`(一条命令给工控机, 带取回执)。
