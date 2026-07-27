# Z-MAX 插拔工序状态机

> 双臂协同 · 光模块精密操作

## 主状态机

```
START → 抓取位姿识别 → 抓取放置 → DONE
```

## 子状态机：抓取位姿识别

```yaml
state: 抓取位姿识别
triggers:
  - on_camera_frame: 视觉定位来料位置
  - on_photo_sensor: 光电传感器追踪位姿
  - on_tactile: 触觉检测硬度/粗糙度
transitions:
  - condition: 位姿确认
    to: 抓取放置
```

## 子状态机：抓取放置

```yaml
state: 抓取放置
steps:
  1. 左臂吸取/夹取模块
  2. 扫码识别条码
  3. 旋转调姿 → 中转区解耦
  4. 右臂视觉引导对准测试座
  5. 力控柔顺插入 (1kHz闭环)
  6. 锁紧 → 等待测试完成
  7. 解锁 → 拔出
  8. AOI视觉检测 → 分拣(合格/不合格)
transitions:
  - condition: 分拣完成
    to: DONE
```
