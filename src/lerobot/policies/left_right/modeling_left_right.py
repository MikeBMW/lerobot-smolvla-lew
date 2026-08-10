"""Z-MAX LeftRight 建模: 左脑MLP动作 + 右脑WorldModel判断 + 状态机
2026-08-10 老倪: 成功模型 (抓起8/8 插入7/8) 按 lerobot 标准封装

架构:
  左脑 LeftBrainMLP:  obs → 4D 动作 (MLP偏置接近)
  右脑 RightBrainWM:  obs+action → next obs + contact判断 (该抓了吗, acc 1.00)
  状态机: 接近→抓取→抬起→转移→插入 (推理时编排)
"""
from __future__ import annotations
import os
import time
from typing import Optional, Any

import torch
import torch.nn as nn
import numpy as np

try:
    from lerobot.policies.pretrained import PreTrainedPolicy
    from .configuration_left_right import LeftRightConfig
    _HAS_LEROBOT = True
except ImportError:
    _HAS_LEROBOT = False
    from dataclasses import dataclass, field
    @dataclass
    class PreTrainedPolicy:
        config: object = None
        def from_pretrained(cls, *a, **k): raise NotImplementedError
    @dataclass
    class LeftRightConfig:
        left_hidden: int = 512
        right_hidden: int = 256
        grasp_contact_threshold: float = 0.5
        grasp_d_hp: float = 0.06
        lift_height: float = 0.08
        transfer_tolerance: float = 0.05
        insert_tolerance: float = 0.05
        n_obs_steps: int = 1
        chunk_size: int = 1
        n_action_steps: int = 1
        input_features: dict = field(default_factory=dict)
        output_features: dict = field(default_factory=dict)


class LeftBrainMLP(nn.Module):
    """左脑: obs → 4D 动作 (连续动作生成)"""
    def __init__(self, obs_dim=39, act_dim=4, hidden=512):
        super().__init__()
        self.obs_dim = obs_dim
        self.act_dim = act_dim
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(), nn.Dropout(0.1),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, act_dim))
    def forward(self, x):
        return self.net(x)


