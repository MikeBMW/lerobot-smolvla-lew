#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_topic_bus.py — 状态空间「可插拔 DDS 观测层」
================================================================
老倪令 (2026-09-25):
  「topic 用于测试、标定、诊断，量产时不用。设计架构:
    我可以随时用 topic，但量产会关闭」

────────────────────── 架构 ──────────────────────
   ┌──────────────────────────────────────────┐
   │  数据面 (量产也跑 · 永不变)                 │
   │    进程内传参 / 共享内存 — 确定性、零网络    │
   │    测试与量产走【同一条】数据路径            │
   ├──────────────────────────────────────────┤
   │  观测面 (可插拔 · 量产关闭)                 │
   │    DDS topic 镜像 — 测试/标定/诊断          │
   │    关闭时: 零 import · 零 socket · 零线程    │
   └──────────────────────────────────────────┘

────────────────────── 模式 ──────────────────────
  ZMAX_SS_TOPIC_MODE:
    off    量产 (默认) — 零开销, 零 DDS 痕迹
    test   测试 — 所有连线镜像到 DDS
    calib  标定 — 只镜像标定相关信号
    diag   诊断 — 只镜像诊断/健康信号
    on     等价 test (全开)

  运行时可切换: 写 /tmp/zmax_ss_topic_mode 文件 (无需重启)
    形如:  echo test > /tmp/zmax_ss_topic_mode

────────────────── 量产安全保证 ──────────────────
  ① off 模式下 `import cyclonedds` / `websockets` 都不会发生
  ② 不创建 DomainParticipant → **进程内无任何 RTPS 端口**
     可审计: lsof -p <pid> -a -i UDP | grep rtps  →  空
  ③ 不启任何线程 / 不占额外内存
  ④ mirror() 在 off 路径 = 一次属性读 + return (纳秒级)

用法:
    from ss_topic_bus import bus
    bus.mirror("zmax/ss/flow/a.out1__b.in1", {"obs": [...]})   # 热路径, off 时零开销
    bus.set_calib_scope(["calib", "handeye"])                  # 标定模式只镜像相关
