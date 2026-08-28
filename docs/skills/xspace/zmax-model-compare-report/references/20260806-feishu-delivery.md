# 飞书自动交付: 视频/PDF 发 dataworld 群 (2026-08-06 实测跑通)

## 凭据与 chat_id
- App 凭据从 `~/.hermes/.env` 读: `FEISHU_APP_ID` / `FEISHU_APP_SECRET` (机器人 xspace = cli_a87851ffe46b500d)
- 群 chat_id 发现: `GET https://open.feishu.cn/open-apis/im/v1/chats?page_size=50` (Bearer tenant_access_token) → 找 `name=="dataworld"` 的 `chat_id` (实测 `oc_c0b4048546145c5c581ddd1a9e8f565d`)
- 代码里可写死 chat_id 兜底, 但优先 `env.get("FEISHU_REPORT_CHAT_ID", <chat_id>)` 允许覆盖

## 三步发送流程 (urllib 即可, 无需 requests)
```python
# 1. tenant_access_token
POST /open-apis/auth/v3/tenant_access_token/internal  {"app_id":..., "app_secret":...}
    → data.tenant_access_token

# 2. 上传文件 (multipart/form-data, 手拼 boundary)
POST /open-apis/im/v1/files
  form 字段: file_type / file_name / file (Content-Type: application/octet-stream)
    → data.file_key

# 3. 发消息
POST /open-apis/im/v1/messages?receive_id_type=chat_id
  {"receive_id": chat_id, "msg_type": "file", "content": "{\"file_key\": ...}"}
```

## 🐛 视频发送的致命坑 (实测踩过, 必须 file_type=stream)
| 上传 file_type | 发消息 msg_type | 结果 |
|---|---|---|
| `mp4` | `file` | **HTTP 400 code 230055** "type of file upload does not match the type of message being sent" |
| `mp4` | `video` | **HTTP 400 code 230001** "invalid msg_type: video" (im/v1/messages 无 video 枚举) |
| `mp4` | `media` | 需 `image_key` 封面 (先上传封面图拿 image_key), 复杂 |
| **`stream`** | **`file`** | ✅ **code 0** — 这就是正确组合! |
- **规则: mp4 一律 `file_type=stream` 上传 + `msg_type=file` 发送**; PDF 用 `file_type=pdf` + `msg_type=file`
- 上传成功 ≠ 发送成功: 批量脚本先单文件验证 (上传 OK + 发消息 OK) 再跑全量, 400 时打印 `r.get("msg")` 定位 (traceback 会吞掉错误体)
- 飞书 bot 发文件前可先发一条 text 消息确认通路 (text 消息永远 OK)

## 5 视频 3+2 同屏拼接 (ffmpeg xstack)
```bash
ffmpeg -y -i a.mp4 -i b.mp4 -i c.mp4 -i d.mp4 -i e.mp4 \
  -filter_complex "[0:v]scale=320:240[a0];[1:v]scale=320:240[a1];[2:v]scale=320:240[a2];[3:v]scale=320:240[a3];[4:v]scale=320:240[a4];[a0][a1][a2][a3][a4]xstack=inputs=5:layout=0_0|320_0|640_0|0_240|320_240[v]" \
  -map "[v]" -c:v libx264 -pix_fmt yuv420p out.mp4
```
- 🐛 **xstack layout 必须纯数字**: `0_0|320_0|640_0|0_240|320_240` ✅
- `w_3_h_0` 这类组合相对引用报 `Failed to configure output pad` / `Error reinitializing filters` / 输出 0 字节 — 不要用
- 二级 xstack (先 3 个再 2 个再竖拼) 因输入宽度不同 (960 vs 640) 也失败; 单次 5 输入 xstack 最稳
- 0 字节输出 = ffmpeg 失败但文件已创建: `ls -la` 看大小, 别只看文件存在

