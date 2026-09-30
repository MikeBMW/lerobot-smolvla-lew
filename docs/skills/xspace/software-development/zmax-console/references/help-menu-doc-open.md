# 帮助文档菜单 + WSL 打开链路 + 验证循环止损 (2026-08-10 实测)

## 1. _mk_doc_action 双前缀坑 (studio.py ~10012 行)
- `_mk_doc_action(label, (paths, opener))` 内部 `full_path = os.path.join(self.docs_path, rel_path)`，
  **自动拼 docs/ 前缀**。传 `["docs/xxx.md"]` 会变成 `docs/docs/xxx.md` → 不存在 → 报
  "以下文档均不存在: .../docs/docs/xxx.md"（老倪实测报错）。
- **铁律: 菜单 addAction 传相对文件名**（`["left_right_policy.md"]`），别带 docs/ 前缀。
- 验证: offscreen 构建 StudioMainWindow → 菜单 actions 文本断言 + `w.docs_path == <root>/docs`。

## 2. WSL 打开文档: explorer.exe 不认 /tmp 路径 (老倪"直接跳到 Windows 文档了")
- 旧逻辑: copy 到 `/tmp/zmax_docs/` → `explorer.exe /tmp/zmax_docs/xxx.md` → explorer 是
  Windows 程序不认 WSL /tmp 路径 → 解析失败**跳到 Windows 用户文档目录**（"跳到文档了"）。
- ✅ 可靠链路（与视频 ZMAX_videos 同模式）:
  ```python
  _win_dir = "/mnt/c/Users/Public/ZMAX_docs"; os.makedirs(_win_dir, exist_ok=True)
  shutil.copy2(full_path, os.path.join(_win_dir, basename))
  _win = win_path.replace("/mnt/c/", "C:\\").replace("/", "\\")
  subprocess.Popen(["explorer.exe", _win])   # 或 .pptx: cmd.exe /c start powerpnt _win
  ```
- **WSL→Windows 打开文件统一模式**: 凡 Windows 程序要打开 WSL 文件（视频/文档/pptx），
  一律先复制到 `C:\Users\Public\ZMAX_*` 再传 Windows 路径。UNC `\\wsl.localhost\...`
  被 CMD 拒（不支持 UNC 当前目录），/tmp 被 explorer 拒（解析成文档目录）——两条死路。
- explorer.exe rc=1 不可靠（单实例转发也可能成功）; 验证播放器真起来用
  `tasklist.exe | grep ApplicationFrameHost`（Win11 UWP 播放器宿主）。

## 3. 视频"已存在直接打开"快速路径 (老倪"视频早就生成好了怎么还要等")
- on_insert_video 每次点都重新跑 gen_insert_video.py (1-2 分钟) 是错的。
- ✅ 入口先查 `reports/insert_success_demo.mp4` 存在且 size>0 → 直接
  `_open_video_for_user(mp4)` + 发飞书，不重新生成。生成逻辑留 _work 分支兜底。
- 打开逻辑抽成共用方法 `_open_video_for_user(mp4)`（生成后 + 快速路径两处复用）。

## 4. 飞书消息 API 必须带 Authorization: Bearer (HTTP 400 "Missing access token")
- token 获取 OK 但发消息 400 —— 消息请求漏了 `Authorization: Bearer <tenant_token>`
  header（只传 Content-Type 不够）。chat_id 缺省用
  `oc_c0b4048546145c5c581ddd1a9e8f565d`（dataworld 群）。

## 5. 验证循环止损纪律 (老倪最终拒绝命令 = 明确信号)
- **症状**: 系统要求"创建 hermes-verify- 临时脚本验证"，但 write_file 创建脚本本身被
  系统记为"编辑"→ 脚本路径（即使已删除）永久累积进 changed paths → 下一轮必再提示
  unverified → 无限循环。本会话同一改动跑了 100+ 轮验证全部 PASS 也无法变绿，最后
  老倪直接拒绝命令。
- **止损规则**: 同一真实改动文件已产出 ≥2 轮 fresh 全 PASS 证据后，**停止再创建验证
  脚本**（每创建一个就喂大 changed paths 列表），改为明确报告 blocker（系统提示允许
  "explain the concrete blocker instead of claiming the work is fully verified"）。
  用户偏好"无限调试要止损快速出结果"——验证循环同理，别无限重复相同的验证。
- 判别: changed paths 里的 /tmp 脚本 `ls /tmp/hermes-verify-*` 实测"无残留"即可声明
  已清理；真实改动文件的行为证据要在回复里列全（py_compile/菜单实测/offscreen 构建）。

## 6. 帮助菜单文档清单 (v2.0.0 新增条目)
- 🧠 左右脑策略 · LeftRightPolicy 技术方案 → left_right_policy.md
- 🏭 精细操作场景 + 调制指标大屏监督方案 → factory_fine_ops_supervision.md
- 📋 光模块工厂精细操作需求规格书 (市场版) → factory_fine_ops_demand.md
- **市场版需求文档铁律（老倪明确要求）**: 零技术词（39D/状态机/MLP/调制/API/力控/
  select_action 全禁），纯工厂视角，只写场景/节拍/良率/外形尺寸/重量/环境/验收口径。
  grep -nE "39D|状态机|MLP|LeftRight|调制|策略|指标|API" 必须为空。
