"""生成应用图标（assets/icon.png + icon.ico），纯 Pillow 绘制雷达图形。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"


def draw_icon(size: int = 1024) -> Image.Image:
    layers = []
    # 深色背景 + 渐变光晕
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bg)
    radius = int(size * 0.22)
    bd.rounded_rectangle((0, 0, size, size), radius=radius, fill=(11, 15, 26, 255))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse(
        (size * 0.05, size * 0.05, size * 0.95, size * 0.95),
        fill=(70, 110, 255, 60),
    )
    glow = glow.filter(__import__("PIL.ImageFilter", fromlist=["ImageFilter"]).GaussianBlur(size // 12))
    bg = Image.alpha_composite(bg, glow)

    d = ImageDraw.Draw(bg)
    cx = cy = size / 2
    # 雷达同心圆
    for frac, alpha in ((0.40, 110), (0.30, 90), (0.20, 70)):
        r = size * frac
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(150, 190, 255, alpha), width=max(2, size // 160))
    # 扫描扇形（用半透明三角近似）
    sector = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sector)
    sd.pieslice((0, 0, size, size), start=-35, end=0, fill=(120, 210, 255, 90))
    bg = Image.alpha_composite(bg, sector)
    d = ImageDraw.Draw(bg)
    # 中心点与高亮点
    r = size * 0.035
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(235, 245, 255, 255))
    for (dx, dy, rr, col) in (
        (-0.17, -0.12, 0.030, (140, 220, 255, 255)),
        (0.21, 0.06, 0.022, (255, 205, 140, 255)),
        (0.02, 0.24, 0.018, (150, 255, 200, 255)),
    ):
        ccx, ccy, cr = cx + size * dx, cy + size * dy, size * rr
        d.ellipse((ccx - cr, ccy - cr, ccx + cr, ccy + cr), fill=col)

    # 圆角裁切
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    bg.putalpha(mask)
    return bg


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = draw_icon(1024)
    icon.save(OUT / "icon.png")
    icon.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("已生成", OUT / "icon.png", OUT / "icon.ico")


if __name__ == "__main__":
    main()
