# 控制台重启纪律 + 真机 YOLO 标定工位三修 (2026-09-17 二次会话实测)

> 来源: 老倪同一天第二次报「怎么又反复重启控制台, 查查, 别自动重启」→ 接着「连上orin了, 测试吧」
> → 「测试标定」→ 「就一个光模块, 怎么定义类别?」→ 「左键拖不出框 / 改选中类别不好使」。
> 全部结论都是代码级 + 实测取证, 不是推断。

## 一、控制台"反复重启"的完整链条 (两段, 都要治)

| 段 | 现象 | 根因 | 处置 |
|---|---|---|---|
| 1 | 点 X 关掉, 5s 又弹回 | `Restart=always` 对**正常退出(exit 0)**也拉起 | 改 `Restart=on-failure` |
| 2 | 仍会"反复重启" | journal 实证 `Main process exited, code=exited, status=1/FAILURE` + `The X11 connection broke (error 1). Did the X11 server die?` — **桌面会话/X 一断就退 1 = FAILURE**, on-failure 又拉起来 | 老倪口径「**别自动重启**」→ `Restart=no` |

复核三连 (改完必做):
```bash
systemctl --user daemon-reload
systemctl --user show zmax-studio -p Restart -p NRestarts -p ActiveState   # 期望 Restart=no / inactive 或 active
```

## 二、⚠️ 重启控制台的正确姿势 (本会话踩到)

**现场控制台很可能根本不在 systemd 下** (桌面图标 `~/Desktop/XSpace-Studio.desktop` →
`tools/gui/launch_studio.sh`, 或人手起的): `systemctl --user is-active` = **inactive** + `MainPID=0`,
但 `ps` 里 `studio.py` 活得好好的。

此时 `systemctl --user start zmax-studio` **不替换它, 而是又起一个 → 两个控制台并存**
(实测: pid 6048 = 43 分钟前的旧代码实例, pid 17583 = 我刚起的新代码实例, 两个都在跑,
用户会看到两套窗口、还可能点到旧的那套 → 又会说"你没改").

规程 (改 GUI 代码后重启必走):
1. `MP=$(systemctl --user show zmax-studio -p MainPID --value)` 拿 service 侧 pid;
2. `ps -eo pid=,etime=,args= | grep -F "studio.py" | grep -vF grep` 列**全部**实例, `etime` 大的 = 旧实例;
3. `kill -TERM <旧pid>` —— **逐个按 pid 杀**;
   ⚠️ **绝不** `pkill -f "gui-venv311/bin/python studio.py"`: 自己命令行含该串 = 自杀 (老坑, 本会话用 MainPID 法绕开);
4. `systemctl --user start zmax-studio` → `sleep 15` → 复核**只剩 1 个进程** + `is-active=active`;
5. 汇报时说清: **"旧实例/旧窗口已随进程关闭, 请重新右键打开窗口"** ——
   Python 已缓存旧类, **关窗口重开不生效**, 必须重启进程。

## 三、真机 YOLO 标定工位: 类别口径 (老倪: 「就一个光模块, 怎么定义类别?」)

**唯一口径源** = `src/lerobot/policies/yolo_3d/frame_source.py`:
```python
CLASS_MAP = {"hand": "hand", "peg": "光模块", "hole": "hole"}   # 注释: peg→光模块; 类 id 顺序不许改
```
下游 `tools/real_yolo_perceive.py` 按**业务名**取: `det3d.get("hand")` / `det3d["光模块"]` / `det3d["hole"]`
→ 写进 obs39 的 `[4:7]`(光模块) 与 `[36:39]`(孔口)。

- ⇒ **真机训练类名必须是 `peg`**。界面原来默认的 `optical_module` 在 CLASS_MAP 里**没有条目**
  ⇒ 训出来的权重接不进感知链 ("光模块"那一路恒空 = 白训)。"光模块"是业务名, `peg` 才是训练类名, 别手输中文。
- **类别 ≠ 型号**: 老倪现场往可编辑 combo 里打了 `100G平` / `400G` (拿型号当类别) ——
  外观相同的模块必须归**一类** (分型号只会让每类样本更少、互相打架), 型号区分属下游元数据。
  类名另禁空格/逗号/斜杠 (`add_class` 直接 raise)。
- 真机现状 (画面只有光模块一端入镜) → **一类 `peg` 足够**; `hand` 真机不靠视觉 (走 `/robot/tcp_pose` 真值);
  `hole` **是视觉出的**, 画面看得到孔口就必须标, 看不到则只能由现场几何示教顶上
  (`tools/ss_geom_calib.py --record goal`), 两条路**至少通一条**。