"""
import os
import sys
import threading
import time

MODE_FILE = os.environ.get("ZMAX_SS_TOPIC_MODE_FILE", "/tmp/zmax_ss_topic_mode")
VALID_MODES = ("off", "test", "calib", "diag", "on")

# 标定模式关注的 topic 关键字 (命中才镜像)
_CALIB_KEYS = ("calib", "handeye", "tcp", "plane", "intrinsic", "extrinsic",
               "gauge", "标定", "cam", "pose")
# 诊断模式关注的 topic 关键字
_DIAG_KEYS = ("health", "status", "diag", "error", "warn", "latency", "fps",
              "health", "监控", "诊断")


class TopicBus:
    """可插拔 DDS 观测层 (单例 `bus`)

    热路径 mirror() 在 off 模式下: 一次 self._mode 读 + 比较 + return
    —— 不 import 任何 DDS 库, 不碰 socket, 不碰线程。
    """

    __slots__ = ("_mode", "_backend", "_sent", "_dropped", "_lock",
                 "_scope", "_last_mode_check", "_mtime", "_stats", "_err")

    def __init__(self):
        self._mode = os.environ.get("ZMAX_SS_TOPIC_MODE", "off").strip().lower()
        if self._mode not in VALID_MODES:
            self._mode = "off"
        self._backend = None          # 懒加载 (只有非 off 才创建)
        self._sent = 0
        self._dropped = 0
        self._lock = threading.Lock()
        self._scope = []              # 非空 = 只镜像命中关键字的 topic
        self._last_mode_check = 0.0
        self._mtime = 0.0
        self._stats = {}
        self._err = ""
        if self._mode in ("calib", "diag"):
            self._apply_scope()

    # ── 模式 ──────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._mode != "off"

    @property
    def mode(self) -> str:
        return self._mode

    def _apply_scope(self):
        if self._mode == "calib":
            self._scope = list(_CALIB_KEYS)
        elif self._mode == "diag":
            self._scope = list(_DIAG_KEYS)
        else:
            self._scope = []

    def set_mode(self, mode: str) -> bool:
        """运行时切模式 (立即生效; 从 off 打开时才懒加载后端)"""
        mode = (mode or "").strip().lower()
        if mode not in VALID_MODES:
            return False
        if mode == self._mode:
            return True
        with self._lock:
            if mode == "off":
                # 关: 释放后端 + 停线程 (回到零开销)
                self._teardown()
            self._mode = mode
            self._apply_scope()
        return True

    def _poll_mode_file(self):
        """运行时开关: 允许写 /tmp/zmax_ss_topic_mode 热切换 (1s 节流)"""
        now = time.time()
        if now - self._last_mode_check < 1.0:
            return
        self._last_mode_check = now
        try:
            m = os.stat(MODE_FILE)
        except OSError:
            return
        if m.st_mtime == self._mtime:
            return
        self._mtime = m.st_mtime
        try:
            with open(MODE_FILE, encoding="utf-8") as f:
                nv = f.read().strip().lower()
            if nv in VALID_MODES and nv != self._mode:
                self.set_mode(nv)
                print(f"🛰  SS topic 模式热切换 → {nv}", flush=True)
        except Exception:
            pass

    # ── 后端 (懒加载) ──────────────────────────────────────
    def _ensure_backend(self):
        """只有非 off 才走到这里; off 模式绝不 import DDS 库"""
        if self._backend is not None:
            return self._backend
        try:
            from ss_dds_lite import DdsLiteWriter  # noqa: PLC0415
            self._backend = DdsLiteWriter()
            print(f"🛰  DDS 观测层已启用 (mode={self._mode})", flush=True)
        except Exception as e:
            self._err = f"{type(e).__name__}: {str(e)[:120]}"
            print(f"⚠️  DDS 观测层启用失败: {self._err}", flush=True)
            self._backend = False        # False = 尝试过但失败, 不再重试
        return self._backend

    def _teardown(self):
        b = self._backend
        self._backend = None
        if b and b is not False:
            try:
                b.close()
            except Exception:
                pass

    # ── 热路径 ────────────────────────────────────────────
    def mirror(self, topic: str, payload, *, kind: str = "link") -> bool:
        """把一条信号镜像到 DDS topic。

        **off 模式 (量产): 一次属性比较 + return False —— 零开销、零副作用。**
        返回 True = 已发出; False = 未发 (模式关闭 / 被 scope 过滤 / 出错)
        """
        if self._mode == "off":                 # ← 量产路径: 唯一成本
            return False
        self._poll_mode_file()                  # 运行时开关 (1s 节流)
        if self._mode == "off":
            return False
        if self._scope and not any(k in topic or k in kind for k in self._scope):
            self._dropped += 1                  # 标定/诊断模式的 scope 过滤
            return False
        b = self._ensure_backend()
        if not b:
            self._dropped += 1
            return False
        try:
            b.send(topic, payload, kind=kind)
            self._sent += 1
            self._stats[topic] = self._stats.get(topic, 0) + 1
            return True
        except Exception as e:
            self._err = f"{type(e).__name__}: {str(e)[:100]}"
            self._dropped += 1
            return False

    # ── 审计 ──────────────────────────────────────────────
    def audit(self) -> dict:
        """量产前审计: 证明观测层已关闭 / 无 DDS 痕迹"""
        return {
            "mode": self._mode,
            "enabled": self.enabled,
            "backend": ("none" if self._backend is None
                        else ("failed" if self._backend is False else "live")),
            "sent": self._sent,
            "dropped": self._dropped,
            "scope": self._scope,
            "topics": len(self._stats),
            "error": self._err,
            "threads": threading.active_count(),
        }


# ── 单例 + 模块级快捷函数 ──────────────────────────────────
bus = TopicBus()


def mirror(topic: str, payload, *, kind: str = "link") -> bool:
    return bus.mirror(topic, payload, kind=kind)


def mode() -> str:
    return bus.mode


def set_mode(m: str) -> bool:
    return bus.set_mode(m)


if __name__ == "__main__":
    import json
    a = sys.argv[1:]
    if a and a[0] in VALID_MODES:
        set_mode(a[0])
    if a and a[0] == "audit":
        print(json.dumps(bus.audit(), ensure_ascii=False, indent=1))
    else:
        print(f"mode={bus.mode} enabled={bus.enabled} "
              f"backend={bus.audit()['backend']} threads={bus.audit()['threads']}")
        print(f"合法模式: {VALID_MODES}  切换: python3 ss_topic_bus.py <mode>")
