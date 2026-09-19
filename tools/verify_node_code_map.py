#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_node_code_map.py — 画布节点 ↔ 真实代码/数据 对齐审计

判据: 每个(非背景带)节点必须能指向一处真实存在的实现 ——
  (a) 显式骨干映射 BACKBONE[node_id] = "文件:符号/话题/产物"
  (b) 规则匹配: params.source / params.real / params.file / 关键词→已知模块
背景带(row_bg)/装饰节点不参与。
输出: 映射表 + 未对齐(phantom)清单 + 计数
"""
import json, os, re, sys

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BACKBONE = {
    "ss2d3d": "tools/perception_chain_real.py:pixel_to_board",
    "n_dsvl": "tools/perception_chain_real.py:ask_deepseek_vl",
    "n_vlm_llm": "tools/perception_chain_real.py:ask_deepseek_vl",
    "n_board_frame": "tools/board_frame_module.py:build_board_frame",
    "n_l2_muscle": "data/skills/l2_atomic/registry.json + tools/l2_daemon.py",
    "n_eng_mem": "data/skills/l2_muscle/",
    "ssff": "tools/gui/state_space_sim_real.py:前馈MLP(SS_USE_MLP)",
    "ssdec": "tools/gui/state_space_sim_real.py:DiT动作头",
    "sssched": "tools/gui/state_space_sim_real.py:decide(动作调制, 唯一出口)",
    "ssact": "tools/l2_daemon.py -> Orin /move_joint|/move_line|/gripper_driver",
    "ssvideo": "tools/gui/gen_state_space_video.py",
    "ssvideo2": "tools/gui/gen_state_space_video.py",
    "ssmode": "tools/gui/studio.py (训练/推理 模式切换)",
    "sscap": "tools/gui/node_logic.py (能力档位/可行域收缩)",
    "ssintact": "tools/gui/state_space_sim_real.py:INTACT策略",
}

KEY = [
    ("yolo", "models/yolo_peg_live.pt -> runs/detect/outputs/yolo_annot/*/weights/best.pt"),
    ("deepseek", "tools/perception_chain_real.py:ask_deepseek_vl"),
    ("vl", "tools/perception_chain_real.py:ask_deepseek_vl"),
    ("skill", "tools/gui/l2_skill_dialog.py + data/skills/l2_atomic/registry.json"),
    ("技能", "tools/gui/l2_skill_dialog.py + data/skills/l2_atomic/registry.json"),
    ("记忆", "data/skills/l2_muscle/*.json"),
    ("muscle", "data/skills/l2_muscle/*.json"),
    ("状态", "src/lerobot/policies/left_right/state_space/"),
    ("obs", "src/lerobot/policies/left_right/state_space/"),
    ("intact", "src/lerobot/policies/left_right/state_space/intact"),
    ("流形", "src/lerobot/policies/left_right/state_space/manifold"),
    ("校准", "tools/real_handeye_calib.py / data/handeye/"),
    ("相机", "tools/perception_chain_real.py (tap cam_rs.png)"),
    ("标定", "tools/board_frame_module.py"),
    ("aoi", "tools/aoi_call.py -> 192.168.23.23:10082/10083"),
    ("金手指", "tools/aoi_call.py -> 192.168.23.23:10082"),
    ("安全", "src/lerobot/policies/left_right/state_space/limits"),
    ("执行器", "tools/l2_daemon.py"),
]


def main():
    flow = json.load(open(os.path.join(R, "flows/state_space_obs.json"), encoding="utf-8"))
    mapped, phantom = {}, []
    for n in flow["nodes"]:
        nid = n["id"]; nm = n.get("name", ""); p = n.get("params") or {}
        t = n.get("type", "")
        if t == "row_bg" or nm.strip() == "":
            continue
        ev = BACKBONE.get(nid)
        if not ev:
            for k in ("source", "file", "artifact"):
                if p.get(k):
                    ev = str(p[k]); break
        if not ev and p.get("real"):
            ev = "真机链路(见 tools/perception_chain_real.py)"
        if not ev:
            low = (nid + " " + nm).lower()
            for k, v in KEY:
                if k in low:
                    ev = v; break
        if ev:
            mapped[nid] = ev
        else:
            phantom.append((nid, nm[:40], t))
    print("节点总数(去掉背景带):", len(mapped) + len(phantom))
    print("已对齐:", len(mapped))
    print("未对齐(phantom):", len(phantom))
    for x in phantom[:15]:
        print("   ✗", x)
    # 真实存在性抽检: 骨干映射里的文件是否存在
    bad = []
    for nid, ev in BACKBONE.items():
        m = re.match(r"([^ :]+)", ev).group(1)
        if not os.path.exists(os.path.join(R, m)):
            bad.append((nid, m))
    print("骨干映射指向文件缺失:", bad if bad else "无 ✓")
    return 0 if not phantom else 1


if __name__ == "__main__":
    sys.exit(main())
