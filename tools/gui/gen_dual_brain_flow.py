#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成「双脑 + 状态机」插拔模型 Simulink Flow JSON — 飞书端跑通方案 v1.0
来源: 用户方案 JSON (2026-08-10): 抓起8/8 插入7/8 超越官方专家
输出: flows/dual_brain_peg.json
"""
import json, os

def mk_id(p, i):
    return f"db{p}{i}"

nodes, links = [], []
def add_node(p, i, ntype, name, x, y, params, w=150):
    nodes.append({
        "id": mk_id(p, i), "type": ntype, "name": name, "x": x, "y": y, "w": w,
        "icon": {"hardware": "▣", "row_bg": "▤", "model": "◈", "condition": "❖",
                 "system": "◉", "action": "➤", "data": "📊", "pdf_report": "📄"}[ntype],
        "color": {"hardware": "#ff4444", "row_bg": "#3a3f4b", "model": "#58a6ff",
                  "condition": "#a371f7", "system": "#d4a800", "action": "#00d4aa",
                  "data": "#58a6ff", "pdf_report": "#1f6feb"}[ntype],
        "params": params,
        "inputs": [{"id": "in1", "label": "in", "dtype": "any"}],
        "outputs": [{"id": "out1", "label": "out", "dtype": "any"}],
        "actions": [],
    })
    return mk_id(p, i)
def add_link(f, t, label=None):
    links.append({"id": f"l{abs(hash(f+t))%10**14}", "f": f, "t": t,
                  "f_port": "out1", "t_port": "in1", "label": label})

BASE_X, BASE_Y, COL_W, ROW_H, BG_H = 140, 80, 240, 230, 214

# ── 行1: 双脑 (感知·决策) ──
y0 = BASE_Y
obs   = add_node("a", 0, "data",      "📊 39D obs 输入", BASE_X + 0*COL_W, y0,
                 {"dim": 39, "source": "metaworld peg-v6", "desc": "完整观测: 坐标+速度+相对向量 (YOLO 3D 产出)"})
left  = add_node("a", 1, "model",     "🧠 左脑 MLP", BASE_X + 1*COL_W, y0,
                 {"role": "连续动作生成", "in_dim": 39, "out_dim": 4,
                  "structure": "3层MLP 512隐藏 (ExpertMLP结构)",
                  "bias": "act*0.3 + hand→peg方向*2.0",
                  "loss": "MSE 800 epoch", "seed": 42,
                  "desc": "左脑: 39D obs → 4D 动作 (3D速度+夹爪)。偏置接近比纯解析强 (5/8 vs 0/8)"})
right = add_node("a", 2, "model",     "🧠 右脑 WorldModel", BASE_X + 2*COL_W, y0,
                 {"role": "抓取时机判断", "in_dim": "39D obs + 4D action",
                  "out_dim": "next obs + contact概率", "contact_acc": "1.00",
                  "loss": "BCE 800 epoch", "seed": 42,
                  "trigger": "contact>0.5 且 d_hp<0.06 → 夹持触发",
                  "desc": "右脑: 预测 next obs + contact 二分类 (该抓了吗)"})
touch = add_node("a", 3, "condition", "❖ 接触判定", BASE_X + 3*COL_W, y0,
                 {"rule": "contact>0.5 & d_hp<0.06", "d_hp_th": 0.06,
                  "desc": "右脑 contact 概率 + 钳口-销钉距离 联合判定 → 触发抓取"})

# ── 行2: 状态机 (执行) ──
y1 = BASE_Y + ROW_H
sm    = add_node("b", 0, "system",    "◉ 状态机 (6阶段)", BASE_X + 0*COL_W, y1,
                 {"stages": ["接近", "抓取", "抬起", "转移", "插入", "完成"],
                  "frames": "32+45+9+38+1 = 125帧", "desc": "接近→抓取→抬起(+8cm)→转移(容差5cm)→插入→完成"})
st_ap = add_node("b", 1, "action",    "➤ 接近", BASE_X + 1*COL_W, y1,
                 {"target": "d_hp 0.2→0.06", "desc": "左脑MLP偏置接近 (32帧)"})
st_gr = add_node("b", 2, "action",    "➤ 抓取", BASE_X + 2*COL_W, y1,
                 {"trigger": "contact>0.5 & d_hp<0.06", "grab": "夹持0.6 + 位置锁定",
                  "desc": "右脑判定触发 (45帧)"})
st_li = add_node("b", 3, "action",    "➤ 抬起", BASE_X + 3*COL_W, y1,
                 {"height": "+8cm", "force": 0.8, "desc": "peg z 升高避开台面 (9帧)"})
st_mv = add_node("b", 4, "action",    "➤ 转移", BASE_X + 4*COL_W, y1,
                 {"tolerance": "5cm", "desc": "水平移到 hole 上方, peg 有导向 (38帧)"})
st_in = add_node("b", 5, "action",    "➤ 插入", BASE_X + 5*COL_W, y1,
                 {"target": "d_ph<0.05", "desc": "垂直下降插入 (1帧)"})
st_ok = add_node("b", 6, "action",    "➤ 完成", BASE_X + 6*COL_W, y1,
                 {"desc": "✅ 插拔完成"})

# ── 行3: 对比 (成绩) ──
y2 = BASE_Y + 2*ROW_H
ours  = add_node("c", 0, "system",    "🎉 双脑+状态机", BASE_X + 0*COL_W, y2,
                 {"grab": "8/8", "insert": "7/8", "rank": "超越官方专家",
                  "desc": "首个学习架构解决完整插拔 (抓起8/8 插入7/8)"})
exp   = add_node("c", 1, "system",    "◉ 官方专家", BASE_X + 1*COL_W, y2,
                 {"grab": "7/8", "insert": "7/8", "desc": "PD 控制律基准"})
sm_lr = add_node("c", 2, "system",    "◉ 纯状态机+学习", BASE_X + 2*COL_W, y2,
                 {"grab": "0/8", "insert": "0/8", "desc": "无学习"})
mlp   = add_node("c", 3, "system",    "◉ MLP蒸馏", BASE_X + 3*COL_W, y2,
                 {"grab": "6/10", "insert": "3/10", "desc": "纯回归无右脑"})
bc    = add_node("c", 4, "system",    "◉ 视觉BC模型", BASE_X + 4*COL_W, y2,
                 {"grab": "0/8", "insert": "0/8", "desc": "视觉BC全部失败"})

# ── 行3.5: 交付 (可运行节点 — 双击直接生成视频/PDF, 2026-08-10) ──
y3 = BASE_Y + 3*ROW_H
vid = add_node("d", 0, "action",     "▶ 生成插拔视频", BASE_X + 0*COL_W, y3,
               {"insert_video": True, "seed": 1,
                "out": "reports/insert_success_demo.mp4",
                "desc": "双击运行: 后台录制 seed1 完整插拔流程 → 旋转180° → mp4 → 自动发飞书 (约1-2分钟)"})
pdf = add_node("d", 1, "pdf_report", "📄 PDF 插拔方案报告", BASE_X + 1*COL_W, y3,
               {"insert_report": True,
                "out": "reports/插拔方案报告_<时间戳>.pdf",
                "desc": "双击运行: 方案JSON+视频帧 → 6章方案PDF → 自动发飞书"})
# 成绩行背景 + 头注
bg0 = add_node("bg", 0, "row_bg", "🎨 双脑", BASE_X - 160, y0 - 20,
               {"bg": "#3a4a5a", "model": "双脑", "desc": "背景行: 左脑动作生成 + 右脑时机判断"}, w=4*COL_W - COL_W + 150 + 200)
bg1 = add_node("bg", 1, "row_bg", "🎨 状态机", BASE_X - 160, y1 - 20,
               {"bg": "#3a5a3a", "model": "状态机", "desc": "背景行: 6阶段执行链"}, w=7*COL_W - COL_W + 150 + 200)
bg2 = add_node("bg", 2, "row_bg", "🎨 对比", BASE_X - 160, y2 - 20,
               {"bg": "#5a4a3a", "model": "对比", "desc": "背景行: 五方案成绩"}, w=5*COL_W - COL_W + 150 + 200)
bg3 = add_node("bg", 3, "row_bg", "🎨 交付", BASE_X - 160, y3 - 20,
               {"bg": "#2d4a5a", "model": "交付", "desc": "背景行: 一键生成演示视频 + 方案PDF"}, w=2*COL_W - COL_W + 150 + 200)
for n in nodes:
    if n["type"] == "row_bg":
        n["h"] = BG_H

# ── 连线: 数据流 + 状态链 ──
add_link(obs, left, "39D obs")
add_link(obs, right, "39D obs")
add_link(left, right, "4D action")
add_link(left, sm, "4D 动作")
add_link(right, touch, "contact概率")
add_link(touch, sm, "抓取触发")
add_link(obs, sm, "观测")
chain = [sm, st_ap, st_gr, st_li, st_mv, st_in, st_ok]
for i in range(len(chain) - 1):
    add_link(chain[i], chain[i+1], ["接近", "抓取", "抬起", "转移", "插入", "完成"][i])
add_link(st_ok, ours, "🎉 8/8 · 7/8")
# 对比行: 我方 vs 各基准 (2026-08-10 修复: 4 个对比节点原来无连线=离散节点)
add_link(ours, exp, "持平 7/8")
add_link(ours, sm_lr, "8/8 vs 0/8")
add_link(ours, mlp, "7/8 vs 3/10")
add_link(ours, bc, "8/8 vs 0/8")
# 交付链: 完成 → 视频 → PDF (可运行节点)
add_link(st_ok, vid, "插拔成功")
add_link(vid, pdf, "演示视频")
add_link(pdf, ours, "成绩入报告")

flow = {
    "format": "hermes-flow",
    "version": 1,
    "name": "🧠 双脑 + 状态机 = 完整插拔",
    "sim": "dual_brain_peg",
    "nodes": nodes,
    "links": links,
}
out = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "flows", "dual_brain_peg.json"))
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(flow, f, ensure_ascii=False, indent=1)

# 校验
NODE_TYPES_OK = {"condition","data","model","action","system","hardware","switch",
                 "train_gate","yolo_gate","coord_overlay","row_bg","pdf_report","skill","scene"}
assert set(n["type"] for n in nodes) <= NODE_TYPES_OK
nids = {n["id"] for n in nodes}
assert all(l["f"] in nids and l["t"] in nids for l in links)
for bg in [n for n in nodes if n["type"] == "row_bg"]:
    nm = bg["name"].replace("🎨 ", "")
    assert len(nm) <= 8, f"背景名超8字: {nm}"
    ry = bg["y"] + 20
    rn = [n for n in nodes if n["type"] != "row_bg" and abs(n["y"] - ry) < 40]
    xs = sorted(n["x"] for n in rn)
    assert min(xs) >= bg["x"] + 160, f"{nm} 节点x越界"
    assert all(xs[i+1] - xs[i] >= 150 for i in range(len(xs) - 1)), f"{nm} 重叠"
print(f"✅ 已生成: {out}")
print(f"   节点 {len(nodes)} (model {sum(1 for n in nodes if n['type']=='model')}, action {sum(1 for n in nodes if n['type']=='action')}, system {sum(1 for n in nodes if n['type']=='system')}, condition {sum(1 for n in nodes if n['type']=='condition')}, data {sum(1 for n in nodes if n['type']=='data')}, pdf_report {sum(1 for n in nodes if n['type']=='pdf_report')}, row_bg {sum(1 for n in nodes if n['type']=='row_bg')})")
print(f"   连线 {len(links)}")