- 已统一: `data/yolo_annot/classes.txt` 与 `yolo_annot_dataset.DEFAULT_CLASSES` 均为 `peg`
  (两处 GUI 兜底默认也改掉了)。

### ⚠️ 可编辑 combo = 类别表污染源
combo 是 `setEditable(True)`, `_on_cls_changed` 里"手输新类别名 → **立即 `add_class()` 追加一行**";
`save_sample()` 对**未知类名也会 append** (`cid = names.index(c) if c in names else add_class(root, c)`)。
实测事故: 下拉残留旧名 `optical_module` + 标定员顺手打了 `100G平`/`400G`
→ `classes.txt` 变 `peg(0)/optical_module(1)/100G平(2)/400G(3)`, 而已存标签写的是 **id 1** ⇒ 类别表与标签语义错位。

排查/修复:
```bash
cat -n data/yolo_annot/classes.txt          # 行号 = class id
# 逐标签首列统计 (看实际用了哪些 id)
python3 -c "import glob;print(sorted({open(f).read().split()[0] for f in glob.glob('data/yolo_annot/sessions/*/labels/*.txt') if open(f).read().strip()}))"
```
修法 = 类别表回归单行 `peg`, 再把所有标签**首列重映射为 0** (批量脚本改, 别手改);
`annotations.jsonl` 是追加式审计流水, **不改历史**。

## 四、标定窗口两个真 bug (都取证过)

### ① 「左键拖不出框」= 拖框锚点被每帧鼠标移动覆盖
`tools/gui/yolo_label_widget.py` `_edit_drag()` 的 `new` 分支原写 `self._drag = ("new", start, pt, -1)`,
而 `start` 是**上一次鼠标点** → 每动一次就把**按下锚点冲掉** ⇒ 松开时算出的矩形只剩最后一小段位移
(通常 <4px) → 被 `if (x2-x1)<4` 判成误点丢弃 (或拖出个 20×15px 碎片框)。
**锚点必须恒为 index1 (按下那一点), index2 才跟鼠标。**

### ② 「🏷 改选中类别 不好使」= 两窗只同步框集合、不同步选中项
`w_orig.changed` / `w_rot.changed` 只接 `_sync_boxes`, 而 `_sync_boxes` 在"**框集合相同**"时直接 return;
在**旋转窗(180°, 相机翻转安装时最常用)**点选一个框只改 `_sel`、不改框集合 ⇒ 左窗 `_sel` 仍 -1,
而「改选中类别 / 删选中 / 撤销」当时全绑 `self.w_orig.selected()` → 取不到选中, 只在日志留一行
"没有选中框" = 用户视角"按钮坏了"。
修: ①两侧 `selectionChanged` 互相同步选中索引 (`_mirror_sel`, 只同步索引不重建框, 带 `_mirroring` 防递归)
②这几个按钮改走 `_active_pane()` (谁有选中就作用于谁, 都没选中退回左窗)。

## 五、可复跑取证

`scripts/verify_annot_drag_relabel.py` (本技能目录下) —— 一个 offscreen 脚本同时验 ①②:
- 拖框锚点: 0° 与 180° 两个窗, 显示坐标 100,100→260,220 (320x240 原帧显示在 640x480 控件),
  期望 0° 存 `(50,50,130,110)` / 180° 存 `(189,129,269,189)`;
- 右窗选中 → 左窗 `selected()` 镜像为 0 → `_relabel_selected()` 后两窗类别一致。
改这两个文件后**先跑它, 再重启控制台**。

## 六、顺带记录: 标定数据落盘链路 (真机帧)
- 真机帧链路: Orin `tools/orin_frame_srv.py` (UVC 取帧 + 服务端 JPEG 压缩) →
  4060 `tools/ss_frame_srv_client.py` (本机 Docker, 落 `~/zmax_ss_remote/live_frame.jpg/.json`) → 窗口轮询。
- 判"到底有没有真帧"看 `live_frame.json`: `age_s` / `seq` / `src` / `device`(VID:PID+序列号) / `stale`。
  实测健康值: `age_s≈0.79 / seq 递增 / src=uvc / device="Intel(R) RealSense(TM) Depth Ca ... sn=..." / stale=false`。
- 现场几何示教 (`ss_geom_calib.py`) 的写出路径必须与采集器读取路径**同口径**
  (`SS_GEOM_PATH` 优先 → 有 `SS_OUT` 就跟随 `$SS_OUT/real_cell_geometry.json`), 否则示教完 tap 仍报"无示教几何"。
