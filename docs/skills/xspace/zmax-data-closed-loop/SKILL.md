---
name: zmax-data-closed-loop
description: Z-MAX 边学边练闭环 — Orin采集→ECS→4060训练→静态URL部署→推理循环。机器人采集时用。
---

# Z-MAX 数据闭环 (边学边练)

## 触发条件
机器人运行中，需要 采集→训练→部署 全自动循环。

## 链路总览
```
① Orin采集(20s MCAP+打标) → ② 上传ECS relay → ③ 静静4060训练(ACT)
→ ④ 模型推静态URL → ⑤ 小芳部署Orin → ⑥ 真实推理 → ⑦ 报告回传 → 循环
```

## 关键端点 (ECS 39.102.211.79)
- 上传: `POST https://datadrive.world/api/relay/upload`
- 数据弹栈: `GET https://datadrive.world/api/relay/latest` (取走即删!)
- 只读peek: `GET https://datadrive.world/api/relay/peek`
- 队列状态: `GET https://datadrive.world/api/relay/status`
- Orin状态: `GET https://datadrive.world/api/relay/orin/status`
- 快照图: `GET https://datadrive.world/api/snapshot/latest`
- **模型静态URL(不弹栈!): `GET https://datadrive.world/models/act_cartesian.safetensors`**

## 模型传递 (最关键, 曾失败4次)
**不要用弹栈队列传模型!** 弹栈时序竞争会导致模型丢失。
**正确方式: 静态URL**:
```bash
# 推模型 (scp 到 ECS 网站目录 + chmod 644)
sshpass -p 'Nix19789' scp model.safetensors root@39.102.211.79:/www/wwwroot/datadrive.world/models/
sshpass -p 'Nix19789' ssh root@39.102.211.79 "chmod 644 /www/wwwroot/datadrive.world/models/*.safetensors"
# 小芳拉取
curl -o /tmp/model.safetensors https://datadrive.world/models/act_cartesian.safetensors
```
注意: 静态目录文件权限必须 644 (nginx www-data 可读), 否则 403。

## 训练 (4060 本地)
```bash
cd ~/lerobot-smolvla-lew
# 数据从 orin_live 构建 LeRobot 数据集
python3 tools/build_orin6d_dataset.py   # 构建 data/orin_6d (6D state/action)
# 训练 (笛卡尔接口或6D关节)
PYTHONPATH=src .venv/bin/python -m lerobot.scripts.lerobot_train --config_path config_act_loop.yaml
```

## LeRobot 数据集坑 (全部踩过)
1. **hub 下载覆盖本地root**: LeRobotDataset(root=本地) 会 snapshot_download 覆盖!
   补丁: lerobot_dataset.py 和 dataset_metadata.py 的 _download 里, root/meta/info.json 存在时跳过下载
2. **parquet float64→float32**: 必须用 pyarrow fixed_size_list(float32) 写
3. **episodes 索引列必须 int64** (float 会导致 format 错误)
4. **frame_index 必须=全局 index** (视频合并顺序), timestamp=total/30.0 全局
5. **视频帧数必须=parquet帧数**: ffmpeg 用 `-vsync 0 -fps_mode passthrough` 防止丢帧
6. **图像只保留有效帧**: 无 camera_b64 的帧跳过, 避免 mp4/parquet 不一致
7. **delta_timestamps 超界**: ACT n_action_steps=7 查未来帧, 全局视频末尾会超界 → timestamp 全局化

## 数据包格式 (小芳上传)
```json
{"meta": {"source": "orin", "frames": N, "n_joint": 6, "n_action": 6, "labels": {...}, "time": 绝对时间戳},
 "frames": [{"observation.state": [6], "action": [6], "label": "...", "timestamp": 相对秒, "camera_b64": "高清320x240 JPEG"}]}
```
- frame_index/episode_index 在包里可能是轨迹内, build 时转全局

## 验证闭环
```bash
curl -s https://datadrive.world/api/relay/orin/status  # infer_count > 0 = 推理中
```

