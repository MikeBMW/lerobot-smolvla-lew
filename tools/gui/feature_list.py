# -*- coding: utf-8 -*-
"""✨ Feature List · Z-MAX 产品特征清单 (2026-08-19 老倪)

右侧下拉菜单「帮助文档」→ Feature List 弹窗。
视角: 工程需求 / 标准接口 / 展品特征 — 偏向 场景·功能·标准接口·性能指标。
铁律: 不强调模型架构 (禁 ACT/SmolVLA/MLP/latent/backbone 等词), 数据来自
Z700_technical_agreement_v3.md (5 场景) + 需求规格书 + 实测评估 (抓起/插入成功率)。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QTextBrowser, QPushButton,
                             QHBoxLayout)

_BG = "#0d1117"
_CARD = "#161b22"
_BORDER = "#30363d"
_TEXT = "#e6edf3"
_SUB = "#8b949e"
_ACCENT = "#58a6ff"

_HTML = """<html><body style="font-family:'WenQuanYi Micro Hei','Noto Sans CJK SC',sans-serif; color:%TEXT%; font-size:13px;">
<h2 style="color:%ACCENT%; margin:4px 0 2px;">Feature List · Z-MAX 产品特征清单</h2>
<div style="color:%SUB%; font-size:12px; margin-bottom:10px;">Z700 / Z700F · 面向光模块工厂精细操作 · 2026-08-19</div>

<h3 style="color:%ACCENT%; margin:10px 0 4px;">1. 产品定位</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %BORDER%; border-collapse:collapse;">
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%; width:90px;"><b>Z700</b></td><td style="border:1px solid %BORDER%;">L4 全自主具身智能机器人 — 感知、决策、操作全链路本地自主完成</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>Z700F</b></td><td style="border:1px solid %BORDER%;">Fix L2 固定工位作业单元 — 单工位精细操作，部署即用</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>服务对象</b></td><td style="border:1px solid %BORDER%;">光模块工厂 (100G/400G/800G 模块, QSFP-DD/OSFP 封装) 精细操作产线</td></tr>
</table>

<h3 style="color:%ACCENT%; margin:10px 0 4px;">2. 应用场景（5 大场景 · 符合技术协议）</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %BORDER%; border-collapse:collapse; width:100%%;">
<tr style="background:%CARD%; color:%ACCENT%;">
<td style="border:1px solid %BORDER%; width:24px;">#</td><td style="border:1px solid %BORDER%;">场景</td><td style="border:1px solid %BORDER%;">作业对象</td><td style="border:1px solid %BORDER%;">工位/设备</td><td style="border:1px solid %BORDER%;">单颗节拍</td><td style="border:1px solid %BORDER%;">成功率</td></tr>
<tr><td style="border:1px solid %BORDER%;">1</td><td style="border:1px solid %BORDER%;">FW Loading + EEPROM 写/读</td><td style="border:1px solid %BORDER%;">100G/400G/800G 成品模块</td><td style="border:1px solid %BORDER%;">桌面 EVB 子板+主板+底座</td><td style="border:1px solid %BORDER%;">≤6 s</td><td style="border:1px solid %BORDER%;">≥99%</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;">2</td><td style="border:1px solid %BORDER%;">上下料搬运</td><td style="border:1px solid %BORDER%;">料盘/料箱（多载具柔性）</td><td style="border:1px solid %BORDER%;">跨工位配送</td><td style="border:1px solid %BORDER%;">按趟</td><td style="border:1px solid %BORDER%;">≥99.5%</td></tr>
<tr><td style="border:1px solid %BORDER%;">3</td><td style="border:1px solid %BORDER%;">BI 老化箱模块插拔</td><td style="border:1px solid %BORDER%;">成品模块 (QSFP~10颗/屉, OSFP~16颗/屉)</td><td style="border:1px solid %BORDER%;">抽屉式老化箱</td><td style="border:1px solid %BORDER%;">单颗≤60 s</td><td style="border:1px solid %BORDER%;">≥99%</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;">4</td><td style="border:1px solid %BORDER%;">热海柜体 电口+光口插拔</td><td style="border:1px solid %BORDER%;">100G/400G/800G (QSFP/OSFP)</td><td style="border:1px solid %BORDER%;">柜体 50cm 高 600mm 宽</td><td style="border:1px solid %BORDER%;">≤20 s</td><td style="border:1px solid %BORDER%;">≥99%</td></tr>
<tr><td style="border:1px solid %BORDER%;">5</td><td style="border:1px solid %BORDER%;">ATS / 线外检测插接</td><td style="border:1px solid %BORDER%;">100G C4 等模块</td><td style="border:1px solid %BORDER%;">ATS 测试座/线外检测工位</td><td style="border:1px solid %BORDER%;">≤15 s</td><td style="border:1px solid %BORDER%;">≥99%</td></tr>
</table>
<div style="color:%SUB%; font-size:12px;">节拍为不可妥协的物理硬指标（顶层约束），成功率按 10 次插拔验收口径统计。</div>

