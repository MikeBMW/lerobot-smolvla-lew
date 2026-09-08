# Z-MAX Simulink 模型开发 · CI/CD 设计 (v1.0)

> 参考: MathWorks《Simulink 模型验证之持续集成》
> 管道核心 = 验证 → 构建 → 测试 → 部署, 分布式资源编排 (资源受限版)

## 1. 资源拓扑 (我们有什么)

| 节点 | 角色 | 算力 | 在 CI/CD 中的职责 |
|------|------|------|------------------|
| 静静 4060 (WSL) | 开发机 | RTX 4060 8G | 本地开发 · 模型验证 · 小数据训练 smoke · GUI 测试 |
| GitHub Actions | 编排/CI | 免费 runner (Linux/Windows) | 全自动管道 · 构建 .exe · 静态检查 · 单测 · 发布 Release |
| web 4090 | 训练/推理 | 4090 24G | 大模型训练 · 云端推理服务 (50054/50056) |
| ECS 服务器 | 部署目标 | 2C4G | datadrive.world 网站 · PHP API · 中转 (50053) |
| Orin Nano | 边缘硬件 | 8G 模块 | 真机采集 · 端侧推理 · HIL 硬件在环测试 |
| 小芳 Mac | 采集桥 | M1 | Orin↔ECS 数据转发 · ROS2 中转 |

## 2. 管道设计 (对标 MathWorks 四阶段)

```
┌─ 触发: push main / PR / 打标签 v* / workflow_dispatch
│
├─ [1] 验证 (Validation) — 对标 Model Advisor
│    ├─ tools/ci/validate_flow.py  ← Simulink 工作流 JSON 标准合规检查
│    │    (节点类型/必填字段/连线引用/自环/重复/DAG无环/未连接节点)
│    ├─ ruff + bandit 静态检查 (quality.yml 已有)
│    └─ 硬件配置 schema 校验 (config yaml 合法性)
│
├─ [2] 构建 (Build) — 对标代码生成
│    ├─ GitHub Actions: .exe 打包 (build-win-exe.yml 已有)
│    └─ 训练镜像/依赖锁定 (uv.lock + Dockerfile 校验)
│
├─ [3] 测试 (Test) — 对标 Simulink Test 套件
│    ├─ pytest 单测 (fast_tests.yml 已有)
│    ├─ 4060 本地: 小数据训练 smoke (ACT 1 epoch) — 触发式
│    └─ Orin HIL: 真机心跳/采集联通性 (手动/定时)
│
└─ [4] 部署 (Deploy) — 对标 Embedded Coder 部署
     ├─ GitHub Release: .exe + 验证报告 (release.yml 已有)
     ├─ ECS: scp 网站/API (web 侧执行)
     └─ 飞书通知: dataworld 群推送管道结果 (webhook)
```

## 3. 关键设计决策 (资源受限)

1. **GitHub Actions 是编排中心** — 免费、可重跑、审计日志全。
   所有"无 GPU 需求"的阶段都在 Actions runner 上跑。

2. **GPU 阶段分派** (Actions 免费 runner 无 GPU):
   - 训练 smoke / 推理验证 → 4060 本地手动触发 (或 webhook)
   - 大训练 → web 4090 (ECS API 50053 中转)
   - HIL 真机 → Orin (小芳 Mac 桥接)

3. **模型 = 工作流 JSON** (simulink-spec.md v1.0):
   - 模型文件是 `flow.json` (nodes+links), 进 git 版本管理
   - CI 第一环就是 validate_flow.py 校验它 → 坏模型进不了构建
   - 对标 Simulink .slx 文件 + Model Advisor 的关系

4. **无 MATLAB 依赖** — 我们全程 Python 生态:
   - 不需要 MATLAB/Simulink 许可证
   - 验证器 validate_flow.py 纯 stdlib (json/sys), 零依赖可跑

5. **增量策略** — 每次 push 只跑 1+2 快速阶段 (~2min),
   3/4 阶段按标签/手动触发, 避免免费额度浪费。

## 4. 需要安装的依赖 (评估结论)

| 依赖 | 位置 | 状态 |
|------|------|------|
| 无 (validate_flow.py) | Actions runner | 纯 stdlib ✓ |
| python 3.11+ | Actions runner | 自带 ✓ |
| ruff/bandit | Actions runner | quality.yml 自动装 ✓ |
| pytest | Actions runner | fast_tests.yml 自动装 ✓ |
| PyQt5 | 4060 本地 | 已装 (pip3 --break-system-packages) ✓ |
| torch + deps | 4060 本地 .venv | 安装中 (阿里云镜像) ⏳ |
| sshpass/scp | ECS 部署侧 | web 已有 (记忆: ECS密码 Nix19789) ✓ |

**结论: 无需新增任何依赖。** CI/CD 全部复用现有 Actions workflow +
stdlib 验证器 + 现有节点工具。

## 5. 落地文件

| 文件 | 用途 |
|------|------|
| tools/ci/validate_flow.py | 模型标准合规验证器 (Model Advisor 对标) |
| .github/workflows/ci-cd.yml | 主管道 (验证→构建→测试→通知) |
| simulink-spec.md | 模型 JSON 规范 (已与 web 同步) |

## 6. 扩展路径

- 覆盖率报告: pytest-cov → Actions artifact → GitHub Pages
- 自动部署: Actions → sshpass 直推 ECS (需 web 授权)
- 飞书通知: curl 调飞书 webhook (web 的 App ID 已配)
- Orin HIL: Actions 定时触发 ECS 心跳 API 检查 (每15分钟 sys-watchdog 已有)
