from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "ux-flow-board.png"
W, H = 2400, 1500

INK = (7, 24, 64)
MUTED = (112, 126, 156)
LINE = (219, 230, 247)
SOFT = (246, 249, 255)
BLUE = (31, 114, 255)
PURPLE = (115, 87, 255)
GREEN = (34, 183, 122)
ORANGE = (255, 173, 50)
WHITE = (255, 255, 255)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for item in candidates:
        p = Path(item)
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


F = {
    "brand": font(38, True),
    "h1": font(46, True),
    "h2": font(30, True),
    "h3": font(18, True),
    "body": font(15),
    "small": font(12),
    "tiny": font(10),
    "bold": font(15, True),
}


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))


def gradient(size: tuple[int, int], c1: tuple[int, int, int], c2: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", size, c1)
    px = img.load()
    w, h = size
    for y in range(h):
        for x in range(w):
            px[x, y] = mix(c1, c2, (x + y) / (w + h))
    return img


def rounded(draw: ImageDraw.ImageDraw, box, r=14, fill=WHITE, outline=LINE, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def shadowed(img: Image.Image, box, r=18, fill=WHITE, outline=LINE):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    x1, y1, x2, y2 = box
    for i, alpha in enumerate([18, 12, 8, 5]):
        od.rounded_rectangle((x1 - i * 2, y1 + 8 + i * 3, x2 + i * 2, y2 + 12 + i * 3), radius=r + i, fill=(29, 74, 140, alpha))
    img.alpha_composite(overlay)
    draw = ImageDraw.Draw(img)
    rounded(draw, box, r, fill, outline)


def text(draw: ImageDraw.ImageDraw, xy, s: str, f=None, fill=INK, anchor=None):
    draw.text(xy, s, font=f or F["body"], fill=fill, anchor=anchor)


def pill(draw, box, label, fill=(234, 246, 240), fg=GREEN):
    rounded(draw, box, 18, fill, None, 0)
    text(draw, (box[0] + 12, box[1] + 6), label, F["tiny"], fg)


def logo(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 58):
    rounded(draw, (x, y, x + size, y + size), 16, BLUE, None, 0)
    draw.rounded_rectangle((x, y, x + size, y + size), 16, fill=None)
    nodes = [(x + 13, y + 14), (x + 42, y + 20), (x + 19, y + 42), (x + 43, y + 43)]
    for a, b in [(0, 1), (0, 2), (1, 3), (2, 3), (1, 2)]:
        draw.line((nodes[a][0], nodes[a][1], nodes[b][0], nodes[b][1]), fill=(238, 246, 255), width=4)
    for nx, ny in nodes:
        draw.ellipse((nx - 6, ny - 6, nx + 6, ny + 6), fill=(255, 255, 255), outline=(238, 246, 255), width=2)


def nav(draw, x, y, active="产品问答"):
    logo(draw, x + 12, y + 18, 28)
    text(draw, (x + 50, y + 21), "知识库", F["h3"])
    items = [("产品问答", "常见问题与解答", "□"), ("固件助手", "相关知识与说明", "▣"), ("操作手册", "指南与步骤", "▤")]
    yy = y + 74
    for title, sub, icon in items:
        bg = (236, 244, 255) if title == active else (250, 253, 255)
        rounded(draw, (x + 10, yy, x + 132, yy + 48), 12, bg, None, 0)
        text(draw, (x + 22, yy + 12), icon, F["body"], BLUE)
        text(draw, (x + 46, yy + 8), title, F["bold"])
        text(draw, (x + 46, yy + 29), sub, F["tiny"], MUTED)
        yy += 58
    draw.line((x + 14, yy + 10, x + 128, yy + 10), fill=LINE)
    text(draw, (x + 16, yy + 28), "最近会话", F["bold"])
    for i, h in enumerate(["电池充电截止电压是多少？", "设备休眠功耗优化方案", "Bootloader 升级流程"]):
        fill = BLUE if i == 0 else MUTED
        text(draw, (x + 16, yy + 58 + i * 30), h, F["tiny"], fill)


def screen(img, xy, title, step, kind):
    draw = ImageDraw.Draw(img)
    x, y = xy
    text(draw, (x, y - 38), f"{step}  {title}", F["h3"], INK)
    draw.ellipse((x - 42, y - 44, x - 12, y - 14), fill=BLUE)
    text(draw, (x - 27, y - 40), str(step), F["small"], WHITE, "ma")
    shadowed(img, (x, y, x + 720, y + 520), 22, (252, 254, 255), LINE)
    draw = ImageDraw.Draw(img)
    draw.rectangle((x + 142, y + 1, x + 143, y + 519), fill=LINE)
    draw.rectangle((x + 542, y + 1, x + 543, y + 519), fill=LINE)
    nav(draw, x, y, "产品问答")
    main_x, right_x = x + 162, x + 560
    rounded(draw, (main_x, y + 22, main_x + 330, y + 58), 12, WHITE, LINE)
    text(draw, (main_x + 16, y + 32), "⌕ 搜索文档、问题或术语", F["small"], MUTED)

    if kind == "home":
        text(draw, (main_x + 85, y + 96), "今天想查什么？", F["h2"])
        rounded(draw, (main_x + 10, y + 145, main_x + 372, y + 220), 16, WHITE, (177, 199, 255), 2)
        text(draw, (main_x + 28, y + 170), "请输入你的问题，例如：电池充电截止电压是多少？", F["small"], MUTED)
        draw.ellipse((main_x + 326, y + 170, main_x + 360, y + 204), fill=BLUE)
        text(draw, (main_x + 343, y + 174), "↗", F["body"], WHITE, "ma")
        labels = ["总结文档", "查找参数", "解释术语", "生成步骤"]
        for i, label in enumerate(labels):
            bx = main_x + 12 + i * 93
            rounded(draw, (bx, y + 238, bx + 82, y + 275), 11, WHITE, LINE)
            text(draw, (bx + 16, y + 249), label, F["tiny"], INK)
        rounded(draw, (main_x + 10, y + 296, main_x + 372, y + 470), 16, WHITE, LINE)
        text(draw, (main_x + 28, y + 316), "我可访问的知识空间", F["bold"])
        for i, label in enumerate(["产品问答", "固件助手", "操作手册"]):
            bx = main_x + 28 + i * 116
            rounded(draw, (bx, y + 356, bx + 98, y + 428), 12, (248, 251, 255), LINE)
            text(draw, (bx + 20, y + 382), label, F["small"], INK)
        right_panel(draw, right_x, y, ["本次推荐能力", "精准检索", "引用溯源", "生成步骤"], ["常见问题", "如何查看固件版本？", "OTA 失败如何处理？", "如何导出设备日志？"])

    elif kind == "space":
        rounded(draw, (main_x + 10, y + 78, main_x + 372, y + 150), 14, WHITE, LINE)
        for i, (k, v) in enumerate([("健康度", "86%"), ("已索引", "128"), ("更新", "14:32")]):
            text(draw, (main_x + 28 + i * 115, y + 95), k, F["tiny"], MUTED)
            text(draw, (main_x + 28 + i * 115, y + 116), v, F["h3"], BLUE)
        for i, doc in enumerate(["产品说明书 v2.3.pdf", "电池管理设计指南.pdf", "固件设计规范 v1.8.pdf"]):
            yy = y + 174 + i * 82
            rounded(draw, (main_x + 10, yy, main_x + 372, yy + 66), 13, WHITE, LINE)
            text(draw, (main_x + 28, yy + 14), doc, F["bold"])
            text(draw, (main_x + 28, yy + 38), f"第 {45 - i * 9} 页 · 充电管理与关键电气参数", F["tiny"], MUTED)
            pill(draw, (main_x + 292, yy + 14, main_x + 350, yy + 36), "高相关" if i < 2 else "中相关", (232, 246, 240) if i < 2 else (255, 244, 226), GREEN if i < 2 else ORANGE)
        right_panel(draw, right_x, y, ["来源统计", "PDF 文档 82", "表格资料 21", "网页备忘 25"], ["空间操作", "索引更新策略", "成员与权限", "访问 KEY"])

    elif kind == "upload":
        rounded(draw, (main_x + 10, y + 82, main_x + 372, y + 212), 18, (248, 251, 255), (168, 194, 255), 2)
        text(draw, (main_x + 95, y + 119), "⇧ 拖拽 PDF、Word 或表格到这里", F["bold"], BLUE)
        text(draw, (main_x + 80, y + 148), "自动识别标题、章节、表格与图片内容", F["small"], MUTED)
        for i, doc in enumerate(["产品说明书 v2.4.pdf", "电池测试报告.xlsx"]):
            yy = y + 234 + i * 68
            rounded(draw, (main_x + 10, yy, main_x + 372, yy + 52), 12, WHITE, LINE)
            text(draw, (main_x + 28, yy + 10), doc, F["bold"])
            text(draw, (main_x + 28, yy + 31), "正在结构化切片" if i == 0 else "等待解析", F["tiny"], MUTED)
            if i == 0:
                draw.rounded_rectangle((main_x + 236, yy + 24, main_x + 342, yy + 31), 4, fill=(232, 238, 248))
                draw.rounded_rectangle((main_x + 236, yy + 24, main_x + 306, yy + 31), 4, fill=BLUE)
        rounded(draw, (main_x + 10, y + 386, main_x + 182, y + 426), 11, WHITE, LINE)
        text(draw, (main_x + 28, y + 397), "权限：研发部、售后组", F["tiny"], INK)
        rounded(draw, (main_x + 214, y + 386, main_x + 372, y + 426), 11, BLUE, None, 0)
        text(draw, (main_x + 258, y + 397), "开始解析", F["small"], WHITE)
        right_panel(draw, right_x, y, ["解析设置", "提取表格", "建立引用页码", "自动生成标签"], ["数据安全", "私有索引", "访问日志开启", "敏感词检测"])

    elif kind == "answer":
        rounded(draw, (main_x + 10, y + 76, main_x + 372, y + 130), 13, WHITE, LINE)
        text(draw, (main_x + 28, y + 91), "电池充电截止电压是多少？", F["bold"])
        text(draw, (main_x + 28, y + 113), "来源：产品问答 · 今天 14:32", F["tiny"], MUTED)
        rounded(draw, (main_x + 10, y + 148, main_x + 372, y + 198), 14, WHITE, (177, 199, 255), 2)
        text(draw, (main_x + 26, y + 164), "继续追问，例如：不同型号是否不同？", F["small"], MUTED)
        for i, s in enumerate(["理解问题", "检索资料", "提取证据", "生成回答"]):
            bx = main_x + 10 + i * 91
            rounded(draw, (bx, y + 214, bx + 80, y + 244), 10, WHITE, LINE)
            text(draw, (bx + 13, y + 222), "✓ " + s, F["tiny"], BLUE)
        rounded(draw, (main_x + 10, y + 264, main_x + 372, y + 460), 15, WHITE, LINE)
        text(draw, (main_x + 28, y + 284), "AI 回答", F["h3"])
        text(draw, (main_x + 28, y + 318), "结论：标准充电条件下，单节锂电池", F["small"], INK)
        text(draw, (main_x + 28, y + 342), "充电截止电压为 4.20V（±0.05V）。", F["small"], BLUE)
        text(draw, (main_x + 28, y + 378), "依据：产品规格书 v2.3.1 第 12 页；", F["tiny"], INK)
        text(draw, (main_x + 28, y + 400), "固件设计说明 v1.8.0 第 23 页。", F["tiny"], INK)
        right_panel(draw, right_x, y, ["引用来源", "产品规格书 v2.3.1", "固件设计说明", "硬件设计指南"], ["操作", "打开原文", "查看上下文", "导出资料"])

    elif kind == "preview":
        rounded(draw, (main_x + 10, y + 70, main_x + 372, y + 106), 10, WHITE, LINE)
        text(draw, (main_x + 24, y + 80), "← 产品问答 / 产品说明书 v2.3 / 第 45 页", F["tiny"], INK)
        rounded(draw, (main_x + 10, y + 128, main_x + 372, y + 462), 12, WHITE, LINE)
        text(draw, (main_x + 82, y + 164), "4.2  充电管理", F["h3"])
        text(draw, (main_x + 82, y + 204), "4.2.1  充电流程概述", F["bold"])
        text(draw, (main_x + 82, y + 232), "设备连接充电器后，充电管理模块会检测输入电源。", F["tiny"])
        text(draw, (main_x + 82, y + 272), "4.2.2  关键电气参数", F["bold"])
        rounded(draw, (main_x + 82, y + 310, main_x + 318, y + 386), 12, (239, 245, 255), BLUE, 2)
        text(draw, (main_x + 98, y + 326), "截止充电电压（V_CV）", F["bold"], BLUE)
        text(draw, (main_x + 98, y + 354), "默认值为 4.20V，精度 ±50mV。", F["tiny"], INK)
        right_panel(draw, right_x, y, ["引用详情", "高度相关", "产品说明书 v2.3", "第 45 页 · 4.2.2"], ["相关来源", "电池充电管理指南", "芯片寄存器手册", "返回回答"])

    elif kind == "settings":
        for i, (k, v) in enumerate([("访问 KEY", "KB-PROD-8F2A"), ("成员范围", "研发部、售后组、产品经理"), ("引用可见性", "回答必须展示来源"), ("自动更新", "每天 02:00 增量解析"), ("标签规则", "#锂电池 #通信协议 #风险项")]):
            yy = y + 84 + i * 64
            rounded(draw, (main_x + 10, yy, main_x + 372, yy + 48), 12, WHITE, LINE)
            text(draw, (main_x + 28, yy + 14), k, F["bold"])
            text(draw, (main_x + 138, yy + 15), v, F["small"], BLUE if i == 0 else MUTED)
        rounded(draw, (main_x + 240, y + 432, main_x + 372, y + 470), 12, BLUE, None, 0)
        text(draw, (main_x + 279, y + 443), "保存设置", F["small"], WHITE)
        right_panel(draw, right_x, y, ["安全状态", "私有向量索引", "操作日志 180 天", "敏感词检测开启"], ["最近更新", "文档解析完成 14:32", "权限变更 昨天", "索引完成"])


def right_panel(draw, x, y, a, b):
    rounded(draw, (x, y + 78, x + 142, y + 230), 14, WHITE, LINE)
    text(draw, (x + 14, y + 94), a[0], F["bold"])
    for i, item in enumerate(a[1:]):
        text(draw, (x + 14, y + 125 + i * 28), "✦ " + item, F["tiny"], BLUE if i == 0 else MUTED)
    rounded(draw, (x, y + 252, x + 142, y + 430), 14, WHITE, LINE)
    text(draw, (x + 14, y + 268), b[0], F["bold"])
    for i, item in enumerate(b[1:]):
        text(draw, (x + 14, y + 300 + i * 30), "• " + item, F["tiny"], MUTED)


def arrow(draw, x1, y1, x2, y2):
    draw.line((x1, y1, x2, y2), fill=BLUE, width=5)
    if x2 > x1:
        pts = [(x2, y2), (x2 - 18, y2 - 10), (x2 - 18, y2 + 10)]
    else:
        pts = [(x2, y2), (x2 + 10, y2 - 18), (x2 - 10, y2 - 18)]
    draw.polygon(pts, fill=BLUE)


def main():
    bg = gradient((W, H), (251, 253, 255), (236, 246, 255)).convert("RGBA")
    draw = ImageDraw.Draw(bg)
    draw.ellipse((-160, -120, 720, 520), fill=(230, 242, 255, 170))
    draw.ellipse((1520, -210, 2530, 520), fill=(236, 231, 255, 120))
    logo(draw, 70, 52, 62)
    text(draw, (150, 62), "知识库", F["brand"])
    text(draw, (1560, 54), "企业知识库 UX 交互子页面", F["h1"])
    text(draw, (1564, 112), "首页、知识空间、上传解析、AI 回答、引用预览、管理设置", F["body"], MUTED)

    positions = [(110, 210), (870, 210), (1630, 210), (110, 880), (870, 880), (1630, 880)]
    data = [
        ("知识空间首页", 1, "home"),
        ("点击“产品问答”", 2, "space"),
        ("上传文档子页面", 3, "upload"),
        ("AI 回答详情页", 4, "answer"),
        ("打开原文 / 上下文", 5, "preview"),
        ("管理 / 设置页", 6, "settings"),
    ]
    for pos, item in zip(positions, data):
        screen(bg, pos, *item)
    draw = ImageDraw.Draw(bg)
    arrow(draw, 830, 470, 865, 470)
    arrow(draw, 1590, 470, 1625, 470)
    arrow(draw, 1990, 742, 480, 875)
    arrow(draw, 830, 1140, 865, 1140)
    arrow(draw, 1590, 1140, 1625, 1140)
    bg.convert("RGB").save(OUT, quality=96)
    print(OUT)


if __name__ == "__main__":
    main()
