# Z-MAX 共享知识区 V1.0 终版 (2026-07-12)

> 静界科技 · 三人协作协议 | 由总工静静维护

## 一、团队

| 成员 | 角色 | 环境 | 仓库分支 | SSH/端口 |
|:--|:--|:--|:--|:--|
| **静静** | 总工·架构 | WSL RTX4060 8G | main ↓ | localhost |
| **web** | 前端·训练 | AutoDL 4090 24G | web → PR | 106.75.239.80:23 |
| **小芳** | 硬件·端侧 | Mac M1 | mac → PR | 10.163.148.52:8080 |

## 二、仓库

| 仓库 | GitHub | 用途 |
|:--|:--|:--|
| GUI | MikeBMW/lerobot-smolvla-lew | 模型+文档+训练 |
| Web | MikeBMW/zmax-website | 网站前端 (web维护) |

## 三、服务器

| 服务器 | IP | 用途 | 关键命令 |
|:--|:--|:--|:--|
| ECS | 39.102.211.79 | Web+Nginx+MySQL | `systemctl start nginx` |
| 4090 | 106.75.239.80 | Sys-2推理+训练 | `ssh -p 23 root@...` |
| Orin | 192.168.23.10 | 端侧部署 | 小芳维护 |

## 四、产品架构

```
Z-MAX 五层引擎:
Sys-0 L2 规则引擎 Orin Nano
Sys-1 L3 ACT/VTLA 4060+4090
Sys-11 L4 smolvla 4060
Sys-12 L4 smolvla_lew 4060
Sys-2 云端 Hermes Agent 4090
```

## 五、关键参数

| 模型 | 参数 | 延迟 | 显存 |
|:--|--:|--:|--:|
| ACT | 52M | 1.2ms | 0.26G |
| smolvla | 450M | 215ms | 0.90G |
| smolvla_lew | 628M | 186ms | 2.06G |
| LeWorldModel | 5.5M | 1.9ms | 0.03G |
| VTLA(4090) | 450M | 280ms | 2.1G |

## 六、命名规范

- Python: `ZmaxSys{N}Policy`
- 目录: `zmax_sys{n}/`
- 显示: `Z-MAX Sys-{N}`

## 七、Web页面

```
/                   = index.html (暗色主页)
/autonomous.html    = 自主系统
/simulation.html    = 仿真报告(含VTLA联调)
/patent.html        = 专利技术
/survey.html        = 用户调研
/monitor.html       = 实时监控
/docs.html          = 文档中心
/hardware-tree.html = 硬件树
/neuromorphic.html  = 类脑计算
```

## 八、运维要点

- ECS重启后: `systemctl start nginx`
- Nginx主页规则: `location = / { try_files /index.html =404; }`
- 4090 Sys-2端口: 50052, 端点 /health /predict
- 飞书web: 4090端口18080, WebSocket
- Git push超时: 正常现象, commit已保存