## rollout checkpoint 路径 ts 不匹配 (vla_touch/awe_zflow)
- **症状**: `FileNotFoundError: checkpoint 不存在: outputs/train/vla_touch_<ts>/checkpoints` — 但目录其实存在 (差几秒的另一个 ts)
- **根因**: on_train 的 `ts_dir` (训练开始时间) 与 train_vla_touch.py/train_awe_zflow.py **脚本内部生成的 ts 差几秒** → train_curve json 记的 ckpt 路径指向不存在目录
- **修复 (rollout_video.py load_policy)**: ckpt 路径不存在时 glob 找最新同前缀目录:
```python
base_dir = os.path.join(ROOT, ckpt_base)
if not os.path.isdir(base_dir):
    import glob as _g
    prefix = os.path.basename(os.path.dirname(ckpt_base)).rsplit("_", 1)[0]  # 🐛 必须 dirname!
    hits = sorted(_g.glob(os.path.join(ROOT, "outputs", "train", f"{prefix}_*", "checkpoints")),
                  key=os.path.getmtime)
    if hits:
        base_dir = hits[-1]
```
- 🐛 **`os.path.basename(ckpt_base)` 取到的是 "checkpoints" 不是目录名** (ckpt_base 以 /checkpoints 结尾) → glob 模式全错。必须 `os.path.basename(os.path.dirname(ckpt_base))` 才拿到 `vla_touch_20260806_180350` → rsplit 得前缀 `vla_touch_20260806`

## 自动交付链路 (ZMAX_AUTO_RUN=1, GUI 训练完自动发)
1. studio.py: 环境变量 `ZMAX_AUTO_RUN=1` → 启动后 QTimer.singleShot 自动切 Simulink 页 + `open_compare5()` + `start_sim()` (确认框 `_qmsg_yes` 覆盖为自动 True)
2. simulink_module.py `_flow_next` 队列空分支: `ZMAX_AUTO_RUN==1` 且未 `_auto_finalize_done` → 后台线程 `_auto_finalize_work`:
   ① rollout 5 模型 (rollout_video.py 各 60 帧) → ② ffmpeg 每模型 mp4 → ③ xstack 3+2 拼接 → ④ generate_report.py PDF → ⑤ 发飞书 (对比视频 + 5 单模型 + PDF)
3. 训练步数控制: 模板 `"steps": N` (17 处) + node_logic.py `steps = p.get("steps", N)` 要一起改 (10→3→1000 按需)

## 自动交付链路的 PyQt5 崩溃/卡死坑 (GUI 维护)
1. **后台线程直接操作 Qt 控件 → GUI 静默崩溃**: `_auto_finalize_work` / `_send_file_to_feishu_work` 是 `threading.Thread`, 里面 `self._log()` 直接 `log_box.append` (QTextEdit) → 跨线程 Qt 访问 → 进程退出 (stdout 无 Traceback, 只看得到 Qt 警告)。**修复**: 后台线程一律用 `_safe_log` — QMetaObject 队列回调主线程:
```python
def _safe_log(self, msg):
    from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
    QMetaObject.invokeMethod(self.log_box, "append", Qt.QueuedConnection, Q_ARG(str, msg))
```
   (scrollbar setValue 同样队列化; 三个后台方法内所有 `self._log(` 替换为 `self._safe_log(`)
2. **worker 终止竞态 → 队列卡死 (五模型 VLA-Touch 不启动)**: `_done`(主线程, QueuedConnection) 触发 `_flow_next` 时, 上一个 QThread worker 刚 emit 完还在收尾, `isRunning()` 短暂 True → 防重入误拦截后续任务 → 队列静默卡住 (训练曲线停在某个模型, 无任何进程)。**修复**: 防重入检查 `if w.isRunning() and not w.wait(300):` 拦截 — wait(300) 给正常收尾放行, 真卡死才拦 (4 处: _start_canvas_flow/_start_worker/_run_full_flow/_run_node_stage)
3. **WSLg 标题栏 emoji 乱码**: QMdiSubWindow 标题 `"🖥 画布 · Simulink 模型"` 的 emoji (U+1F5A5) 在 Windows 标题栏渲染成十六进制乱码 (如 "01F 5A5"); MDI 子窗口激活时 Qt 把子标题附加到主标题 → 乱码进窗口标题栏。**修复**: 窗口标题一律纯文本 (emoji 只留在按钮/正文), 用 PowerShell `Get-Process msrdc | select MainWindowTitle` 可复现
4. **WSLg 模态弹窗不可见 → "第一次点击没反应"**: exec_() 模态 QMessageBox 在 WSLg 下弹窗不可见但阻塞主线程 → 用户重复点击/按键才解除, 表现为"视频要双击两次才打开"。**修复**: 提示一律非模态 (气泡 _show_bubble / 对话框自带状态行), 不用 exec_
