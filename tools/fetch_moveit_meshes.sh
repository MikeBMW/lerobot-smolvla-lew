#!/usr/bin/env bash
# 从 Orin 只读拷回 URDF 引用的 mesh (零 Orin 改动) → 校验引用可解析 → 入库
set -u
cd /home/ubuntu/zmax_rel || exit 1
SRC=/home/tashan/0810/tashan_robot_so_20260807_174920_6983506_aarch64/resource/config/sr5_guangmokuai_100gAOI/robot/urdf/meshes
DST=config/moveit_xms5/urdf/meshes
echo "═══ ① 只读拷回 (Orin → 本机) ═══"
mkdir -p "$DST"
timeout 300 sshpass -p 'ts123' ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no tashan@192.168.23.66 "tar -C $SRC -cf - ." 2>/dev/null | tar -C "$DST" -xf - 2>/dev/null
N=$(find "$DST" -name "*.stl" | wc -l); SZ=$(du -sm "$DST" | cut -f1)
echo "  拷回 STL: $N 个 · ${SZ}MB"
echo "═══ ② 校验 URDF 引用是否全部可解析 ═══"
./gui-venv311/bin/python - <<'PY'
import os, re
u = "config/moveit_xms5/urdf/xms5_r800_w4g3b4c.urdf"
txt = open(u, encoding="utf-8").read()
refs = sorted(set(re.findall(r'filename="([^"]+\.stl)"', txt)))
base = os.path.dirname(u)
miss = [r for r in refs if not os.path.isfile(os.path.join(base, r))]
print("  URDF 引用 mesh: %d 个 · 缺失: %d" % (len(refs), len(miss)))
for m in miss[:6]:
    print("    ❌", m)
print("  ✅ 全部可解析" if not miss else "  ⚠️ 仍有缺失 (碰撞几何会退化)")
PY
echo "═══ ③ 入库 ═══"
git add config/moveit_xms5 tools/arm_settle_final.py docs/ 2>/dev/null
git -c user.name=ubuntu -c user.email=ubuntu@zmax commit -q -m "M3 收口(1/2): 从 Orin 只读拷回 URDF 引用的 STL mesh → MoveIt 碰撞几何可用

· 70 个 STL (${SZ}MB) 从产线工作空间只读拷回 (零 Orin 改动), 放入 config/moveit_xms5/urdf/meshes
· URDF 的 meshes/xms5_r800_w4g3b4c_meshes/*.stl 引用全部可解析 ⇒ 不再有 'Could not resolve host: meshes'
· MoveIt 此前只做 IK/规划(mesh 缺失→碰撞检查退化), 现在具备真实碰撞几何" 2>&1 | tail -2
git push origin HEAD:main 2>&1 | tail -1
git log --oneline -1
