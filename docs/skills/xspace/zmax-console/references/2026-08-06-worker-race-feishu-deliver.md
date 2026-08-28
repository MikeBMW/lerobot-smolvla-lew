# 2026-08-06 下半场: worker 竞态 / 后台线程Qt / 飞书交付 / 自动链路

老倪验收「5 模型训练→视频→PDF→飞书群」全链路时暴露的技术坑。全部已修复并提交。

## 1. worker 终止竞态 → 五模型队列卡死（VLA-Touch 不启动）

- 症状: 五模型训练串行队列, ACT→SmolVLA→SmolVLA+LEW 完成后, VLA-Touch 不启动, 无子进程, 曲线停在 smolvla_lew。
- 根因: `_done`(主线程) 收到 finished_ok 触发 `_flow_next` 启动下一个任务时, 上一个 worker 线程刚 emit 完还在收尾, `QThread.isRunning()` 短暂返回 True → 防重入误拦截 → 队列卡死。
- 修复: 4 处防重入 (`_start_canvas_flow`/`_start_worker`/`_run_full_flow`/`_run_node_stage`) 统一改为:
  ```python
  if w is not None:
      if w.isRunning() and not w.wait(300):   # 300ms 等正常收尾; 真卡死才拦截
          self._log(self._busy_hint())
          return
  ```
- 教训: 防重入检查 `isRunning()` 有竞态窗口; 训练完成瞬间的"还在跑"提示很可能是误判。

## 2. 后台 threading.Thread 直接操作 Qt 控件 → GUI 静默崩溃

- 症状: `_auto_finalize_work`(threading.Thread) 里 `self._log()` 直接 `log_box.append` → 进程无 Traceback 直接退出（Qt 跨线程 UI 访问）。
- 修复: `_safe_log` 用 QMetaObject 队列回调主线程:
  ```python
  def _safe_log(self, msg):
      from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
      QMetaObject.invokeMethod(self.log_box, "append", Qt.QueuedConnection, Q_ARG(str, msg))
      QMetaObject.invokeMethod(self.log_box.verticalScrollBar(), "setValue",
                               Qt.QueuedConnection, Q_ARG(int, self.log_box.verticalScrollBar().maximum()))
  ```
- 所有后台线程方法 (`_auto_finalize_work`/`_send_file_to_feishu_work`/`_send_report_to_feishu_work`) 的 `self._log(` 一律换 `self._safe_log(`。

## 3. 飞书发文件到群: mp4 必须 file_type=stream

- 上传 API: `POST open.feishu.cn/open-apis/im/v1/files` (multipart: file_type/file_name/file)。
- **mp4**: 上传 `file_type=mp4` + 发 `msg_type=file` → **400 code 230055 "file upload does not match message type"**。
  `msg_type=video` 不存在（invalid msg_type）；`msg_type=media` 需额外 image_key 封面。
  **正解: 上传 `file_type=stream` + 发 `msg_type=file` → 0 success。**
- pdf: 上传 `file_type=pdf` + 发 `msg_type=file`（正常）。
- 群 chat_id: `oc_c0b4048546145c5c581ddd1a9e8f565d` (dataworld)，凭据在 `~/.hermes/.env` (FEISHU_APP_ID/SECRET)。
- token: `POST .../auth/v3/tenant_access_token/internal` {app_id, app_secret} → tenant_access_token。
- 发送后跟一条 text 消息说明文件名（群成员可读）。

## 4. rollout_video.py load_policy: ckpt ts 目录不一致 → glob 兜底

- 症状: vla_touch/awe_zflow rollout 失败 `FileNotFoundError: checkpoint 不存在: outputs/train/vla_touch_<ts>/checkpoints`。
- 根因: on_train 的 ts_dir 与 train_vla_touch/train_awe_zflow 脚本内部生成的 ts 差几秒 → 曲线 json 记的 ckpt 路径不存在。
- 修复: base_dir 不存在时 glob 找最新同前缀目录:
  ```python
  base_dir = os.path.join(ROOT, ckpt_base)
  if not os.path.isdir(base_dir):
      prefix = os.path.basename(os.path.dirname(ckpt_base)).rsplit("_", 1)[0]
      hits = sorted(glob.glob(f"outputs/train/{prefix}_*/checkpoints"), key=os.path.getmtime)
      if hits: base_dir = hits[-1]
  ```
