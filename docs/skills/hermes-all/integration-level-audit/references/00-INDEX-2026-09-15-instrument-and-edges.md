# 2026-09-15 新增 (仪器自检 + 逐边审计) — 索引

SKILL.md 的指针本轮未能写入 (read-before-write 守卫拒绝, 见交付说明), 先在此登记新增支持文件,
**下次维护时请把下面两行补进 SKILL.md 的「逐边审计 / 证据仪器自检」小节与「参考」列表**:

- `references/instrument-selfcheck-and-edge-audit-2026-09-15.md`
  铁律 4 (逐位 hash 比对前先跑同配置对照臂对证仪器; 不确定则降级结构性判据) ·
  铁律 5 (采数/标定不能依赖"已就绪" → 没标定→没采数 死锁) ·
  铁律 6 (导出侧新字段必须核对消费侧白名单/拷贝) ·
  逐边判决表范式 (✅ 有数据 / ⚠️ 未接管 / ❌ 死线 / ❓ 未登记; 先框定行; 交代运行模式;
  `n_nonzero` 才算数; "物理为零"≠"没接上")。
- `scripts/zero_regression_arms.py`
  臂隔离零回退 A/B 骨架: 先 `--control` 跑同配置对照臂对证仪器; 仪器确定用 hash 判据,
  否则自动降级为"两臂新代码进入计数都为 0"。改 CONFIG (RUNNER/SCENES/ARM_ENV/审计字段) 即可复用。

## 本轮新增的判定桶速查 (给未来会话直接抄)

| 桶 | 判据 |
|---|---|
| ✅ 有数据 | 运行时计数 > 0 且逐帧列 `n_nonzero` > 0 |
| ⚠️ 通道在跑未接管 | 真前向有计数, 注入权重 0 / 未过闸 |
| ❌ 死线 | 无任何运行时消费者 → 直说 + 给"为什么/怎么补" |
| ❓ 未登记 | 审计表没写 → 视为未审计, 不许算通过 |

配套 (本仓落点): `tools/audit_l4_edges.py` (判决表) · `tools/verify_fiber_zero_regression.py`
(带仪器自检的零回退) · `tools/probe_l4_callchain.py` (审计 json 生产 + 正对照场景 micro/L3/L4line/L4audit)。
