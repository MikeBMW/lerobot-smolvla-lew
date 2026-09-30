# 硬件数据 API (供 Web 前端使用)

> 小芳提供 · @web 直接调用

## Orin Gateway

```javascript
// 实时关节数据
const joints = await fetch("http://192.168.23.10:8765/joints").then(r => r.json());
// → {joints: [6D], ts: timestamp}

// 健康检查
const health = await fetch("http://192.168.23.10:8765/health").then(r => r.json());
// → {online: bool, age_s: float}
```

## 静态数据文件 (GitHub Raw)

| 数据 | URL | 用途 |
|------|-----|------|
| 硬件树 | `docs/web/hardware-tree.json` | 设备拓扑 |
| L2/L3/L4规格 | `docs/web/hardware-spec-L2-L3-L4.json` | 产品对比 |
| 状态快照 | `docs/web/robot-status.json` | 页面默认加载 |
| 健康状态 | `docs/web/hardware-health.json` | 仪表盘 |

## GUI → Web 功能映射

| GUI 功能 | Web 页面 | 数据源 |
|:---:|:---:|------|
| 首页 | index.html | 静态 |
| 数据集 | datasets.html | GitHub |
| 硬件树 | hardware.html | hardware-tree.json |
| 实时监控 | monitor.html | Orin Gateway :8765 |
| 实时波形 | waveforms.html | Orin Gateway :8765 |
| 系统架构 | architecture.html | 静态 |
| 配置中心 | config.html | 静态 |
| 版本信息 | version.html | Git API |
