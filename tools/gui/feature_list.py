# -*- coding: utf-8 -*-
"""✨ Feature List · Z-MAX 产品特征清单 (2026-08-19 老倪)

右侧下拉菜单「帮助文档」→ Feature List 弹窗。
视角: 工程需求 / 标准接口 / 展品特征 — 偏向 场景·功能·标准接口·性能指标。
与能力库 feature.dbc 对应: 弹窗含「模型能力」区块 (当前模型能力组合),
支持一键导出 Excel (能力库/模型组合/接口说明 3 sheets)。
"""
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QTextBrowser, QPushButton,
                             QHBoxLayout, QLabel)

_BG = "#0d1117"
_CARD = "#161b22"
_BORDER = "#30363d"
_TEXT = "#e6edf3"
_SUB = "#8b949e"
_ACCENT = "#58a6ff"

# 产品/展品特征 (静态部分)
_PRODUCT_HTML = """
<h2 style="color:%(accent)s; margin:4px 0 2px;">Feature List · Z-MAX 产品特征清单</h2>
<div style="color:%(sub)s; font-size:12px; margin-bottom:10px;">Z700 / Z700F · 面向光模块工厂精细操作 · 与能力库 feature.dbc 对应</div>

<h3 style="color:%(accent)s; margin:10px 0 4px;">1. 产品定位</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %(border)s; border-collapse:collapse;">
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s; width:90px;"><b>Z700</b></td><td style="border:1px solid %(border)s;">L4 全自主具身智能机器人 — 感知、决策、操作全链路本地自主完成</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>Z700F</b></td><td style="border:1px solid %(border)s;">Fix L2 固定工位作业单元 — 单工位精细操作，部署即用</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>服务对象</b></td><td style="border:1px solid %(border)s;">光模块工厂 (100G/400G/800G 模块, QSFP-DD/OSFP 封装) 精细操作产线</td></tr>
</table>

<h3 style="color:%(accent)s; margin:10px 0 4px;">2. 应用场景（5 大场景 · 符合技术协议）</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %(border)s; border-collapse:collapse; width:100%;">
<tr style="background:%(card)s; color:%(accent)s;">
<td style="border:1px solid %(border)s; width:24px;">#</td><td style="border:1px solid %(border)s;">场景</td><td style="border:1px solid %(border)s;">作业对象</td><td style="border:1px solid %(border)s;">工位/设备</td><td style="border:1px solid %(border)s;">单颗节拍</td><td style="border:1px solid %(border)s;">成功率</td></tr>
<tr><td style="border:1px solid %(border)s;">1</td><td style="border:1px solid %(border)s;">FW Loading + EEPROM 写/读</td><td style="border:1px solid %(border)s;">100G/400G/800G 成品模块</td><td style="border:1px solid %(border)s;">桌面 EVB 子板+主板+底座</td><td style="border:1px solid %(border)s;">≤6 s</td><td style="border:1px solid %(border)s;">≥99%</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;">2</td><td style="border:1px solid %(border)s;">上下料搬运</td><td style="border:1px solid %(border)s;">料盘/料箱（多载具柔性）</td><td style="border:1px solid %(border)s;">跨工位配送</td><td style="border:1px solid %(border)s;">按趟</td><td style="border:1px solid %(border)s;">≥99.5%</td></tr>
<tr><td style="border:1px solid %(border)s;">3</td><td style="border:1px solid %(border)s;">BI 老化箱模块插拔</td><td style="border:1px solid %(border)s;">成品模块 (QSFP~10颗/屉, OSFP~16颗/屉)</td><td style="border:1px solid %(border)s;">抽屉式老化箱</td><td style="border:1px solid %(border)s;">单颗≤60 s</td><td style="border:1px solid %(border)s;">≥99%</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;">4</td><td style="border:1px solid %(border)s;">热海柜体 电口+光口插拔</td><td style="border:1px solid %(border)s;">100G/400G/800G (QSFP/OSFP)</td><td style="border:1px solid %(border)s;">柜体 50cm 高 600mm 宽</td><td style="border:1px solid %(border)s;">≤20 s</td><td style="border:1px solid %(border)s;">≥99%</td></tr>
<tr><td style="border:1px solid %(border)s;">5</td><td style="border:1px solid %(border)s;">ATS / 线外检测插接</td><td style="border:1px solid %(border)s;">100G C4 等模块</td><td style="border:1px solid %(border)s;">ATS 测试座/线外检测工位</td><td style="border:1px solid %(border)s;">≤15 s</td><td style="border:1px solid %(border)s;">≥99%</td></tr>
</table>
<div style="color:%(sub)s; font-size:12px;">节拍为不可妥协的物理硬指标（顶层约束），成功率按 10 次插拔验收口径统计。</div>

<h3 style="color:%(accent)s; margin:10px 0 4px;">3. 核心功能（工程需求视角）</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %(border)s; border-collapse:collapse; width:100%;">
<tr style="background:%(card)s; color:%(accent)s;"><td style="border:1px solid %(border)s; width:130px;">功能项</td><td style="border:1px solid %(border)s;">说明</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>端侧自主作业</b></td><td style="border:1px solid %(border)s;">感知→决策→动作全链路在机端完成，不依赖云端网络，满足 24h 连续作业</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>精细操作技能库</b></td><td style="border:1px solid %(border)s;">抓取 / 搬运 / 对准 / 插拔 / 压合等原子技能，可组合编排成完整作业流程</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>力控保护</b></td><td style="border:1px solid %(border)s;">触觉反馈实时力控，插拔过程保护模块金手指与壳体，不损伤工件</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>多阶段作业编排</b></td><td style="border:1px solid %(border)s;">接近/抓取/抬起/转移/插入分阶段调度，各阶段独立标定，全程可追溯</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>边学边练闭环</b></td><td style="border:1px solid %(border)s;">现场采集数据 → 自动训练 → 热更新部署，产线数据持续反哺能力提升</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>仿真先行验证</b></td><td style="border:1px solid %(border)s;">作业策略先在仿真环境验证成功率与动作质量，达标后再迁移真机，降低现场风险</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>多方案统一管理</b></td><td style="border:1px solid %(border)s;">多套作业方案统一配置、一键对比评估（成功率/动作幅度/耗时），择优部署</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>大屏指标监督</b></td><td style="border:1px solid %(border)s;">成功率/节拍/力值等 KPI 实时上报大屏，异常即时告警</td></tr>
</table>

<h3 style="color:%(accent)s; margin:10px 0 4px;">4. 标准接口</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %(border)s; border-collapse:collapse; width:100%;">
<tr style="background:%(card)s; color:%(accent)s;"><td style="border:1px solid %(border)s; width:130px;">接口</td><td style="border:1px solid %(border)s;">说明</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>部署接口</b></td><td style="border:1px solid %(border)s;">模型文件 (safetensors) 热更新，机端监听自动拉取生效，无需停机</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>数据接口</b></td><td style="border:1px solid %(border)s;">标准数据集格式（视频帧 + 状态 + 动作），SN 绑定可追溯，支持增量采集</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>监控接口</b></td><td style="border:1px solid %(border)s;">指标 HTTP 上报（成功率/节拍/力值/状态），对接大屏与上位系统</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>消息接口</b></td><td style="border:1px solid %(border)s;">训练完成 / 视频 / 报告自动推送飞书，产线人员无需盯屏</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>Web 接口</b></td><td style="border:1px solid %(border)s;">datadrive.world 网页端监控与演示，手机可访问</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>训练接口</b></td><td style="border:1px solid %(border)s;">容器化 GPU 训练环境，标准配置一键训练，训练产物版本化管理</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>硬件接口</b></td><td style="border:1px solid %(border)s;">7 轴机械臂 + 视觉 + 触觉传感，Orin 机端推理，与产线 PLC/联锁信号对接</td></tr>
</table>

<h3 style="color:%(accent)s; margin:10px 0 4px;">5. 性能指标</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid %(border)s; border-collapse:collapse; width:100%;">
<tr style="background:%(card)s; color:%(accent)s;"><td style="border:1px solid %(border)s;">指标</td><td style="border:1px solid %(border)s;">规格/实测</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>插拔成功率</b></td><td style="border:1px solid %(border)s;">验收口径 ≥99%（10 次插拔统计）；仿真实测：抓起 6-8/8、插入 4-6/8（多 seed 取波动区间，持续优化中）</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>作业节拍</b></td><td style="border:1px solid %(border)s;">按场景 ≤6 s ~ ≤60 s（详见第 2 节），节拍为物理硬指标</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>负载能力</b></td><td style="border:1px solid %(border)s;">插拔类负载 &gt;1.00 kg；搬运类 ≥5 kg</td></tr>
<tr style="background:%(card)s;"><td style="border:1px solid %(border)s;"><b>端侧轻量化</b></td><td style="border:1px solid %(border)s;">端侧决策模型 &lt;1M 参数级，机端实时推理（插拔循环 0.64M 规模）</td></tr>
<tr><td style="border:1px solid %(border)s;"><b>连续作业</b></td><td style="border:1px solid %(border)s;">24 小时不间断，无尘车间 Class 1000 环境适配，全流程 SN 可追溯</td></tr>
</table>
"""


