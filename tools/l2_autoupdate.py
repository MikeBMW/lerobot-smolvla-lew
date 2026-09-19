#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_autoupdate.py — 大模型层指挥 L2 肌肉记忆升级 (架构闭环最后一环)

链路: DeepSeek VL(场景理解) → 本编排器(把场景+现有技能喂给 LLM 规划) → 生成技能更新提案
      → 人工确认(--apply) → 调 l2_skill_learn 热更新 → 执行器下一帧即用(无需重启)

用法:
  python3 tools/l2_autoupdate.py --scene data/scene_state.json --skill L2.MUSCLE.OPEG_DEMO_LEARNED.v1
  python3 tools/l2_autoupdate.py --scene ... --skill ... --apply     # 应用提案
"""
import argparse, json, os, re, subprocess, sys, urllib.request

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_key():
    p = os.path.expanduser("~/.hermes/.env")
    for ln in open(p, encoding="utf-8", errors="ignore") if os.path.exists(p) else []:
        m = re.match(r"\s*DEEPSEEK_API_KEY\s*=\s*(.+)", ln)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return os.environ.get("DEEPSEEK_API_KEY", "")


def ask_llm(prompt, key, timeout=90):
    body = json.dumps({"model": "deepseek-chat",
                       "messages": [{"role": "system", "content": "你是 Z-MAX 具身智能的 L3 长程序列规划器。只输出 JSON, 不要解释。"},
                                    {"role": "user", "content": prompt}],
                       "temperature": 0.2}).encode()
    req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode())
    return d["choices"][0]["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="data/scene_state.json")
    ap.add_argument("--skill", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    scene = json.load(open(os.path.join(R, a.scene), encoding="utf-8")) if os.path.exists(os.path.join(R, a.scene)) else {}
    sp = os.path.join(R, "data/skills/l2_muscle/%s.json" % a.skill.replace(".", "_"))
    if not os.path.exists(sp):
        print("找不到技能:", sp); return 2
    sk = json.load(open(sp, encoding="utf-8"))

    prompt = ("【场景理解(DeepSeek VL 输出)】\n%s\n\n"
              "【当前 L2 技能】%s (v%s)\n点位: %s\n\n"
              "【任务】判断场景与技能是否失配(新路径/新场景/点位漂移)。若需更新, 给出要改的点位新值(单位 m/四元数);"
              "若无需更新, 只回 {\"action\":\"none\"}。\n"
              "严格输出 JSON: {\"action\":\"update\"|\"none\", \"point\":\"点位名\", "
              "\"pos\":[x,y,z], \"quat\":[qx,qy,qz,qw], \"reason\":\"一句话\"}") % (
        json.dumps(scene, ensure_ascii=False)[:900], sk.get("name"), sk.get("version"),
        json.dumps({k: v.get("pos") for k, v in list(sk.get("points", {}).items())[:6]}, ensure_ascii=False)[:600])

    key = load_key()
    if not key:
        print("无 DEEPSEEK_API_KEY, 无法规划"); return 3
    try:
        out = ask_llm(prompt, key)
    except Exception as e:
        print("LLM 调用失败:", e); return 4
    m = re.search(r"\{.*\}", out, re.S)
    prop = json.loads(m.group(0)) if m else {"action": "none", "raw": out[:200]}
    print("提案:", json.dumps(prop, ensure_ascii=False))

    if prop.get("action") == "update" and a.apply and prop.get("point") in sk.get("points", {}):
        cmd = [sys.executable, os.path.join(R, "tools/l2_skill_learn.py"), "--set-point", a.skill, prop["point"]] + \
              [str(x) for x in prop["pos"]] + [str(x) for x in prop.get("quat", [0, 0, 0, 1])]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print("已应用:", r.stdout.strip() or r.stderr.strip()[-200:])
    elif prop.get("action") == "update":
        print("(未加 --apply, 仅提案; 确认后加 --apply 生效)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
