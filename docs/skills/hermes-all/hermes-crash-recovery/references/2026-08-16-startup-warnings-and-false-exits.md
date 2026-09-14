# 2026-08-16 启动警告误报 + "静静又退出"假象诊断

## 1. `⚠ Deprecated .env settings detected: TERMINAL_CWD=...` 每次启动刷黄字

**根因 (误报)**: Hermes 源码 `warn_deprecated_cwd_env_vars()` (hermes_cli/config.py:2181-2225)。
告警条件 = 环境里有 `TERMINAL_CWD` **且** config.yaml 的 `terminal.cwd` 不是显式路径
(`"."`, `"auto"`, `"cwd"`, `""` 都算非显式)。用户 .env 里其实只有注释掉的 `# TERMINAL_CWD=.`,
环境里的 `TERMINAL_CWD=/root` 是 Hermes 自己转译注入的 → 每次启动都误报。

**修复 (实测通过 2026-08-16)**:
```bash
hermes config set terminal.cwd /root
```
- config.yaml 有安全写保护, **不能用 patch/write_file 直接改** — 必须走 `hermes config set`。
- 改完验证: 同条件(TERMINAL_CWD=/root 在环境里)调 `warn_deprecated_cwd_env_vars()` → 零输出。
- 行为不变 (终端本来就在 /root 工作), 只是警告消失。

## 2. 用户说"你怎么又自己退出了" — 三种假象的鉴别

用户感知的"静静退出"绝大多数是假象, 按概率排序:

| 现象 | 真相 | 证据位置 |
|---|---|---|
| ① 回复到一半停了, 用户发新消息 | 用户打断 → `stream_interrupt_abort`, 设计行为非崩溃 | `~/.hermes/logs/agent.log` (OpenAI client aborted), `~/.hermes/interrupt_debug.log` (interrupt fired) |
| ② 会话标题静静→#2→#3→#4 | 每次重开终端/CLI = 新会话编号; 记忆/技能共享不受影响 | session_search browse (多个同标题会话) |
| ③ 飞书不回复, gateway.log 停更 | gateway 独立进程真死了 (SIGKILL/OOM/VM death) | `ps aux | grep "gateway run"` 无输出; gateway-exit-diag.log 的 `exited UNCLEANLY` |

**诊断顺序**: `ps aux | grep hermes` (CLI 活着 = ①②) → 解释 interrupt 机制;
再 `ps aux | grep "gateway run"` + gateway-exit-diag.log (gateway 死 = ③, 才需要真修复,
见 SKILL.md 的"容器无 systemd 守护"配方)。

**教训**: 用户说"你退出了"时不要先道歉或重启, 先查 ps — CLI 进程还在就讲清楚机制,
用户要的是解释, 不是重启。