def _build_model_cap_html(module=None):
    """🧩 模型能力区块 (与 feature.dbc 对应, 模型体现能力)"""
    try:
        import feature_dbc as _fdb
        from model_feature import current_model_key
        dbc = _fdb.load_dbc()
        if not dbc:
            return ""
        key = current_model_key(module) if module is not None else None
        caps = dbc.get("capabilities", {})
        mans = dbc.get("manifests", {})
        rows = []
        for node, ids in mans.items():
            cur = " ← 当前" if (key and node == key.upper()) else ""
            names = " · ".join(f"{i} {caps.get(i, {}).get('name', i)}" for i in sorted(ids))
            is_cur = bool(key and node == key.upper())
            tr_style = f' style="background:{_CARD};"' if is_cur else ""
            rows.append(
                f'<tr{tr_style}>'
                f'<td style="border:1px solid {_BORDER};"><b>{node}{cur}</b></td>'
                f'<td style="border:1px solid {_BORDER};">{names}</td></tr>')
        return f"""
<h3 style="color:{_ACCENT}; margin:10px 0 4px;">6. 模型能力（feature.dbc 对应）</h3>
<table border="0" cellspacing="0" cellpadding="4" style="border:1px solid {_BORDER}; border-collapse:collapse; width:100%;">
<tr style="background:{_CARD}; color:{_ACCENT};"><td style="border:1px solid {_BORDER}; width:130px;">模型节点</td><td style="border:1px solid {_BORDER};">能力组合（→ 数据字典 feature.dbc 完整定义）</td></tr>
{''.join(rows)}
</table>
<div style="color:{_SUB}; font-size:12px;">每条能力的解释/接口定义/输入输出信号见数据字典「🧩 能力数据库 feature.dbc」或导出 Excel。</div>
"""
    except Exception:
        return ""