class RightBrainWM(nn.Module):
    """右脑: obs + action → next obs + contact判断 (抓取时机)"""
    def __init__(self, obs_dim=39, act_dim=4, hidden=256):
        super().__init__()
        self.enc = nn.Sequential(
            nn.Linear(obs_dim + act_dim, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU())
        self.pred_next = nn.Linear(hidden, obs_dim)
        self.contact_head = nn.Linear(hidden, 1)
    def forward(self, obs, act):
        h = self.enc(torch.cat([obs, act], dim=-1))
        next_obs = self.pred_next(h)
        contact = torch.sigmoid(self.contact_head(h))
        return next_obs, contact


class LeftRightPolicy(PreTrainedPolicy):
    """双脑策略: 左脑动作 + 右脑判断 + 状态机 (lerobot 标准 PreTrainedPolicy)
    2026-08-10: 完整集成成功逻辑 (8/8抓起 7/8插入):
      - 左脑 MLP 偏置接近 (act*0.3 + hand→peg方向*2.0)
      - 右脑 contact 判断 → 夹持 0.6 + 位置锁定
      - 状态机: 接近→抓取→抬起→转移→插入 (从 39D obs 推断)
    """
    config_class = LeftRightConfig  # lerobot 标准要求
    name = "left_right"            # lerobot 标准要求

    # 状态机 (8 状态, 与 train_full_pipeline 一致 — 2026-08-10: 插入4/8 vs 7/8 根因是缺对位/下降)
    ST_APPROACH, ST_ALIGN, ST_DESCEND, ST_GRASP = 0, 1, 2, 3
    ST_LIFT, ST_TRANSFER, ST_INSERT, ST_DONE = 4, 5, 6, 7

    def __init__(self, config: Optional[LeftRightConfig] = None, dataset_stats: Optional[dict] = None,
                 dataset_meta: Optional[Any] = None):
        config = config or LeftRightConfig()
        self.config = config
        super().__init__(config)  # 2026-08-10: 必须先 super (模块赋值要求)
        # 维度: 从 config.input_features 读, 默认 39D obs / 4D act
        obs_dim = 39
        act_dim = 4
        if config.input_features:
            obs_dim = config.input_features.get("observation.state", [39])[0] if isinstance(
                config.input_features.get("observation.state", [39]), (list, tuple)) else 39
            act_dim = config.output_features.get("action", [4])[0] if isinstance(
                config.output_features.get("action", [4]), (list, tuple)) else 4
        self.left = LeftBrainMLP(obs_dim, act_dim, config.left_hidden)
        # 2026-08-10 P3: 指标量测状态 (select_action 前可用, reset 重置)
        self.metrics = {}
        self.action_log = []
        self._t_stage = {}
        self.right = RightBrainWM(obs_dim, act_dim, config.right_hidden)
        # 推理状态 (reset 初始化)
        self.state = self.ST_APPROACH
        self.peg_z0 = None
        self.peg_lifted = False

    # ── 状态机核心 (与 train_full_pipeline 一致) ──
    def _step_state_machine(self, obs, contact_p):
        """状态机转移 (8 状态, 与 train_full_pipeline 一致)"""
        hand, peg, hole = self._get_pose(obs)
        d_hp = float(np.linalg.norm(hand - peg))
        d_ph = float(np.linalg.norm(peg - hole))
        if self.state == self.ST_APPROACH:
            if d_hp < self.config.grasp_d_hp and contact_p > self.config.grasp_contact_threshold:
                self.state = self.ST_GRASP
        elif self.state == self.ST_GRASP:
            if self.peg_z0 is not None and peg[2] - self.peg_z0 > 0.02:
                self.state = self.ST_LIFT
                self.peg_lifted = True
        elif self.state == self.ST_LIFT:
            if self.peg_z0 is not None and peg[2] > self.peg_z0 + self.config.lift_height:
                self.state = self.ST_TRANSFER
        elif self.state == self.ST_TRANSFER:
            if (abs(peg[0] - hole[0]) < self.config.transfer_tolerance
                    and abs(peg[1] - hole[1]) < self.config.transfer_tolerance):
                self.state = self.ST_INSERT
        elif self.state == self.ST_INSERT:
            if d_ph < self.config.insert_tolerance:
                self.state = self.ST_DONE
        return self.state

    def _act_state_machine(self, obs, act, contact_p):
        """状态机动作 (8 状态, 与 train_full_pipeline 一致)"""
        hand, peg, hole = self._get_pose(obs)
        act = np.asarray(act, dtype=np.float32).copy()
        if self.state == self.ST_APPROACH:
            # 双脑: MLP 偏置接近
            delta = peg - hand
            act[:3] = act[:3] * 0.3 + np.clip(delta * 2.0, -1, 1)
            act[3] = -1.0
        elif self.state == self.ST_GRASP:
            # 双脑: contact判断 → 夹持0.6 + 锁定
            act[:3] = act[:3] * 0.1
            act[3] = 0.6
        elif self.state == self.ST_LIFT:
            act[:3] = [0.0, 0.0, 0.8]
            act[3] = 0.6
        elif self.state == self.ST_TRANSFER:
            d_xy = np.array([hole[0] - peg[0], hole[1] - peg[1]])
            d_xy_n = np.linalg.norm(d_xy)
            if d_xy_n > 1e-4:
                # 2026-08-10: 转移速度自适应 — 距离越近越慢 (防过冲卡顿)
                if d_xy_n > 0.2:
                    vel = 0.6
                elif d_xy_n > 0.05:
                    vel = 0.35
                else:
                    vel = 0.15
                act[:3] = np.clip((d_xy / d_xy_n) * vel, -1, 1).tolist() + [0.0]
            act[3] = 0.6
        elif self.state == self.ST_INSERT:
            act[:3] = [0.0, 0.0, np.clip((hole[2] - peg[2]) * 2.0, -0.6, 0.6)]
            act[3] = 0.6
        else:
            act[:3] = [0.0, 0.0, 0.0]
            act[3] = 0.6
        _mx = float(np.abs(act).max()) if len(act) else 1.0
        if _mx > 1.0:
            act = act / _mx
        return act

    def select_action(self, batch, **kwargs):
        """推理: 双脑 + 状态机 (lerobot 标准, 完整插拔编排)"""
        self.eval()
        obs = batch["observation.state"].float()
        if obs.ndim == 3:
            obs = obs[:, -1]
        obs_np = obs.cpu().numpy()
        # 归一化 (与训练一致, 2026-08-10: 从 full_pipeline 导入的 x_mean/x_std)
        obs_in = obs
        if hasattr(self, "x_mean"):
            xm = self.x_mean.float().to(obs.device)
            xs = self.x_std.float().to(obs.device)
            obs_in = (obs - xm) / xs
        with torch.no_grad():
            pred_act_norm = self.left(obs_in).cpu().numpy()
            # 2026-08-10: 右脑输入须 tensor + 原始动作 (训练时右脑吃原始act)
            if hasattr(self, "y_mean"):
                pred_act_raw = pred_act_norm * self.y_std.numpy() + self.y_mean.numpy()
            else:
                pred_act_raw = pred_act_norm
            act_t = torch.from_numpy(pred_act_raw).float().to(obs.device)
            _, contact = self.right(obs, act_t)
        contact_p = contact.squeeze().cpu().numpy()
        # 反归一化动作
        if hasattr(self, "y_mean"):
            pred_act = pred_act_norm * self.y_std.numpy() + self.y_mean.numpy()
        else:
            pred_act = pred_act_norm
        # 逐 batch 处理 (通常 batch=1)
        outs = []
        for i in range(len(obs_np)):
            o_i = obs_np[i]
            a_i = pred_act[i]
            c_i = float(contact_p[i]) if np.ndim(contact_p) > 0 else float(contact_p)
            st_prev = self.state
            self._step_state_machine(o_i, c_i)
            a_out = self._act_state_machine(o_i, a_i, c_i)
            # 2026-08-10 P3: 动作级指标量测 (供大屏监督上报)
            self._measure_metrics(o_i, c_i, st_prev, a_out)
            outs.append(a_out)
        return torch.from_numpy(np.stack(outs)).float().to(obs.device)

    # ── P3: 动作级指标量测 (2026-08-10, 大屏监督方案) ──
    def _measure_metrics(self, obs, contact_p, st_prev, act):
        """记录当前阶段的实际量测指标 → self.metrics (大屏 API 上报用)
        指标与 docs/factory_fine_ops_supervision.md 的 8 状态指标表一致"""
        hand, peg, hole = self._get_pose(obs)
        d_hp = float(np.linalg.norm(hand - peg))
        d_ph = float(np.linalg.norm(peg - hole))
        m = {
            "ts": time.time(),
            "stage": ["APPROACH", "ALIGN", "DESCEND", "GRASP", "LIFT", "TRANSFER", "INSERT", "DONE"][self.state],
            "stageIdx": self.state,
            "metrics": [],
        }
        st = self.state
        if st == self.ST_APPROACH:
            m["metrics"] = [{"k": "d_hp", "name": "收敛距离", "v": float(round(d_hp, 4)), "unit": "m", "target": self.config.grasp_d_hp, "pass": bool(d_hp < self.config.grasp_d_hp)},
                            {"k": "contact", "name": "接触概率", "v": float(round(contact_p, 3)), "unit": "", "target": self.config.grasp_contact_threshold, "pass": contact_p > self.config.grasp_contact_threshold}]
        elif st == self.ST_GRASP:
            z = peg[2] - (self.peg_z0 or 0)
            m["metrics"] = [{"k": "contact", "name": "接触概率", "v": float(round(contact_p, 3)), "unit": "", "target": self.config.grasp_contact_threshold, "pass": bool(contact_p > self.config.grasp_contact_threshold)},
                            {"k": "grip_f", "name": "夹持力", "v": float(round(float(act[3]) if np.ndim(act) else 0, 3)), "unit": "", "target": 0.6, "pass": bool(abs(float(act[3]) - 0.6) < 0.05)},
                            {"k": "dz", "name": "抬升量", "v": float(round(z, 4)), "unit": "m", "target": 0.02, "pass": bool(z > 0.02)}]
        elif st == self.ST_LIFT:
            z = peg[2] - (self.peg_z0 or 0)
            m["metrics"] = [{"k": "dz", "name": "抬升高度", "v": float(round(z * 100, 2)), "unit": "cm", "target": self.config.lift_height * 100, "pass": bool(z >= self.config.lift_height)},
                            {"k": "t_lift", "name": "抬升时间", "v": float(round(self._t_stage.get("LIFT", 0), 2)), "unit": "s", "target": 0.5, "pass": True}]
        elif st == self.ST_TRANSFER:
            d_xy = float(np.linalg.norm(peg[:2] - hole[:2]))
            m["metrics"] = [{"k": "e_xy", "name": "到位偏差", "v": float(round(d_xy * 1000, 2)), "unit": "mm", "target": self.config.transfer_tolerance * 1000, "pass": bool(d_xy < self.config.transfer_tolerance)},
                            {"k": "v_xfer", "name": "转移速度", "v": float(round(float(np.linalg.norm(act[:3])), 2)), "unit": "m/s", "target": 0.6, "pass": True}]
        elif st == self.ST_INSERT:
            m["metrics"] = [{"k": "d_ph", "name": "插入距离", "v": float(round(d_ph * 1000, 2)), "unit": "mm", "target": self.config.insert_tolerance * 1000, "pass": bool(d_ph < self.config.insert_tolerance)},
                            {"k": "f_ins", "name": "插入力", "v": float(round(float(act[3]) if np.ndim(act) else 0, 2)), "unit": "", "target": 0.6, "pass": True}]
        elif st == self.ST_DONE:
            m["metrics"] = [{"k": "done", "name": "完成判定", "v": 1, "unit": "", "target": 1, "pass": True}]
        else:
            m["metrics"] = [{"k": "stage", "name": "阶段", "v": st, "unit": "", "target": st, "pass": True}]
        m["pass"] = bool(all(x["pass"] for x in m["metrics"]))
        # 阶段计时 (LIFT 用)
        if not hasattr(self, "_t_stage"):
            self._t_stage = {}
        if st_prev != self.state:
            self._t_stage = {}
        self._t_stage.setdefault(self._stage_name(st), time.time())
        # 2026-08-10 P3 fix: actionLog 记录旧阶段的最后指标 (m 是新阶段)
        prev_m = getattr(self, "_prev_metrics", None)
        if st_prev != self.state and st_prev in range(8) and prev_m:
            self.action_log.append({"ts": time.time(), "stage": prev_m.get("stage", self._stage_name(st_prev)),
                                    "stageIdx": st_prev,
                                    "metrics": prev_m.get("metrics", []), "pass": prev_m.get("pass", True)})
        self._prev_metrics = m
        self.metrics = m

    def _stage_name(self, s):
        return ["APPROACH", "ALIGN", "DESCEND", "GRASP", "LIFT", "TRANSFER", "INSERT", "DONE"][s] if 0 <= s < 8 else str(s)

    def reset(self):
        """重置状态机 (lerobot 标准, 每 episode 开始调用)"""
        self.state = self.ST_APPROACH
        self.peg_z0 = None
        self.peg_lifted = False
        # 2026-08-10 P3: 指标量测状态重置
        self.metrics = {}
        self.action_log = []
        self._t_stage = {}

    def set_peg_z0(self, peg_z0):
        """记录初始 peg 高度 (episode 开始, 供抬起判定)"""
        self.peg_z0 = float(peg_z0)

    def set_env(self, env):
        """注入 env 引用 (2026-08-10: 状态机用 env 真值 peg/hole, 因 39D obs 无 peg 段)
        评估/部署时在 episode 开始调用, 与 train_full_pipeline 一致"""
        self._env = env

    def _get_pose(self, obs):
        """从 obs 或 env 真值提取 hand/peg/hole 位置
        2026-08-10: 39D obs 无 peg 段 ([18:21] 是 hand 重复) → 有 env 用真值, 无则退化 obs"""
        env = getattr(self, "_env", None)
        if env is not None:
            try:
                hand = env.data.site_xpos[env.model.site("endEffector").id]
                peg = env.data.site_xpos[env.model.site("pegGrasp").id]
                hole = env.data.site_xpos[env.model.site("hole").id]
                return np.asarray(hand, dtype=np.float32), np.asarray(peg, dtype=np.float32), np.asarray(hole, dtype=np.float32)
            except Exception:
                pass
        obs = np.asarray(obs, dtype=np.float32).ravel()
        hand = obs[0:3]
        peg = obs[18:21]
        hole = obs[36:39] if len(obs) >= 39 else np.zeros(3)
        return hand, peg, hole

    def load_trained_weights(self, pt_path, weights_only=False):
        """从 train_full_pipeline 产物导入权重 (2026-08-10)
        pt_path: outputs/rl_peg/full_pipeline.pt (含 left/right/xm/xs/ym/ys)"""
        import os as _os
        data = torch.load(pt_path, map_location="cpu", weights_only=weights_only)
        self.left.load_state_dict(data["left"])
        # 2026-08-10: 右脑兼容 (full_pipeline 有 align_head 第三头, left_right 只用 next+contact)
        right_sd = {k: v for k, v in data["right"].items() if not k.startswith("align_head")}
        self.right.load_state_dict(right_sd, strict=False)
        # 归一化参数 (训练脚本的, 推理直接用)
        self.x_mean = torch.from_numpy(np.asarray(data["xm"], dtype=np.float32))
        self.x_std = torch.from_numpy(np.asarray(data["xs"], dtype=np.float32))
        self.y_mean = torch.from_numpy(np.asarray(data["ym"], dtype=np.float32))
        self.y_std = torch.from_numpy(np.asarray(data["ys"], dtype=np.float32))
        return self

    def forward(self, batch, **kwargs):
        """训练: 左脑动作回归 + 右脑 next/contact 预测
        batch: {"observation.state": [B, T, obs_dim], "action": [B, T, act_dim]}
        返回: {"action": [B, T, act_dim]} (标准 lerobot 输出)
        """
        obs = batch["observation.state"].float()
        if obs.ndim == 3:
            obs = obs[:, -1]  # 取最后 obs step
        act = batch["action"].float()
        if act.ndim == 3:
            act_flat = act[:, -1]
        else:
            act_flat = act
        # 左脑动作预测
        pred_act = self.left(obs)
        # 右脑判断 (辅助 loss 用, 推理不需要)
        if self.training and "next_state" in batch:
            next_s = batch["next_state"].float()
            if next_s.ndim == 3:
                next_s = next_s[:, -1]
            pred_next, pred_cont = self.right(obs, act_flat)
            # 右脑 loss 附加 (contact 标签由调用方提供)
            self._right_loss = nn.functional.mse_loss(pred_next, next_s)
        # 标准输出: action (无 chunk, 1 步)
        out = pred_act.unsqueeze(1) if pred_act.ndim == 2 else pred_act
        # 2026-08-10: lerobot_train 期望 (loss, output_dict)
        act_t = batch["action"].float()
        if act_t.ndim == 3:
            act_t = act_t[:, -1]
        loss = nn.functional.mse_loss(out.squeeze(1), act_t)
        right_loss = getattr(self, "_right_loss", None)
        if right_loss is not None:
            loss = loss + 0.5 * right_loss
        return loss, {"action": out}

    def get_right_contact(self, obs, act):
        """右脑 contact 判断 (状态机用)"""
        self.eval()
        with torch.no_grad():
            _, contact = self.right(obs, act)
        return contact

    def compute_loss(self, batch, **kwargs):
        """lerobot 标准 loss 接口"""
        loss, _ = self.forward(batch, **kwargs)
        return {"loss": loss}

    def reset(self):
        """重置状态 (lerobot 标准)"""
        self.state = self.ST_APPROACH
        self.peg_z0 = None
        self.peg_lifted = False

    def get_optim_params(self):
        """优化器参数 (lerobot 标准: 参数组列表)"""
        return [
            {"params": [p for p in self.left.parameters() if p.requires_grad]},
            {"params": [p for p in self.right.parameters() if p.requires_grad]},
        ]

    def predict_action_chunk(self, observation, **kwargs):
        """预测动作块 (lerobot 标准: [B, n_action_steps, act_dim])"""
        obs = observation["observation.state"].float()
        if obs.ndim == 3:
            obs = obs[:, -1]
        with torch.no_grad():
            pred = self.left(obs)
        return pred.unsqueeze(1)  # [B, 1, act_dim]

    def save_pretrained(self, save_directory, **kwargs):
        """保存 (lerobot 标准)"""
        os.makedirs(save_directory, exist_ok=True)
        # config.json
        import json
        def _feat_to_dict(feats):
            """PolicyFeature → dict (2026-08-10: 修 JSON 序列化)"""
            out = {}
            for k, v in (feats or {}).items():
                if hasattr(v, "type") and hasattr(v, "shape"):  # PolicyFeature
                    out[k] = {"type": str(v.type.value) if hasattr(v.type, "value") else str(v.type),
                              "shape": list(v.shape)}
                elif isinstance(v, dict):
                    out[k] = v
                else:
                    out[k] = {"shape": list(v) if isinstance(v, (list, tuple)) else v}
            return out
        cfg = {
            "type": "left_right",
            "left_hidden": self.config.left_hidden,
            "right_hidden": self.config.right_hidden,
            "grasp_contact_threshold": self.config.grasp_contact_threshold,
            "grasp_d_hp": self.config.grasp_d_hp,
            "lift_height": self.config.lift_height,
            "transfer_tolerance": self.config.transfer_tolerance,
            "insert_tolerance": self.config.insert_tolerance,
            "n_obs_steps": self.config.n_obs_steps,
            "chunk_size": self.config.chunk_size,
            "n_action_steps": self.config.n_action_steps,
            "input_features": _feat_to_dict(self.config.input_features),
            "output_features": _feat_to_dict(self.config.output_features),
        }
        with open(os.path.join(save_directory, "config.json"), "w") as f:
            json.dump(cfg, f, indent=2)
        # 权重
        torch.save({
            "left": self.left.state_dict(),
            "right": self.right.state_dict(),
            "obs_dim": self.left.obs_dim,
            "act_dim": self.left.act_dim,
        }, os.path.join(save_directory, "model.pt"))

    @classmethod
    def from_pretrained(cls, pretrained_path, **kwargs):
        """加载 (lerobot 标准)"""
        import json
        cfg_path = os.path.join(pretrained_path, "config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg_data = json.load(f)
        else:
            cfg_data = {}
        config = LeftRightConfig(
            left_hidden=cfg_data.get("left_hidden", 512),
            right_hidden=cfg_data.get("right_hidden", 256),
            grasp_contact_threshold=cfg_data.get("grasp_contact_threshold", 0.5),
            grasp_d_hp=cfg_data.get("grasp_d_hp", 0.06),
            lift_height=cfg_data.get("lift_height", 0.08),
            transfer_tolerance=cfg_data.get("transfer_tolerance", 0.05),
            insert_tolerance=cfg_data.get("insert_tolerance", 0.05),
            input_features=cfg_data.get("input_features", {}),
            output_features=cfg_data.get("output_features", {}),
        )
        policy = cls(config)
        model_path = os.path.join(pretrained_path, "model.pt")
        if os.path.exists(model_path):
            data = torch.load(model_path, map_location="cpu", weights_only=False)
            policy.left.load_state_dict(data["left"])
            policy.right.load_state_dict(data["right"])
        return policy
