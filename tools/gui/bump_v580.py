#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bump_v580.py — 中版本迭代 v5.7.0 → v5.8.0 (五处同步点 + VERSION.md 历史表)

本次内容 (老倪 2026-09-19): 大模型层连接拓扑补全 + 环境数据入技能编排器 + 工程记忆→总装记忆同步。
"""
import os
import time

REPO = "/home/ubuntu/lerobot-smolvla-lew"
NEW = "v5.8.0"
NEWV = "5.8.0"

CHANGELOG = (
    "        # v5.8.0: 🧠🔗 **大模型层连接拓扑补全 + 环境数据入技能编排器 + 工程记忆→总装记忆同步 (与飞书端商量好)** — "
    "老倪: 「技能编排器怎么没有输入呢? 环境数据要输入给技能编排层的大语言模型啊」「其它节点怎么都是悬浮在那呢? 你要设计好连接拓扑关系」"
    "「当前的工程记忆, 要同步到大模型层的总装记忆节点」 "
    "①**画布拓扑**: 新增 📚工程记忆节点 + 31 条连线 — 环境→技能编排器 (数据源/真机实况) · 状态/安全否决→异常推理器 · "
    "三层记忆(L2/L3/L4)+记忆图谱+工程记忆→总装记忆中枢 · 意图丛/技能词典/记忆图谱/意图直读 由**全悬空接上真实读写** · "
    "数据源→训练/推理→能力档位→(L4/L3/L2 各层) · 标定层↔2D→3D 反投影/潜空间标定; **悬空节点 0** (仅 2 个源节点无入线)。 "
    "②**布局按数据流层级定列** (tools/gui/gen_ss_obs_layout2.py): DFS 反馈边 → DAG 最长路 → x=层级 → 所有非双向边必然向右; "
    "双向关系 (记忆上报/下发 等 13 条) 自动标 ↩; 三版对比 右→左连线 基线7 → 首版40 → **13(全为真双向)** · 方框重叠 0 · 穿框 47→25。 "
    "③**环境输入** (node_ss_skill/_skill_spec_from_env): 真机/仿真帧来源+帧龄 · 场景理解(SceneVLM) · 宏观记忆下行建议 → 汇成规格文本给 SkillComposer; "
    "缺哪一路如实打印 (实测无 VLM 时打印「环境帧不可用; 场景理解未就绪」并仍注入宏观记忆建议)。 "
    "④**工程记忆→总装** (src/lerobot/memory/eng_memory.py + 节点 📚): 真读 docs/memory/*.md(59) + ~/.hermes/memories(2) + 技能(163) = **224 文件/997 记忆条目/1581 技能小节** "
    "→ **追加式**写入 macro_memory.engineering (幂等指纹 · 原子 tmp+rename · 回读校验), 飞书端其它键 (knowledge/capability/diagnosis/advice/seen) 原样保留。 "
    "⑤**修同名覆盖**: node_ss_skill 被原子技能处理器二次定义覆盖 (同名) → 原子技能更名 node_ss_atomic, 分派器+注册同步 (行为不变, 隐患消除)。 "
    "⑥**验收**: /tmp/hermes-verify-llm-topology.py 四条全绿 (编排器有环境输入 · 规划器有上下文 · 工程记忆同步回读 · 无悬空节点); 零回退 ✅ (档位归属/L2 57/L3 62/L4 79/连线丢失 0)。\n"
)


def patch(path, pairs, must=True):
    p = os.path.join(REPO, path)
    s = open(p, encoding="utf-8").read()
    o = s
    for a, b in pairs:
        n = s.count(a)
        if must:
            assert n == 1, f"{path}: 锚点 {a[:60]!r} 出现 {n} 次"
        s = s.replace(a, b)
    if s != o:
        open(p, "w", encoding="utf-8").write(s)
        return True
    return False


def main():
    done = []
    done.append(("tools/gui/studio.py", patch("tools/gui/studio.py", [
        ('ver = QLabel("Z-MAX v5.7.0")', 'ver = QLabel("Z-MAX v5.8.0")'),
        ('self.setWindowTitle("XSpace Studio — Z-MAX v5.7.0 [W-01] ⚠️非调试模式")',
         'self.setWindowTitle("XSpace Studio — Z-MAX v5.8.0 [W-01] ⚠️非调试模式")'),
        ('self.setWindowTitle("XSpace Studio — Z-MAX v5.7.0 [W-01]")',
         'self.setWindowTitle("XSpace Studio — Z-MAX v5.8.0 [W-01]")'),
        ('        # v5.7.0: 🕐🤖 **真机 J6 首次真运动', CHANGELOG + '        # v5.7.0: 🕐🤖 **真机 J6 首次真运动'),
    ])))
    done.append(("tools/gui/update_checker.py", patch("tools/gui/update_checker.py",
                                                     [('CURRENT_VERSION = "v5.7.0"', 'CURRENT_VERSION = "v5.8.0"')])))
    done.append(("tools/gui/version_sync.py", patch("tools/gui/version_sync.py",
                                                    [('zmax_ver = "5.7.0"', 'zmax_ver = "5.8.0"')])))
    done.append(("tools/gui/docs_sync.py", patch("tools/gui/docs_sync.py", [
        ('"version": "v5.7.0",', '"version": "v5.8.0",'),
        ('"zmax_version": "v5.7.0",', '"zmax_version": "v5.8.0",'),
    ])))
    # 画布流程名版本 (状态空间架构 v5.2 → v5.3)
    fp = os.path.join(REPO, "flows", "state_space_obs.json")
    s = open(fp, encoding="utf-8").read()
    if "状态空间架构 v5.2" in s:
        s = s.replace("状态空间架构 v5.2", "状态空间架构 v5.3")
        open(fp, "w", encoding="utf-8").write(s)
        done.append(("flows/state_space_obs.json", "v5.2 → v5.3"))
    # VERSION.md 历史表: 新行插到 v5.7.0 行之前
    vm = os.path.join(REPO, "VERSION.md")
    v = open(vm, encoding="utf-8").read()
    row_head = "| **v5.7.0** |"
    assert v.count(row_head) == 1, "VERSION.md 锚点异常"
    newrow = ("| **v5.8.0** | 09-19 | 🧠🔗 **大模型层连接拓扑补全 + 环境数据入技能编排器 + 工程记忆→总装记忆同步** — 老倪: "
              "「技能编排器怎么没有输入呢? 环境数据要输入给技能编排层的大语言模型啊」「其它节点怎么都是悬浮在那呢? 你要设计好连接拓扑关系」"
              "「当前的工程记忆, 要同步到大模型层的总装记忆节点」 ①画布拓扑: 新增 📚工程记忆节点 + **31 条连线** (环境→编排器 · 状态/安全否决→异常推理器 · "
              "三层记忆+图谱+工程记忆→总装 · 意图丛/技能词典/记忆图谱/意图直读 从**全悬空接上真实读写** · 数据源→模式→档位→各层 · 标定层↔2D→3D/潜空间), 悬空节点 0。 "
              "②布局按**数据流层级定列** (DFS 反馈边→DAG 最长路→x=层级): 右→左连线 基线7 → 首版40 → **13 条(全部为真双向上报/下发, 自动标 ↩)** · 重叠 0 · 穿框 47→25。 "
              "③环境输入: `_skill_spec_from_env` 读 真机/仿真帧来源+帧龄 · 场景理解 · 宏观记忆建议 → 规格文本, 缺路如实打印 (实测仍注入宏观建议)。 "
              "④工程记忆→总装: `src/lerobot/memory/eng_memory.py` 真读 docs/memory(59)+Hermes记忆(2)+技能(163) = **224 文件/997 记忆条目/1581 技能小节** → "
              "**追加式**写入 `macro_memory.engineering` (幂等指纹+原子写+回读), 飞书端其它键保留。 "
              "⑤修同名覆盖: `node_ss_skill` 被原子技能处理器二次定义 → 更名 `node_ss_atomic`。 "
              "⑥验收四条全绿 + 零回退 ✅ (档位归属不变/L2 57/L3 62/L4 79/连线丢失 0) |\n")
    v = v.replace(row_head, newrow + row_head, 1)
    open(vm, "w", encoding="utf-8").write(v)
    done.append(("VERSION.md", "新增 v5.8.0 行"))
    for k, r in done:
        print(f"  {'✅' if r else '⏭'} {k}: {r if isinstance(r, str) else ('已改' if r else '无改动')}")
    print(f"\n版本同步点: {NEW} (5 处 + VERSION.md + 画布流程名)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
