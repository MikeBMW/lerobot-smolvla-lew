#!/bin/bash
# 🎯 reacher 数据集准备 (方案①"子集落位"): 归档 → 解压完整 h5 → 切 N 回合子集 → 删大件 → 落位 → 跑评测
#   为什么: 完整 dmc/reacher_random.h5 = 98.9GB, 撞磁盘余量; 评测/实况只需要少量回合 + 归一化统计。
#   安全检查: 解压前要求可用空间 ≥ 105GB (99GB 完整 h5 峰值), 不够就中止并报错 (不把盘写满)。
set -u
DS=/home/ubuntu/stable-wm-cache/datasets
ARC=${ARC:-$DS/reacher.tar.zst}
EP=${EP:-100}                     # 子集回合数
LOG=/tmp/reacher_prep.log
exec >>"$LOG" 2>&1
echo "=== reacher 子集落位 $(date '+%F %T') · 归档 $(stat -c%s "$ARC" 2>/dev/null) 字节 · 子集 $EP 回合 ==="

for i in $(seq 1 720); do [ -f "$ARC.aria2" ] || break; sleep 30; done
[ -f "$ARC.aria2" ] && { echo "⚠️ 归档仍未下完, 中止"; exit 1; }
echo "=== 归档就绪 $(date '+%F %T') · $(stat -c%s "$ARC") 字节 ==="

FREE=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "$FREE" -lt 105 ]; then echo "❌ 可用空间 ${FREE}G < 105G, 不冒险解压, 中止 (需先腾空间)"; exit 2; fi
echo "可用 ${FREE}G → 解压"

while pgrep -f "unzstd|tar .*reacher" >/dev/null; do echo "…别的进程在解压, 等 60s"; sleep 60; done
mkdir -p /tmp/reacher_x && cd /tmp/reacher_x || exit 1
tar --use-compress-program=unzstd -xf "$ARC" 2>&1 | tail -3
BIG=$(find /tmp/reacher_x -name "*.h5" -printf "%s %p\n" 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
[ -z "$BIG" ] && { echo "❌ 解压后没找到 h5"; exit 3; }
echo "完整 h5: $BIG ($(stat -c%s "$BIG") 字节)"

# 切子集 (流式, 峰值内存有界)
SUB=/tmp/reacher_subset.h5
/usr/bin/env HDF5_PLUGIN_PATH=/home/ubuntu/.h5plugins /home/ubuntu/INTACT-JEPA/.venv/bin/python \
  /home/ubuntu/lerobot-smolvla-lew/tools/make_h5_subset.py --src "$BIG" --out "$SUB" --episodes "$EP" 2>&1 | tail -6
RC=$?
if [ $RC -ne 0 ]; then echo "❌ 子集切分失败 rc=$RC (完整 h5 保留: $BIG)"; exit 4; fi

mkdir -p "$DS/dmc"
cp -f "$SUB" "$DS/dmc/reacher_random.h5" && echo "→ 落位 $DS/dmc/reacher_random.h5 ($(stat -c%s "$DS/dmc/reacher_random.h5") 字节)"
# 校验落位文件可用
/usr/bin/env HDF5_PLUGIN_PATH=/home/ubuntu/.h5plugins /home/ubuntu/INTACT-JEPA/.venv/bin/python -c "
import h5py,hdf5plugin,numpy as np
f=h5py.File('$DS/dmc/reacher_random.h5','r'); n=len(f['ep_len'])
std=float(np.asarray(f['pixels'][:5,::8,::8,:]).std()) if 'pixels' in f else None
print('落位校验:', n, '回合 · std', std, '→', 'OK' if n>=10 else 'BAD'); f.close()" 2>&1 | tail -2

# 清大件 (完整 h5 + 子集临时件 + 归档), 保留落位子集
rm -rf /tmp/reacher_x "$SUB"
echo "清理: 删除完整 h5 与归档 → 释放空间 $(df -BG --output=avail / | tail -1 | tr -dc '0-9')G 可用"
rm -f "$ARC" "$ARC.aria2"
df -h / | tail -1

echo "=== 跑 reacher 官方评测 $(date '+%F %T') ==="
N_EVAL=6 bash /home/ubuntu/run_official_eval.sh reacher
echo "=== 完成 $(date '+%F %T') ==="