- ⚠️ 陷阱: `os.path.basename(ckpt_base)` 取到的是 `checkpoints` 不是 `vla_touch_<ts>` — 必须 `basename(dirname(...))`。

## 5. ffmpeg xstack 拼接: layout 用纯数字

- 症状: 两级 xstack (3+2) 和 `layout=0_0|w_0_0|w_0+w_1_0|0_h_0|w_3_h_0` 均 `Failed to configure output pad` → 输出 0 字节。
- 根因: `w_3_h_0` 组合相对引用不被支持; 多输入 xstack 直接用纯数字坐标。
- 正解 (5 输入 3+2 网格, 每格 320×240):
  ```
  [0:v]scale=320:240[a0];...;[a0][a1][a2][a3][a4]xstack=inputs=5:layout=0_0|320_0|640_0|0_240|320_240[v]
  ```

## 6. ZMAX_AUTO_RUN=1 自动交付链路

- studio.py `__init__` 尾: `if os.environ.get("ZMAX_AUTO_RUN")=="1": QTimer.singleShot(2500, self._auto_run_compare5)`。
- `_auto_run_compare5`: 切 Simulink 页 → `_qmsg_yes=lambda:True` → `open_compare5()` → `start_sim()`。
- `_flow_next` 队列空分支: ZMAX_AUTO_RUN 且未 done → `_auto_finalize()` (threading) → rollout 5 模型(60帧) → ffmpeg mp4 + xstack → generate_report.py PDF → 飞书发视频+PDF。
- 手动交付应急脚本模式: bash 直接调 rollout_video.py → ffmpeg → python 发飞书（绕开 GUI worker，用户催交付时最快路径）。

## 7. 训练步数档位 (2026-08-06 演变)

3 步=通路验证 → 10 步=流程跑通 → 500/1000 步=正式对比。老倪验收链路: 先 3 步看通路(群里收到视频+PDF), 再 1000 步看插拔成功。改步数: `"steps": N` 在 simulink_module.py 模板训练节点 (17 处) + node_logic.py `steps = p.get("steps", N)` + TrainConfigDialog 默认。

## 8. 外部命令行训练日志 → GUI 终端区显示 (_poll_ext_log)

- 触发: 老倪"我看着GUI界面呢,终端得有东西啊" — 命令行后台训练 (zmax_train4.sh 等) 日志不进 GUI log_box, 用户看不到进度。
- 修复: GUI 每 2s 轮询外部日志文件新行, 过滤关键行 append 到 log_box:
  ```python
  def _start_ext_log_watch(self):   # __init__ 末尾调用
      self._ext_log_pos = {p: 0 for p in ("/home/xspace/zmax_train4.log",
                                          "/home/xspace/zmax_deliver_latest.log")}
      self._ext_log_timer = QTimer(self); self._ext_log_timer.timeout.connect(self._poll_ext_log)
      self._ext_log_timer.start(2000)
  def _poll_ext_log(self):
      _keep = ("loss", "step=", "✅", "❌", "===", "完成", "📈", "训练", "epoch", "it/s", "step/s", "curve")
      # 每文件: seek(pos) 读增量 → 逐行: 跳过空行/"+ "前缀(set -x 噪音) → 命中 _keep 才 append
      # 尾部: verticalScrollBar().setValue(maximum()) 自动滚底
  ```
- 命令行训练约定: 后台脚本写日志到固定路径 (`/home/xspace/zmax_train4.log`), GUI 监视它 — 命令行训练与 GUI 并行互不干扰 (GUI 重启不杀训练进程)。
- 用户偏好 (铁律): **自动流程必须 GUI 可见** — 老倪"你自动流程,我也看不到,你得启动控制台,你可以在控制台上工作"、"我得看着啊"。后台偷偷跑 + 只文字汇报 = 不合格; 先 `DISPLAY=:0 python3 studio.py` 开控制台让用户看着, 再跑流程。
- 手动交付应急模式: `/home/xspace/zmax_deliver_latest.sh` (rollout 5 模型 → ffmpeg mp4 → xstack → python 发飞书), 用户催"视频呢/最新视频有么"时最快路径 — 但**以后要自动发送** (老倪明确), 手动只是应急。

