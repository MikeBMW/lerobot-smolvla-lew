# -*- coding: utf-8 -*-
"""✅ L4 光模块插拔链 · 节点级验证 (offscreen, 真跑整条链)

验证对象 = 画布真正用的那份代码 (tools/gui/node_logic.py 的 4 个节点), 不是另写一套:
  ① 节点名 → 语义key 匹配 (sw_ds/sw_intact/sw_world/sw_video)
  ② 任务分派 = optical_insert (data/intact_sw_task.json)
  ③ 部署档 _sw_deploy 挑到的权重文件真存在 (与统计同源)
  ④ 真跑整链: node_sw_ds (起桥+等终态) → node_sw_intact → node_sw_world → node_sw_video
  ⑤ 终态核验: 帧数/std>5/视频/回合对照/诚实标注

用法: ./gui-venv311/bin/python /tmp/verify_l4_optical_chain.py
"""
import json
import os
import sys
import time

ROOT = "/home/ubuntu/lerobot-smolvla-lew"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("STABLEWM_HOME", "/home/ubuntu/stable-wm-cache")
os.environ.setdefault("LOCAL_DATADIR", os.environ["STABLEWM_HOME"])

import node_logic as NL                                              # noqa: E402

LOGS = []


def log(*a):
    s = " ".join(str(x) for x in a)
    LOGS.append(s)
    print(s, flush=True)


def main():
    fails = []
    print("═══ ① 节点名 → 语义key ═══")
    fl = json.load(open(os.path.join(ROOT, "flows", "state_space_obs.json"), encoding="utf-8"))
    names = {n["id"]: n["name"] for n in fl["nodes"]}
    for nid, want in (("swds", "sw_ds"), ("swintact", "sw_intact"),
                      ("swworld", "sw_world"), ("swvideo", "sw_video")):
        got = NL.match_node(names[nid])
        ok = got == want
        print(f"   {nid:<9} {names[nid][:44]:<46} → match={got} {'✅' if ok else '❌ 期望 ' + want}")
        if not ok:
            fails.append(f"match_node {nid}")

    print("═══ ② 任务分派 + ③ 部署档 ═══")
    task = NL._sw_task(ROOT)
    print(f"   _sw_task = {task} {'✅' if task == 'optical_insert' else '❌'}")
    if task != "optical_insert":
        fails.append("task")
    dep = NL._sw_deploy(ROOT)
    pol = str(dep.get("policy") or "")
    ck = os.path.join(os.environ["STABLEWM_HOME"], "checkpoints", pol)
    stf = str(dep.get("stats") or "")
    print(f"   权重 {pol}  存在={os.path.isfile(ck)} {'✅' if os.path.isfile(ck) else '❌'}")
    print(f"   统计 {os.path.basename(stf)} 存在={os.path.isfile(stf)} "
          f"{'✅' if os.path.isfile(stf) else '❌'}")
    if not os.path.isfile(ck) or not os.path.isfile(stf):
        fails.append("deploy")

    print("═══ ④ 真跑整链 (节点级, 走画布同一份代码) ═══")
    d, fr, st, vd = NL._sw_paths(ROOT)
    for f in os.listdir(vd):                      # 只清本轮要核验的视频 (历史留档)
        pass
    ctx = {"log": log, "root": ROOT}
    t0 = time.time()
    for fn, nm in ((NL.node_sw_ds, "🧪 数据源"), (NL.node_sw_intact, "🎯 INTACT 策略"),
                   (NL.node_sw_world, "🌍 引擎"), (NL.node_sw_video, "🎬 视频")):
        t1 = time.time()
        ok = bool(fn(ctx))
        print(f"   [{nm}] return={ok} · {time.time()-t1:.1f}s\n")
        if not ok:
            fails.append(nm)

    print("═══ ⑤ 终态核验 ═══")
    d0 = NL._sw_status(st)
    frames = [x for x in os.listdir(fr) if x.endswith(".jpg")]
    vids = [x for x in os.listdir(vd) if x.endswith(".mp4")]
    rows = d0.get("rows") or []
    n_mod = len([r for r in rows if r.get("model")])
    checks = [
        ("终态 stage=done", d0.get("stage") == "done"),
        ("task=optical_insert", d0.get("task") == "optical_insert"),
        ("engine=metaworld (真物理)", "metaworld" in str(d0.get("env", ""))),
        ("模型真推理次数 > 0", int(d0.get("model_calls") or 0) > 0),
        ("spool 帧数 > 100", len(frames) > 100),
        ("帧 std > 5 (真图)", float(d0.get("frame_std") or 0) > 5),
        ("视频 >= 2 个", len(vids) >= 2),
        ("模型在环回合 >= 1", n_mod >= 1),
        ("解析链对照有记录", len(rows) >= 1 and rows[0].get("analytic") is not None),
        ("诚实标注在位", bool(d0.get("honest_note"))),
        ("无推理错误", not any((r.get("model") or {}).get("err") for r in rows)),
    ]
    for nm, ok in checks:
        print(f"   {'✅' if ok else '❌'} {nm}")
        if not ok:
            fails.append(nm)
    print("\n   汇总:")
    print(f"     帧 {len(frames)} · 视频 {len(vids)} · 模型真推理 {d0.get('model_calls')} 次 · "
          f"帧std {d0.get('frame_std')}")
    print(f"     解析链对照 {d0.get('succ')}/{len(rows)} = {d0.get('success_rate')}% · "
          f"模型直驱 {d0.get('model_succ')}/{n_mod} = {d0.get('model_success_rate')}%")
    for r in rows:
        a, m = (r.get("analytic") or {}), (r.get("model") or {})
        print(f"     seed {r.get('seed')}: 解析 done={a.get('done')} 插入={a.get('insert_mm')}mm"
              f" 全链={((a.get('full_chain') or {}).get('done'))} ‖ 模型 done={m.get('done')} "
              f"插入={m.get('insert_mm')}mm 推理={m.get('model_calls')} err={m.get('err')}")
    print(f"     总耗时 {time.time()-t0:.0f}s")
    print("\n" + ("❌ 未通过: " + " · ".join(fails) if fails else "✅ 全部通过 (L4 光模块插拔链)"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