## 容量上限 (防磁盘满, 2026-08-03)
- 单包/缓冲上限 100M (nginx 100m + relay MAX_PKG 413拒绝)
- disk_guard.py: orin_live限60包/训练保留4个/日志5MB/水流2万行/tmp7天, 每小时自动清理
- ECS logrotate: datadrive.world.log/error.log daily 100M 3份压缩
- ECS 磁盘 40G 易满, 重点清 /www/wwwlogs + archive(快照505M)

## WS 事件驱动 (v2, 2026-08-03)
- auto_loop v2: WS订阅 data_arrived → 毫秒级触发训练 + 60s轮询兜底 + 断线5s重连
- ECS zmax_relay: /upload成功→notify(:8766)→广播; ws_relay 8766通知口
- 单测6/6: 事件触发/非事件忽略/快照过滤/frames阈值/全链路/并发锁

## 里程碑 (2026-08-02)
- v1: 笛卡尔模型 state3D→action4D, 真实推理 1051ms (TCP位姿输入)
- **v2: 6D关节模型 state6D→action6D, 真实推理 479ms** (比v1快2.2倍), 动作值合理
- 训练: 755帧/19轨迹, loss 1.524, 2000步
- 推理验证命令: `orin_real_infer.py <6个关节值>` (v2必须6D输入, 不是3D!)
- v2模型: https://datadrive.world/models/act_cartesian.safetensors (已覆盖为6D模型)
- **orin_real_infer.py 修复**: 旧版硬编码3D输入(笛卡尔), v2改从权重自动推断 state_dim
- 完整链路 v2 实测: 采集755帧 → 训练loss 1.524 → 静态URL → 部署Orin → 真实推理479ms ✅
- 6D 关节模型与实机匹配 (state6/action6), 代码已入库, 闭环进入持续迭代模式 (守护自动训练 v3...)

## 里程碑 v3 (2026-08-02 晚, 数据闭环真实性加固)
- **action 恒等修复**: Orin 采集端把当前关节状态当 action 记录 (action==state) → 训练恒等映射无效。
  修复: `tools/fix_orin_action.py` 检测 action≈state → 改关节速度差分 (delta state), 与 metaworld joint 定义一致; 已集成进 GUI 拉取链路
- **6D 统一**: metaworld joint6 (qpos[0:6] 6D, 无夹爪) = Orin 6D (n_joint=6), 图像都 64² → 三阶段维度完全一致, Stage3 权重迁移成功 (--policy.path= 等号 CLI 格式!)
- **expert 策略采集**: `collect_metaworld_joint.py --policy expert` 用 metaworld 自带脚本策略 (sawyer_reach_v3_policy) 采高质量演示, 替代随机动作 (2000帧/20ep); Sim2Real MSE 0.0355→0.0051
- **S2 测试集评估**: eval_ds 取尾部 20% 帧 (训练前 80%), 消除"同分布全量"过拟合假象
- **数据闭环控制台** (Simulink): 🎯数据闭环控制台 = 闭环状态栏(数据/模型/URL/Orin/推理, 10s 轮询真实 API) + 6环节流水线(采集→训练→验证→集成→部署→推理, 全部真实执行) + 三阶段卡(cicd_pipeline 真实命令)。所有状态读真实文件/API, 无模拟值。数据帧数口径=训练集 orin_real_v1
- **三阶段超参 (用户策略落地)**: S1 lr1e-4/backbone冻结/kl10/chunk100/n_action50; S3 lr1e-5/backbone1e-6/kl10/chunk100/n_action1(ensemble硬性)/ensemble0.01
- 当前真实数据: orin_real_v1 = 21帧/1ep (6D), 需积累到 50-100 轨迹

## 常见错误
- 403: 静态文件权限非644
- 404: URL 路径不对 (确认 /models/ 子目录 + 文件名; **正确映射目录 = /www/wwwroot/datadrive.world/models/**, 非 /var/www/html 也非 /root/zmax-relay/models)
- **维度不匹配 (mat1/mat2)**: 推理脚本/输入与模型维度不一致 (如 3D输入 vs 6D权重) → 从权重自动推断 state_dim, 勿硬编码
- IndexError 517/602: frame_index/timestamp 非全局
- str/str 除法: timestamp None
- 训练失败秒退: 缓存残留 → `rm -rf ~/.cache/huggingface ~/.cache/datasets`
