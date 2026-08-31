# python 环境探测: 项目无 .venv! (2026-08-30, commit 87c9cb69)

**症状**: 推理模式运行数据层节点 → "❌ 缺少 .venv/bin/python (推理需本地 GPU 环境)"。

**根因**: on_infer_rollout / on_eval_state_space 写死 `os.path.join(root, ".venv", "bin", "python")`,
但本机项目**没有 .venv** — 推理/训练环境是 `~/lerobot-venv` (uv 建的, python 3.12.13,
torch 2.7.1+cu128 CUDA 可用)。

**修法** (多候选探测, 首个存在者优先):
```python
py = next((c for c in (os.path.join(root, ".venv", "bin", "python"),
                       os.path.expanduser("~/lerobot-venv/bin/python"),
                       os.path.join(root, "gui-venv311", "bin", "python"))
           if os.path.exists(c)), None)
if not py:
    return False, "缺少推理 python 环境 (需 .venv 或 ~/lerobot-venv, 含 torch+CUDA)"
```

**⚠️ uv 建的 venv 没有 pip**: `~/lerobot-venv/bin/pip` 不存在, `python -m pip` 也没有 →
装包用 `uv pip install --python ~/lerobot-venv/bin/python <pkg>` (uv 在 ~/.hermes/bin/uv)。

**gen_insert_video/eval_state_space 需要 metaworld 仿真环境** (make_env → MT1 peg-insert-side-v3):
- apt: `sudo apt-get install -y libglfw3-dev libosmesa6-dev patchelf`
- `uv pip install --python ~/lerobot-venv/bin/python metaworld` (mujoco wheel 大, 下载 5-10 分钟)
- 缺失时症状: "⚠️ YOLO 感知构建失败 (No module named 'metaworld'), 回退真值感知"
  (警告, 非致命 — _build_aligner 设计内回退) 随后 make_env 直接崩 → rollout 失败。
- 验证: `~/lerobot-venv/bin/python -c "import metaworld"` + 依赖导入测试。

**排查启示**: "运行了但报环境错" 时先看**真实环境在哪** (ls -d */bin/python + pyvenv.cfg),
别假设项目 .venv 存在 — uv 管理的项目常常把 venv 放别处。
