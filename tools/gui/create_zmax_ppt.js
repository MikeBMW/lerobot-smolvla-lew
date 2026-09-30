const pptxgen = require("pptxgenjs");

async function createPresentation() {
    const pres = new pptxgen();
    pres.layout = "LAYOUT_16x9";
    pres.author = "智蜂创元";
    pres.title = "Z-MAX 多模态动作专家 - 管理层汇报";

    const colors = {
        bg_dark: "0F172A",
        bg_card: "1E293B",
        primary: "3B82F6",
        secondary: "06B6D4",
        accent: "F59E0B",
        text_white: "F8FAFC",
        text_gray: "CBD5E1",
        success: "10B981",
        border: "334155"
    };

    // ====== Slide 1: 封面 ======
    const slide1 = pres.addSlide();
    slide1.background = { color: colors.bg_dark };
    slide1.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.15, fill: { color: colors.primary } });
    slide1.addText("Z-MAX", { x: 0.8, y: 1.2, w: 8.4, h: 1.2, fontSize: 72, fontFace: "Arial Black", color: colors.primary, bold: true, align: "left", margin: 0 });
    slide1.addText("多模态动作专家", { x: 0.8, y: 2.3, w: 8.4, h: 0.8, fontSize: 44, fontFace: "Arial", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slide1.addShape(pres.shapes.LINE, { x: 0.8, y: 3.3, w: 3, h: 0, line: { color: colors.accent, width: 3 } });
    slide1.addText([
        { text: "光模块工厂智能插拔解决方案", options: { fontSize: 24, color: colors.text_gray, breakLine: true } },
        { text: " ", options: { fontSize: 16, breakLine: true } },
        { text: "±0.02mm 精度  |  99.2% 成功率  |  L4级全自主", options: { fontSize: 18, color: colors.accent, bold: true } }
    ], { x: 0.8, y: 3.6, w: 8.4, h: 1.5, fontFace: "Arial", align: "left", margin: 0 });
    slide1.addShape(pres.shapes.RECTANGLE, { x: 0, y: 6.8, w: 10, h: 0.7, fill: { color: colors.bg_card } });
    slide1.addText("智蜂创元 | 具身机器人产品解决方案", { x: 0.8, y: 6.95, w: 8.4, h: 0.4, fontSize: 14, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0 });

    // ====== Slide 2: 品牌介绍 ======
    const slideBrand = pres.addSlide();
    slideBrand.background = { color: colors.bg_dark };
    slideBrand.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.15, fill: { color: colors.accent } });
    slideBrand.addText("核心产品形态", { x: 0.8, y: 0.5, w: 8.4, h: 0.7, fontSize: 36, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slideBrand.addShape(pres.shapes.LINE, { x: 0.8, y: 1.3, w: 2, h: 0, line: { color: colors.accent, width: 2 } });
    slideBrand.addText([
        { text: "Z-MAX ", options: { fontSize: 28, color: colors.primary, bold: true } },
        { text: "智蜂 - 多模态动作专家", options: { fontSize: 28, color: colors.text_white, bold: true } }
    ], { x: 0.8, y: 1.5, w: 8.4, h: 0.6, fontFace: "Arial", align: "left", margin: 0 });

    // 命名逻辑区域
    slideBrand.addText("命名逻辑", { x: 0.8, y: 2.2, w: 8.4, h: 0.4, fontSize: 16, fontFace: "Arial", color: colors.text_gray, italic: true, align: "left", margin: 0 });

    // 智蜂 Z-Bee 卡片
    slideBrand.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 2.7, w: 8.4, h: 1.0, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
    slideBrand.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 2.7, w: 0.08, h: 1.0, fill: { color: colors.accent } });
    slideBrand.addText([
        { text: "智蜂 Z-Bee", options: { fontSize: 18, color: colors.accent, bold: true } },
        { text: "  ·  精密、高效、协同的工业级品牌IP", options: { fontSize: 16, color: colors.text_white } }
    ], { x: 1.1, y: 2.9, w: 7.9, h: 0.4, fontFace: "Arial", align: "left", margin: 0 });

    // Z-MAX 四维含义
    slideBrand.addText("Z-MAX 四维含义", { x: 0.8, y: 3.9, w: 8.4, h: 0.4, fontSize: 16, fontFace: "Arial", color: colors.text_gray, italic: true, align: "left", margin: 0 });

    const dimensions = [
        { letter: "Z", full: "潜在特征空间", capability: "L4级全域感知与认知底座", color: colors.primary },
        { letter: "M", full: "模态", capability: "L4级感官融合与自适应泛化", color: colors.secondary },
        { letter: "A", full: "Action / 动作", capability: "L4级精细力控与动态执行", color: colors.success },
        { letter: "X", full: "eXpert / 专家", capability: "L4级自主决策与全自主闭环", color: colors.accent }
    ];

    dimensions.forEach((dim, idx) => {
        const cardY = 4.4 + idx * 0.65;
        slideBrand.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: cardY, w: 0.65, h: 0.55, fill: { color: dim.color } });
        slideBrand.addText(dim.letter, { x: 0.8, y: cardY + 0.08, w: 0.65, h: 0.35, fontSize: 22, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "center", margin: 0 });
        slideBrand.addText([
            { text: dim.full, options: { fontSize: 14, color: colors.text_white, bold: true } },
            { text: "  →  ", options: { fontSize: 14, color: colors.text_gray } },
            { text: dim.capability, options: { fontSize: 13, color: colors.text_gray } }
        ], { x: 1.6, y: cardY + 0.08, w: 7.6, h: 0.35, fontFace: "Arial", align: "left", margin: 0 });
    });

    // 品牌注册备选
    slideBrand.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 7.0, w: 8.4, h: 0.7, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
    slideBrand.addText([
        { text: "品牌注册备选  |  ", options: { fontSize: 12, color: colors.text_gray, breakLine: false } },
        { text: "R-MAX", options: { fontSize: 13, color: colors.primary, bold: true, breakLine: false } },
        { text: "  ·  ", options: { fontSize: 13, color: colors.text_gray, breakLine: false } },
        { text: "RB-MAX", options: { fontSize: 13, color: colors.secondary, bold: true, breakLine: false } },
        { text: "  ·  ", options: { fontSize: 13, color: colors.text_gray, breakLine: false } },
        { text: "Z-BOT", options: { fontSize: 13, color: colors.success, bold: true } }
    ], { x: 1.0, y: 7.15, w: 8.0, h: 0.4, fontFace: "Arial", align: "center", margin: 0 });

    // ====== Slide 3: 智能化分级体系 ======
    const slide2 = pres.addSlide();
    slide2.background = { color: colors.bg_dark };
    slide2.addText("智能化分级体系 (L1-L5)", { x: 0.8, y: 0.5, w: 8.4, h: 0.7, fontSize: 36, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slide2.addShape(pres.shapes.LINE, { x: 0.8, y: 1.3, w: 2, h: 0, line: { color: colors.primary, width: 2 } });

    const levels = [
        { level: "L2", title: "基础驱动平台", systems: "System 0 + System 2", desc: "硬件底座与安全层", color: colors.success },
        { level: "L3", title: "条件自主插拔", systems: "System 0 + 11 + 2", desc: "单工位自动插拔", color: colors.secondary },
        { level: "L4", title: "全域无人插拔", systems: "System 0+11+12+2", desc: "产线级全自主", color: colors.accent },
        { level: "L5", title: "全域通用", systems: "全栈系统", desc: "跨场景泛化", color: "EC4899" }
    ];

    levels.forEach((item, idx) => {
        const col = idx % 2;
        const row = Math.floor(idx / 2);
        const cardX = 0.8 + col * 4.5;
        const cardYPos = 1.7 + row * 2.1;
        slide2.addShape(pres.shapes.RECTANGLE, { x: cardX, y: cardYPos, w: 4.2, h: 1.8, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
        slide2.addShape(pres.shapes.RECTANGLE, { x: cardX, y: cardYPos, w: 0.08, h: 1.8, fill: { color: item.color } });
        slide2.addText(item.level, { x: cardX + 0.3, y: cardYPos + 0.2, w: 0.8, h: 0.5, fontSize: 28, fontFace: "Arial Black", color: item.color, bold: true, align: "center", margin: 0 });
        slide2.addText(item.title, { x: cardX + 1.2, y: cardYPos + 0.2, w: 2.8, h: 0.5, fontSize: 18, fontFace: "Arial", color: colors.text_white, bold: true, align: "left", margin: 0 });
        slide2.addText(item.systems, { x: cardX + 0.3, y: cardYPos + 0.8, w: 3.7, h: 0.4, fontSize: 12, fontFace: "Arial", color: colors.secondary, bold: true, align: "left", margin: 0 });
        slide2.addText(item.desc, { x: cardX + 0.3, y: cardYPos + 1.2, w: 3.7, h: 0.4, fontSize: 13, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0 });
    });
    slide2.addText("* 基于《智算中枢·智能化技术标准》Q/ZFCY001.1-2026", { x: 0.8, y: 6.2, w: 8.4, h: 0.3, fontSize: 11, fontFace: "Arial", color: colors.text_gray, italic: true, align: "left", margin: 0 });

    // ====== Slide 3: L2级详情 ======
    const slide3 = pres.addSlide();
    slide3.background = { color: colors.bg_dark };
    slide3.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 1.2, fill: { color: colors.success } });
    slide3.addText("L2 - 基础驱动平台", { x: 0.8, y: 0.25, w: 8.4, h: 0.7, fontSize: 32, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "left", margin: 0 });

    // System 0 卡片
    slide3.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 1.5, w: 4, h: 2.5, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
    slide3.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 1.5, w: 0.06, h: 2.5, fill: { color: colors.primary } });
    slide3.addText("System 0", { x: 1.1, y: 1.6, w: 3.5, h: 0.4, fontSize: 18, fontFace: "Arial", color: colors.primary, bold: true, align: "left", margin: 0 });
    slide3.addText([
        { text: "L2基石层", options: { bold: true, breakLine: true } },
        { text: "• 硬件驱动 (EtherCAT/Modbus)", options: { breakLine: true } },
        { text: "• 力控安全系统（≤50N全域停机）", options: { breakLine: true } },
        { text: "• 急停与保护机制（双冗余）", options: { breakLine: true } },
        { text: "• 运动控制基础（运动学正逆解）", options: {} }
    ], { x: 1.1, y: 2.1, w: 3.5, h: 1.7, fontSize: 12, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0, paraSpaceAfter: 4 });

    // System 2 卡片
    slide3.addShape(pres.shapes.RECTANGLE, { x: 5.2, y: 1.5, w: 4, h: 2.5, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
    slide3.addShape(pres.shapes.RECTANGLE, { x: 5.2, y: 1.5, w: 0.06, h: 2.5, fill: { color: colors.secondary } });
    slide3.addText("System 2", { x: 5.5, y: 1.6, w: 3.5, h: 0.4, fontSize: 18, fontFace: "Arial", color: colors.secondary, bold: true, align: "left", margin: 0 });
    slide3.addText([
        { text: "L4大脑层", options: { bold: true, breakLine: true } },
        { text: "• 云端智能体（任务规划与拆解）", options: { breakLine: true } },
        { text: "• 任务调度与状态监控", options: { breakLine: true } },
        { text: "• 异常处理策略", options: { breakLine: true } },
        { text: "• 数据收集与反馈", options: {} }
    ], { x: 5.5, y: 2.1, w: 3.5, h: 1.7, fontSize: 12, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0, paraSpaceAfter: 4 });

    // 功能特点 - 控制在页面内（y: 4.3 开始，高度 2.0）
    slide3.addText("功能特点", { x: 0.8, y: 4.3, w: 3, h: 0.4, fontSize: 20, fontFace: "Arial", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slide3.addText([
        { text: "✓ ", options: { color: colors.success, bold: true } },
        { text: "硬件底座搭建完成，系统稳定运行", options: { breakLine: true } },
        { text: "✓ ", options: { color: colors.success, bold: true } },
        { text: "安全保护层激活，具备基础运动能力", options: { breakLine: true } },
        { text: "✓ ", options: { color: colors.success, bold: true } },
        { text: "可接收云端任务指令，执行人工示教轨迹", options: { breakLine: true } },
        { text: "✗ ", options: { color: colors.accent, bold: true } },
        { text: "不具备自主插拔能力，依赖人工干预", options: {} }
    ], { x: 0.8, y: 4.8, w: 8.4, h: 1.7, fontSize: 14, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0, paraSpaceAfter: 6 });

    // ====== Slide 4: L3级详情 ======
    const slide4 = pres.addSlide();
    slide4.background = { color: colors.bg_dark };
    slide4.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 1.2, fill: { color: colors.secondary } });
    slide4.addText("L3 - 条件自主插拔", { x: 0.8, y: 0.25, w: 8.4, h: 0.7, fontSize: 32, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "left", margin: 0 });

    // 三列系统配置 - 使用SYS-11命名
    const sys3 = [
        { name: "System 0", sub: "L2基石层", color: colors.primary, items: ["硬件驱动层", "力控安全", "急停保护", "运动控制基础"] },
        { name: "SYS-11", sub: "L3动作系统", color: colors.accent, items: ["SmolVLA动作模型", "DiT-B动作头", "端侧推理 <10ms", "精细力控执行"] },
        { name: "System 2", sub: "L4大脑层", color: colors.secondary, items: ["云端智能体", "任务调度", "状态监控", "异常处理"] }
    ];

    sys3.forEach((sys, idx) => {
        const cardX = 0.8 + idx * 3.1;
        slide4.addShape(pres.shapes.RECTANGLE, { x: cardX, y: 1.5, w: 2.9, h: 2.8, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
        slide4.addShape(pres.shapes.RECTANGLE, { x: cardX, y: 1.5, w: 0.06, h: 2.8, fill: { color: sys.color } });
        slide4.addText(sys.name, { x: cardX + 0.2, y: 1.6, w: 2.5, h: 0.4, fontSize: 16, fontFace: "Arial", color: sys.color, bold: true, align: "left", margin: 0 });
        slide4.addText(sys.sub, { x: cardX + 0.2, y: 2.0, w: 2.5, h: 0.3, fontSize: 11, fontFace: "Arial", color: colors.text_gray, italic: true, align: "left", margin: 0 });
        slide4.addText(sys.items.map((item, i) => ({
            text: `• ${item}`,
            options: { breakLine: i < sys.items.length - 1 }
        })), { x: cardX + 0.2, y: 2.4, w: 2.5, h: 1.7, fontSize: 12, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0, paraSpaceAfter: 5 });
    });

    // 核心能力 - 控制在页面内
    slide4.addText("核心能力", { x: 0.8, y: 4.6, w: 3, h: 0.4, fontSize: 20, fontFace: "Arial", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slide4.addText([
        { text: "✓ ", options: { color: colors.success, bold: true } },
        { text: "单工位自动插拔能力，精度 ±0.02mm", options: { breakLine: true } },
        { text: "✓ ", options: { color: colors.success, bold: true } },
        { text: "SmolVLA 500M 模型端侧推理，响应 <10ms", options: { breakLine: true } },
        { text: "✓ ", options: { color: colors.success, bold: true } },
        { text: "支持结构化环境下的自动操作", options: { breakLine: true } },
        { text: "△ ", options: { color: colors.accent, bold: true } },
        { text: "需要人工处理异常情况和复杂故障", options: {} }
    ], { x: 0.8, y: 5.1, w: 8.4, h: 1.7, fontSize: 14, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0, paraSpaceAfter: 6 });

    // ====== Slide 5: L4级详情 ======
    const slide5 = pres.addSlide();
    slide5.background = { color: colors.bg_dark };
    slide5.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 1.2, fill: { color: colors.accent } });
    slide5.addText("L4 - 全域无人插拔", { x: 0.8, y: 0.25, w: 8.4, h: 0.7, fontSize: 32, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "left", margin: 0 });

    // 四列系统配置 - 使用SYS-11/SYS-12命名
    const sys4 = [
        { name: "System 0", sub: "L2基石", color: colors.primary, items: ["硬件驱动", "力控安全", "急停保护", "运动控制"] },
        { name: "SYS-11", sub: "L3动作", color: colors.accent, items: ["SmolVLA模型", "DiT-B动作头", "端侧推理", "精细力控"] },
        { name: "SYS-12", sub: "L3引导", color: "8B5CF6", items: ["LeWorldModel", "世界预测", "轨迹规划", "状态估计"] },
        { name: "System 2", sub: "L4大脑", color: colors.secondary, items: ["云端智能", "全局规划", "异常诊断", "自学习"] }
    ];

    sys4.forEach((sys, idx) => {
        const cardX = 0.8 + idx * 2.3;
        slide5.addShape(pres.shapes.RECTANGLE, { x: cardX, y: 1.5, w: 2.1, h: 2.8, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
        slide5.addShape(pres.shapes.RECTANGLE, { x: cardX, y: 1.5, w: 0.06, h: 2.8, fill: { color: sys.color } });
        slide5.addText(sys.name, { x: cardX + 0.15, y: 1.6, w: 1.85, h: 0.4, fontSize: 14, fontFace: "Arial", color: sys.color, bold: true, align: "left", margin: 0 });
        slide5.addText(sys.sub, { x: cardX + 0.15, y: 2.0, w: 1.85, h: 0.3, fontSize: 10, fontFace: "Arial", color: colors.text_gray, italic: true, align: "left", margin: 0 });
        slide5.addText(sys.items.map((item, i) => ({
            text: `• ${item}`,
            options: { breakLine: i < sys.items.length - 1 }
        })), { x: cardX + 0.15, y: 2.4, w: 1.85, h: 1.7, fontSize: 11, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0, paraSpaceAfter: 4 });
    });

    // 核心能力 - 控制在页面内
    slide5.addText("核心能力", { x: 0.8, y: 4.6, w: 3, h: 0.4, fontSize: 20, fontFace: "Arial", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slide5.addText([
        { text: "★ ", options: { color: colors.accent, bold: true } },
        { text: "产线级全自主无人插拔，7×24小时连续运行", options: { breakLine: true } },
        { text: "★ ", options: { color: colors.accent, bold: true } },
        { text: "SYS-11 + SYS-12 协同：动作系统与世界模型融合", options: { breakLine: true } },
        { text: "★ ", options: { color: colors.accent, bold: true } },
        { text: "具备异常自主诊断和恢复能力", options: { breakLine: true } },
        { text: "★ ", options: { color: colors.accent, bold: true } },
        { text: "成功率达 99.2%，达到工业级量产标准", options: {} }
    ], { x: 0.8, y: 5.1, w: 8.4, h: 1.7, fontSize: 14, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0, paraSpaceAfter: 6 });

    // ====== Slide 6: 系统架构总览 ======
    const slide6 = pres.addSlide();
    slide6.background = { color: colors.bg_dark };
    slide6.addText("系统架构总览", { x: 0.8, y: 0.5, w: 8.4, h: 0.7, fontSize: 36, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slide6.addShape(pres.shapes.LINE, { x: 0.8, y: 1.3, w: 2, h: 0, line: { color: colors.primary, width: 2 } });

    const architecture = [
        { layer: "L2基石层", system: "System 0", color: colors.primary, w: 2.8, x: 0.8, tech: "EtherCAT\n力控安全\n急停保护" },
        { layer: "L3/L4核心层", system: "SYS-11 / SYS-12", color: colors.accent, w: 3.6, x: 3.8, tech: "SmolVLA 500M\nDiT-B Action Head\nLeWorldModel 15M" },
        { layer: "L4大脑层", system: "System 2", color: colors.secondary, w: 2.4, x: 7.0, tech: "云端智能体\n任务规划\n全局调度" }
    ];

    architecture.forEach((arch) => {
        slide6.addShape(pres.shapes.RECTANGLE, { x: arch.x, y: 1.7, w: arch.w, h: 3.5, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
        slide6.addShape(pres.shapes.RECTANGLE, { x: arch.x, y: 1.7, w: arch.w, h: 0.08, fill: { color: arch.color } });
        slide6.addText(arch.layer, { x: arch.x + 0.2, y: 1.9, w: arch.w - 0.4, h: 0.5, fontSize: 16, fontFace: "Arial", color: arch.color, bold: true, align: "center", margin: 0 });
        slide6.addText(arch.system, { x: arch.x + 0.2, y: 2.4, w: arch.w - 0.4, h: 0.4, fontSize: 14, fontFace: "Arial", color: colors.text_white, bold: true, align: "center", margin: 0 });
        slide6.addText(arch.tech, { x: arch.x + 0.2, y: 2.9, w: arch.w - 0.4, h: 2.0, fontSize: 12, fontFace: "Arial", color: colors.text_gray, align: "center", margin: 0, paraSpaceAfter: 6 });
    });

    slide6.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 5.4, w: 8.4, h: 0.9, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
    slide6.addText([
        { text: "技术路线：", options: { bold: true, color: colors.text_white } },
        { text: "LeRobot (机器人框架) + SmolVLA (视觉-语言-动作) + LeWorldModel (世界模型) + DiT-B Flow-Matching (动作生成)", options: { color: colors.text_gray } }
    ], { x: 1.0, y: 5.6, w: 8.0, h: 0.5, fontSize: 13, fontFace: "Arial", align: "left", margin: 0 });

    // ====== Slide 7: 核心优势与商业价值 ======
    const slide7 = pres.addSlide();
    slide7.background = { color: colors.bg_dark };
    slide7.addText("核心优势与商业价值", { x: 0.8, y: 0.5, w: 8.4, h: 0.7, fontSize: 36, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slide7.addShape(pres.shapes.LINE, { x: 0.8, y: 1.3, w: 2, h: 0, line: { color: colors.accent, width: 2 } });

    const metrics = [
        { value: "±0.02", unit: "mm", label: "插拔精度", color: colors.primary },
        { value: "99.2", unit: "%", label: "成功率", color: colors.success },
        { value: "<10", unit: "ms", label: "端侧推理", color: colors.secondary },
        { value: "7×24", unit: "h", label: "连续运行", color: colors.accent }
    ];

    metrics.forEach((metric, idx) => {
        const col = idx % 2;
        const row = Math.floor(idx / 2);
        const cardX = 0.8 + col * 4.5;
        const cardY = 1.7 + row * 2.1;
        slide7.addShape(pres.shapes.RECTANGLE, { x: cardX, y: cardY, w: 4.2, h: 1.8, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
        slide7.addText([
            { text: metric.value, options: { fontSize: 48, bold: true, color: metric.color } },
            { text: ` ${metric.unit}`, options: { fontSize: 24, color: metric.color } }
        ], { x: cardX + 0.3, y: cardY + 0.3, w: 3.6, h: 0.9, fontFace: "Arial Black", align: "left", margin: 0 });
        slide7.addText(metric.label, { x: cardX + 0.3, y: cardY + 1.2, w: 3.6, h: 0.4, fontSize: 16, fontFace: "Arial", color: colors.text_gray, align: "left", margin: 0 });
    });

    slide7.addText([
        { text: "商业价值：", options: { bold: true, color: colors.text_white, fontSize: 14, breakLine: true } },
        { text: "• 人工成本降低 → ", options: { color: colors.text_gray } },
        { text: "单机替代2-3名熟练操作工", options: { color: colors.success, bold: true, breakLine: true } },
        { text: "• 良率提升 → ", options: { color: colors.text_gray } },
        { text: "减少人工损伤，良率从95%提升至99%+", options: { color: colors.success, bold: true, breakLine: true } },
        { text: "• 换型时间缩短 → ", options: { color: colors.text_gray } },
        { text: "从小时级降至分钟级，柔性生产成为可能", options: { color: colors.success, bold: true } }
    ], { x: 0.8, y: 5.9, w: 8.4, h: 0.7, fontSize: 13, fontFace: "Arial", align: "left", margin: 0 });

    // ====== Slide 8: 实施路线图 ======
    const slide8 = pres.addSlide();
    slide8.background = { color: colors.bg_dark };
    slide8.addText("实施路线图", { x: 0.8, y: 0.5, w: 8.4, h: 0.7, fontSize: 36, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "left", margin: 0 });
    slide8.addShape(pres.shapes.LINE, { x: 0.8, y: 1.3, w: 2, h: 0, line: { color: colors.primary, width: 2 } });

    const timeline = [
        { phase: "Phase 1", quarter: "2026 Q3", title: "L2基础搭建", desc: "硬件底座完成\n安全层激活", color: colors.success },
        { phase: "Phase 2", quarter: "2026 Q4", title: "L3单工位验证", desc: "SmolVLA部署\n条件自主插拔", color: colors.secondary },
        { phase: "Phase 3", quarter: "2027 Q1-Q2", title: "L4产线落地", desc: "SYS-11+12融合\n全域无人插拔", color: colors.accent },
        { phase: "Phase 4", quarter: "2027+", title: "规模化复制", desc: "多产线部署\n持续优化", color: "EC4899" }
    ];

    timeline.forEach((item, idx) => {
        const cardX = 0.8 + idx * 2.3;
        if (idx < timeline.length - 1) {
            slide8.addShape(pres.shapes.LINE, { x: cardX + 2.2, y: 2.5, w: 0.2, h: 0, line: { color: colors.border, width: 2 } });
        }
        slide8.addShape(pres.shapes.RECTANGLE, { x: cardX, y: 1.7, w: 2.1, h: 3.8, fill: { color: colors.bg_card }, line: { color: colors.border, width: 1 } });
        slide8.addShape(pres.shapes.RECTANGLE, { x: cardX, y: 1.7, w: 2.1, h: 0.08, fill: { color: item.color } });
        slide8.addText(item.phase, { x: cardX + 0.15, y: 1.9, w: 1.85, h: 0.4, fontSize: 14, fontFace: "Arial", color: item.color, bold: true, align: "center", margin: 0 });
        slide8.addText(item.quarter, { x: cardX + 0.15, y: 2.3, w: 1.85, h: 0.4, fontSize: 16, fontFace: "Arial Black", color: colors.text_white, bold: true, align: "center", margin: 0 });
        slide8.addText(item.title, { x: cardX + 0.15, y: 2.8, w: 1.85, h: 0.7, fontSize: 13, fontFace: "Arial", color: colors.text_white, bold: true, align: "center", margin: 0 });
        slide8.addText(item.desc, { x: cardX + 0.15, y: 3.6, w: 1.85, h: 1.6, fontSize: 11, fontFace: "Arial", color: colors.text_gray, align: "center", margin: 0, paraSpaceAfter: 4 });
    });

    // 保存文件 - 保存到两个位置
    const outputPath = "/home/admin/xspace/lerobot-smolvla-lew/tools/gui/Z-MAX管理层汇报.pptx";
    await pres.writeFile({ fileName: outputPath });
    console.log("✓ PPT生成成功:", outputPath);
}

createPresentation().catch(err => {
    console.error("Error:", err);
    process.exit(1);
});
