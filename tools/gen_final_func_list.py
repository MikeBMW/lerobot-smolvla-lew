#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_final_func_list.py — 最终功能清单生成器 (2026-09-05 老倪)

整合三维度: 功能节点(域) × 硬件域(感知=摄像头/动作=珞石臂/闭环) × 波形验证通道
(引擎轨迹 → 可视化层窗口: 📊仿真波形/🧠激活波动/🧭3D/🎯归因 — 脑机接口式统一验证)
→ reports/最终功能清单_硬件与波形整合.md
"""
import os
import sys

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "verification"))
import node_func_tree as nft

HW_CAM, HW_ARM, HW_BOTH, HW_DATA, HW_SOFT = (nft.HW_CAM, nft.HW_ARM, nft.HW_BOTH,
                                             nft.HW_DATA, nft.HW_SOFT)
SHORT = {HW_CAM: "感知·摄像头", HW_ARM: "动作·珞石臂", HW_BOTH: "感知+动作闭环",
         HW_DATA: "数据", HW_SOFT: "决策/软件"}


def main():
    L = []
    L.append("# ZFCY Z-MAX · 最终功能清单 — 硬件 × 功能 × 波形验证整合")
    L.append("")
    L.append("> 生成 2026-09-05 · 场景 = **光模块插拔** (代码/任务名含 peg 者为历史标识符, 业务对象=光模块)")
    L.append(">")
    L.append("> **整合逻辑**: 感知类功能挂 📷摄像头硬件, 动作类功能挂 🦾珞石机械臂硬件, 闭环功能两者皆有;")
    L.append("> 全部功能的验证统一在**波形/可视化**(脑机接口式: 引擎六层信号 → 可视化层窗口),")
    L.append("> 测试用例跑的是引擎真实数值, 波形就是每个功能的实时证据 → 硬件可溯源。")
    L.append("")
    L.append("## 一、硬件资产")
    L.append("")
    L.append("| 域 | 硬件 | 关联功能节点 |")
    L.append("|---|---|---|")
    rows_hw = {"感知 · 📷摄像头 (Z700 视觉/相机: YOLO 检出→2D→3D)": ["sssensor", "ssyolo", "ss2d3d", "sstactile", "ssaoi", "ssobs", "ssmani_c", "ssmani_p"],
               "动作 · 🦾珞石机械臂 (执行器: 位姿/速度/夹爪)": ["ssact", "ssworld", "sssched", "sslimit", "ssobs", "ssmani_c", "ssmani_p"],
               "闭环 (感知→决策→动作)": ["ssff", "ssest", "sspred", "ssinnov", "sslat", "sscalib", "sstactile"]}
    L.append("| 📷 感知 (视觉硬件) | 摄像头 (Z700 相机) | sssensor · ssyolo · ss2d3d · ssaoi · sstactile |")
    L.append("| 🦾 动作 (运动硬件) | 珞石机械臂 (6 轴 + 夹爪) | ssact · ssworld · sssched · sslimit |")
    L.append("| 🔄 闭环 | 摄像头 ↔ 珞石臂 (含触觉/力反馈) | ssobs · ssff · ssest · sspred · ssinnov · sslat · sscalib · ssmani_c · ssmani_p |")
    L.append("")
    L.append("## 二、功能节点 × 硬件 × 波形验证通道 (22 节点)")
    L.append("")
    L.append("| 节点 | 功能域 | 硬件域 | 波形验证通道 (测试看这里) | 功能/用例数 |")
    L.append("|---|---|---|---|---|")
    total_f = total_t = 0
    hw_cnt = {}
    for k, nd in nft.NODE_TREE.items():
        hw, viz = nft.NODE_HW_VIZ.get(k, ("—", "—"))
        nf = len(nd["funcs"])
        nt = sum(len(f.get("tests", [])) for f in nd["funcs"])
        total_f += nf
        total_t += nt
        hw_cnt[SHORT.get(hw, "?")] = hw_cnt.get(SHORT.get(hw, "?"), 0) + 1
        L.append(f"| {nd.get('name','?')} | {k} | {SHORT.get(hw,'?')} | {viz} | {nf}/{nt} |")
    L.append("")
    L.append(f"合计: 22 节点 · {total_f} 功能 · {total_t} 用例 | 硬件分布: "
             + " · ".join(f"{k} {v} 节点" for k, v in hw_cnt.items()))
    L.append("")
    L.append("## 三、波形 = 统一的'脑机接口'验证面 (所有功能的实时证据)")
    L.append("")
    L.append("| 可视化窗口 | 验证什么 (波形通道 → 功能) |")
    L.append("|---|---|")
    L.append("| 🧠 前馈激活波动 | 每层能量/激活变化事件波形, 阶段色带(8阶段), 插入尖峰 — ssff 决策/sssched 阶段/全流程 |")
    L.append("| 📊 仿真波形 | 距离/前馈/残差/接触概率/法向偏离/插深剩余/横向错位(0.5mm线) — 感知-估计-动作闭环各功能 |")
    L.append("| 🧭 3D 视图 | 机械臂/光模块/孔 YOLO 检出层/坐标 — 感知硬件的空间证据 |")
    L.append("| 🎯 归因视图 | 512 单元分工 (PCA/t-SNE) — 模型内部功能归属 |")
    L.append("| 🎥 操作视频 | 真机/仿真操作对比 — 最终动作证据 |")
    L.append("")
    L.append("**验证闭环**: 测试用例(auto 断言)跑引擎真实数值 → 同一轨迹同时驱动波形窗口 →")
    L.append("波形显示的就是该功能在动作里的实时表现 → 测试=看波形可测到功能, 硬件可溯源(感知查摄像头链路, 动作查珞石臂链路)。")
    L.append("")
    L.append("## 四、关键验收 (唯一指标, FNaccept01)")
    L.append("")
    L.append("- 插入成功 12/12 扰动集 · 插入段 <0.5s · 末横向错位 <0.5mm · 插深到底 <0.5mm")
    L.append("- 波形证据: 📊仿真波形 底部验收摘要 + 插深剩余/横向错位 0.5mm 红线; 🧠波动视图 插入段金色高亮+✅")
    L.append("- 硬件证据: 感知=摄像头检出(3D YOLO 层), 动作=珞石臂轨迹(3D 机械臂层)")
    L.append("")
    md = "\n".join(L)
    out = os.path.join(ROOT, "reports", "最终功能清单_硬件与波形整合.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    # 终端摘要
    print(md)
    print(f"\nMD={out}")


if __name__ == "__main__":
    main()