def _build_html(module=None):
    _html = _PRODUCT_HTML
    for _k, _v in (("%(accent)s", _ACCENT), ("%(border)s", _BORDER),
                   ("%(card)s", _CARD), ("%(sub)s", _SUB),
                   ("%(text)s", _TEXT), ("%(bg)s", _BG)):
        _html = _html.replace(_k, _v)
    return _html + _build_model_cap_html(module) + f"""
<div style="color:{_SUB}; font-size:12px; margin-top:10px;">数据来源: Z700 具身方案技术协议 v3 · 光模块工厂精细操作需求规格书 · 评估实测 (2026-08) · 能力库 feature.dbc。</div>
</body></html>"""


class FeatureListDialog(QDialog):
    """✨ Feature List 产品特征清单 — QTextBrowser 展示, 深色主题, 可调整大小
    module: SimulinkModule (可选) — 用于定位当前模型, 展示模型能力区块"""

    def __init__(self, parent=None, module=None):
        super().__init__(parent)
        self._module = module
        self.setWindowTitle("Feature List · Z-MAX 产品特征清单")  # 禁 emoji (VcXsrv 变 ??)
        self.setMinimumSize(760, 560)
        self.resize(920, 680)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(f"QDialog{{background:{_BG};}}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        self._browser = _FLTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setStyleSheet(
            f"QTextBrowser{{background:{_BG}; color:{_TEXT}; border:1px solid {_BORDER};"
            f" border-radius:4px; padding:8px;}}")
        self._browser.setHtml(_build_html(module))
        lay.addWidget(self._browser, 1)

        h = QHBoxLayout()
        self._lbl_res = QLabel("")
        self._lbl_res.setStyleSheet(
            f"color:{_SUB}; font-size:12px; background:transparent; border:none;")
        h.addWidget(self._lbl_res)
        h.addStretch()
        b_xlsx = QPushButton("导出 Excel")
        b_close = QPushButton("关闭")
        for b in (b_xlsx, b_close):
            b.setStyleSheet(
                f"QPushButton{{background:{_CARD}; color:{_TEXT}; border:1px solid {_BORDER};"
                f" border-radius:4px; padding:6px 22px; font-size:12px;}}"
                f"QPushButton:hover{{background:{_BORDER};}}")
        b_xlsx.clicked.connect(self._export_excel)
        b_close.clicked.connect(self.close)
        h.addWidget(b_xlsx)
        h.addWidget(b_close)
        lay.addLayout(h)

    def _export_excel(self):
        """导出能力库 Excel 并上传 datadrive.world (用户可下载)"""
        try:
            from feature_dbc import upload_excel
            path, url = upload_excel()
            if url:
                self._lbl_res.setText(f"✅ 已导出并上传: {url} (浏览器打开下载)")
            else:
                self._lbl_res.setText(f"✅ 已导出(本机): {path}")
        except Exception as ex:
            self._lbl_res.setText(f"⚠️ 导出失败: {ex}")


class _FLTextBrowser(QTextBrowser):
    """🐛 2026-08-19 老倪报: Feature List 滚动条拖动只更新左侧窄条, 右侧残留不动
    = VcXsrv XCopyArea 半移 bug (滚动搬运只画部分区域)。内容区小 (7KB HTML),
    滚动后强制 viewport 全量重绘, 代价无感, 画面完整正确。"""

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        try:
            self.viewport().update()
        except Exception:
            pass
