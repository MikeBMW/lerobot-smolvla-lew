# Z-MAX 全局数据空间 (dds.db) 更新流程

> 2026-08-02 · 数据闭环全景 v4.0 后统一口径。老倪:"更新全局数据空间" = 更新 dds.db 并同步 ECS, 全站数据空间页面自动反映。

## 库位置与结构
- 本地: `/home/xspace/zmax-website/dds.db` (web 维护, 但 xspace 可更新)
- 线上: scp 到 ECS `/www/wwwroot/datadrive.world/dds.db`
- API: `https://datadrive.world/api/dds-all.php` (读全库 JSON, 网站数据空间页面数据源)
- 17 表: company/kpi/robots/systems/models/hardware/factory_zones/factory_meta/roadmap/theme/dds_skills/links/pipeline/atomic_skills(242行)/proposal/changelog

## 更新步骤 (实测)
1. 写脚本 `update_dds_loop.py`: DELETE 目标表 + executemany INSERT (幂等)
2. `python3 update_dds_loop.py` 本地跑
3. `sshpass -p 'Nix19789' scp dds.db root@39.102.211.79:/www/wwwroot/datadrive.world/dds.db`
4. 验证 API: `curl https://datadrive.world/api/dds-all.php | python3 -c "import sys,json; d=json.load(sys.stdin); ..."`
   - 注意: pipeline 在 API 里是 **list**, kpi 是 **dict** (key=id) — 遍历方式不同

## 数据闭环统一口径 (2026-08-02 v4.0)
- pipeline 5 环节: 采集(Orin 20s)→上传(ECS)→训练(4060 ACT 150s)→部署(静态URL→Orin)→推理(0.5s)
- kpi 实测: infer_lat=479ms (v2真机), loop_cycle=<5min (采集→部署), 保留 precision/yield_rate/cycle_time
- models 新增: ACT_6D (真机6D关节, 957帧, loss 1.543, 静态URL部署)
- changelog 是**字段级审计表**: 列 = id/ts/table_name/key_name/field_name/old_value/new_value (无 ver 列! 别按常见 ver/msg 结构写)

## 文档基准 (三体一致)
- **唯一基准**: `docs/ZMAX-DATA-LOOP-OVERVIEW.md` (v4.0) — 开发流程/场景/功能/数据流定义
- 旧文档 (DATA-FLYWHEEL.md / ARCHITECTURE-OVERVIEW.md) 已标记指向基准, 保留历史
- 任何环节改动必须同步该文件, 保证三体(静静/小芳/web)逻辑、数据一致

## 陷阱
- changelog 表无 `ver`/`msg` 列 → 按字段级审计插入 (table_name/key_name/field_name/new_value)
- 表结构先 `PRAGMA table_info(<t>)` 确认再写脚本
- API 的 pipeline 是 list 不是 dict → `.values()` 会 AttributeError