<h3 style="color:%ACCENT%; margin:10px 0 4px;">3. 核心功能（工程需求视角）</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %BORDER%; border-collapse:collapse; width:100%%;">
<tr style="background:%CARD%; color:%ACCENT%;"><td style="border:1px solid %BORDER%; width:130px;">功能项</td><td style="border:1px solid %BORDER%;">说明</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>端侧自主作业</b></td><td style="border:1px solid %BORDER%;">感知→决策→动作全链路在机端完成，不依赖云端网络，满足 24h 连续作业</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>精细操作技能库</b></td><td style="border:1px solid %BORDER%;">抓取 / 搬运 / 对准 / 插拔 / 压合等原子技能，可组合编排成完整作业流程</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>力控保护</b></td><td style="border:1px solid %BORDER%;">触觉反馈实时力控，插拔过程保护模块金手指与壳体，不损伤工件</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>多阶段作业编排</b></td><td style="border:1px solid %BORDER%;">接近/抓取/抬起/转移/插入分阶段调度，各阶段独立标定，全程可追溯</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>边学边练闭环</b></td><td style="border:1px solid %BORDER%;">现场采集数据 → 自动训练 → 热更新部署，产线数据持续反哺能力提升</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>仿真先行验证</b></td><td style="border:1px solid %BORDER%;">作业策略先在仿真环境验证成功率与动作质量，达标后再迁移真机，降低现场风险</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>多方案统一管理</b></td><td style="border:1px solid %BORDER%;">多套作业方案统一配置、一键对比评估（成功率/动作幅度/耗时），择优部署</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>大屏指标监督</b></td><td style="border:1px solid %BORDER%;">成功率/节拍/力值等 KPI 实时上报大屏，异常即时告警</td></tr>
</table>

<h3 style="color:%ACCENT%; margin:10px 0 4px;">4. 标准接口</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %BORDER%; border-collapse:collapse; width:100%%;">
<tr style="background:%CARD%; color:%ACCENT%;"><td style="border:1px solid %BORDER%; width:130px;">接口</td><td style="border:1px solid %BORDER%;">说明</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>部署接口</b></td><td style="border:1px solid %BORDER%;">模型文件 (safetensors) 热更新，机端监听自动拉取生效，无需停机</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>数据接口</b></td><td style="border:1px solid %BORDER%;">标准数据集格式（视频帧 + 状态 + 动作），SN 绑定可追溯，支持增量采集</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>监控接口</b></td><td style="border:1px solid %BORDER%;">指标 HTTP 上报（成功率/节拍/力值/状态），对接大屏与上位系统</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>消息接口</b></td><td style="border:1px solid %BORDER%;">训练完成 / 视频 / 报告自动推送飞书，产线人员无需盯屏</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>Web 接口</b></td><td style="border:1px solid %BORDER%;">datadrive.world 网页端监控与演示，手机可访问</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>训练接口</b></td><td style="border:1px solid %BORDER%;">容器化 GPU 训练环境，标准配置一键训练，训练产物版本化管理</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>硬件接口</b></td><td style="border:1px solid %BORDER%;">7 轴机械臂 + 视觉 + 触觉传感，Orin 机端推理，与产线 PLC/联锁信号对接</td></tr>
</table>

<h3 style="color:%ACCENT%; margin:10px 0 4px;">5. 性能指标</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %BORDER%; border-collapse:collapse; width:100%%;">
<tr style="background:%CARD%; color:%ACCENT%;"><td style="border:1px solid %BORDER%;">指标</td><td style="border:1px solid %BORDER%;">规格/实测</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>插拔成功率</b></td><td style="border:1px solid %BORDER%;">验收口径 ≥99%（10 次插拔统计）；仿真实测：抓起 6-8/8、插入 4-6/8（多 seed 取波动区间，持续优化中）</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>作业节拍</b></td><td style="border:1px solid %BORDER%;">按场景 ≤6 s ~ ≤60 s（详见第 2 节），节拍为物理硬指标</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>负载能力</b></td><td style="border:1px solid %BORDER%;">插拔类负载 &gt;1.00 kg；搬运类 ≥5 kg</td></tr>
<tr style="background:%CARD%;"><td style="border:1px solid %BORDER%;"><b>端侧轻量化</b></td><td style="border:1px solid %BORDER%;">端侧决策模型 &lt;1M 参数级，机端实时推理（插拔循环 0.64M 规模）</td></tr>
<tr><td style="border:1px solid %BORDER%;"><b>连续作业</b></td><td style="border:1px solid %BORDER%;">24 小时不间断，无尘车间 Class 1000 环境适配，全流程 SN 可追溯</td></tr>
</table>

<div style="color:%SUB%; font-size:12px; margin-top:10px;">数据来源: Z700 具身方案技术协议 v3 · 光模块工厂精细操作需求规格书 · 评估实测 (2026-08)。</div>
</body></html>""".replace("%BG%", _BG).replace("%CARD%", _CARD).replace("%BORDER%", _BORDER) \
    .replace("%TEXT%", _TEXT).replace("%SUB%", _SUB).replace("%ACCENT%", _ACCENT)


class FeatureListDialog(QDialog):
    """✨ Feature List 产品特征清单 — QTextBrowser 展示, 深色主题, 可调整大小"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Feature List · Z-MAX 产品特征清单")  # 禁 emoji (VcXsrv 变 ??)
        self.setMinimumSize(760, 560)
        self.resize(920, 680)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(f"QDialog{{background:{_BG};}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setStyleSheet(
            f"QTextBrowser{{background:{_BG}; color:{_TEXT}; border:1px solid {_BORDER};"
            f" border-radius:4px; padding:8px;}}")
        self._browser.setHtml(_HTML)
        lay.addWidget(self._browser, 1)

        h = QHBoxLayout()
        h.addStretch()
        b_close = QPushButton("关闭")
        b_close.setStyleSheet(
            f"QPushButton{{background:{_CARD}; color:{_TEXT}; border:1px solid {_BORDER};"
            f" border-radius:4px; padding:6px 22px; font-size:12px;}}"
            f"QPushButton:hover{{background:{_BORDER};}}")
        b_close.clicked.connect(self.close)
        h.addWidget(b_close)
        lay.addLayout(h)
