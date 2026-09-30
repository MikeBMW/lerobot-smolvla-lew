# 20260807 数据集管理命名/列表迭代 + 插销数据链路

老倪(08-07)数据集管理页连续整改记录 — 全部细节，避免下次重踩。

## 命名规范（关键认知）

- **本地目录名 ≠ 官方任务名**：
  - `data/metaworld_act` = 官方 **nut-on-peg**（套环，MT50 task 0，696 帧）
  - `data/metaworld_peg_lerobot` = 官方 **peg-insert-side-v3**（插销插拔，24 eps / 4800 帧）
  - `data/metaworld_peg_v2` = peg 数据 npz 原始源（30 eps / 5850 帧，中间产物，列表隐藏）
  - `data/orin_live` = CICD 采集包（114 个 auto_*.json，meta 标 relay=ECS）
  - `data/orin_real_v1` = 真机 v1（parquet+mp4，**64×64 低清 21 帧**）
  - `data/orin_archive` = 产线快照（3124 个 snap_*.json+jpg，工序状态：料盘识别/取料/尝试插入/扫码）
- **表格显示两行命名**：`name = f"📁 {中文名}\n{官方任务名}"`（上行中文 / 下行官方名）
- 官方仓库只有任务名（peg-insert-side-v3 等），metaworld_* 目录名只存在于本地 data/——用户问"哪有 metaworld_act"时解释这是本地存储名。

## 列表规则（_local_datasets / DatasetModule）

- `tasks` 列：本地单一任务演示集填 **"—"**（曾误填帧数 4800/696 被纠）；HF 云端条目（MT50）填 50
- 本地行 `local=True`：缓存列恒 "✅ 本地"；下载按钮对本地行无意义（orin 是 CICD 采集，不是 HF 下载——下载报"缺少 huggingface_hub"是错误路径）
- 重复行删除：peg_v2（npz 源）与 peg_lerobot 同数据 → 只留训练用的；本地 mt50 与 HF mt50 重复 → 删本地行
- orin 数据合并**一行**（就一个 Orin，子目录按阶段）——用户嫌"4 个 orin 不都一样么"
- `_is_cached` metaworld 分支：glob 必须 `recursive=True`（parquet 在 chunk-000/ 子目录，非递归匹配不到 → 缓存显示"—"）

## 数据集查看器格式支持矩阵（dataset_viewer.py）

| 格式 | 路径 | 注意 |
|---|---|---|
| npz | `_load_npz_frame` | **内存提取**：`np.load` 后 NpzFile 数组访问是 lazy 解压（1.5s/帧）→ `_np.array(d["observations"])` 一次提取 → 翻帧 1ms；180° 旋转**仅 peg 数据**（`"peg" in local_npz`）——metaworld_act 是 MT50 官方数据方向正确**不转**（曾无条件旋转把 act 转反被纠） |
| parquet | `_load_parquet_frame` | 系统 python3 无 pandas/pyarrow → 读不了；**有 npz 时 npz 优先** |
| mp4 视频 | cv2 | AV1 编码 cv2 硬件解码失败（metaworld_act videos）→ npz 优先兜底 |
| json 采集包 | `_load_json_package` | orin_live 无图像 → 显示包 meta（源/帧数/关节）+ 每帧 state/action 文本；ep_slider 切包、frame_slider 切帧 |
- 打开自动加载首帧（`QTimer.singleShot(0, self._load_video_frame)`）——frame_slider maximum 初始 0，手动点"加载帧"才更新导致"下一帧点不了"
- 低清图放大加 `Qt.SmoothTransformation`

## 插销数据生成链路（gen_peg_data.py）

- 官方专家策略 `SawyerPegInsertionSideV3Policy`（metaworld/policies/sawyer_peg_insertion_side_v3_policy.py）采样成功轨迹
- 参数：`--eps 30 --camera corner2`（与视频同视角）；失败轨迹 150 步提前终止（渲染慢）
- 30 成功 eps / 41 尝试（73%）；5850 帧 → npz_to_lerobot 转 24 eps / 4800 帧（train 80%）+ val 1050 帧（20%）
- 专家策略文件=数据生成源头：`metaworld/policies/` 下 50 个文件对应 50 任务，生成任意任务数据改任务名即可

## 大文件操作教训（复述，重要）

- studio.py 曾用 execute_code 字符串操作删 DATASETS 条目 → **静默截断文件到 1266 行**（删了 6500 行）→ git checkout 恢复 HEAD（15:52 提交）+ 重新应用 15:52 后的 8 处 patch
- 教训：大段删除用 patch（精确 old_string）；execute_code 写文件后必须立刻 wc -l + ast.parse + grep 关键类验证
