# Orin 真机料仓工序 YAML 解析

> 2026-07-12 · 小芳现场采集

## 主流程

```
抓取位姿识别 → 抓取放置 → done
     (可选: 识别下料盘位置)
```

## 抓取位姿识别 Pipeline

```
1. JointAndPoseServer  → 获取当前位姿
2. QuatAndEuler (q2e)  → 四元数→欧拉角
3. MechVisionClient     → 192.168.23.26
4. QuatAndEuler (e2q)  → 欧拉角→四元数
5. CollectionResponse   → 返回
```

## 抓取放置工序 (state_machine.yaml)

30个YAML文件, 16个工序节点:

```
初始化循环 → 取料 → 扫码 → AOI_1~6 → 插入(含力控)
→ 等待测试结果 → OK/NG分支 → 拔出 → 循环
```

容错机制:
- 抓取失败 → 开爪重试 → 连续失败报错
- 插入失败 → 二次尝试
- AOI NG → 跳NG分支

## 关键接口

| 组件 | 地址 | 功能 |
|------|------|------|
| 控制器 | 192.168.23.160 | 珞石 xCore |
| Orin | 192.168.23.10 | ROS2 主控 |
| Mech-Mind | 192.168.23.26 | 3D 视觉 |
| Mac | 192.168.23.1 | 监控 |
