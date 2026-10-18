"""把网页截图包装成"桌面应用窗口"示意图（用于 README）。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SHOT = ROOT / "docs" / "screenshots" / "feed.png"
OUT = ROOT / "docs" / "screenshots" / "app.png"

PAD = 90
BAR = 46
SHADOW = 40


def main() -> None:
    shot = Image.open(SHOT).convert("RGB")
    w, h = shot.size
    win_w, win_h = w, h + BAR
    canvas_w, canvas_h = win_w + PAD * 2 + SHADOW, win_h + PAD * 2 + SHADOW

    # 桌面背景（深色径向渐变）
    bg = Image.new("RGB", (canvas_w, canvas_h), (10, 13, 20))
    glow = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-canvas_w // 3, -canvas_h // 3, canvas_w * 4 // 3, canvas_h * 4 // 3), fill=(50, 80, 160, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    bg = Image.alpha_composite(bg.convert("RGBA"), glow).convert("RGB")

    # 阴影
    shadow = Image.new("RGBA", (win_w + SHADOW * 2, win_h + SHADOW * 2), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (SHADOW, SHADOW, win_w + SHADOW, win_h + SHADOW), radius=18, fill=(0, 0, 0, 190)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    bg.paste(shadow, (PAD - SHADOW // 2, PAD - SHADOW // 2), shadow)

    # 窗口
    win = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
    wd = ImageDraw.Draw(win)
    wd.rounded_rectangle((0, 0, win_w, win_h), radius=14, fill=(16, 21, 32, 255))
    win.paste(shot, (0, BAR))

    wd.rounded_rectangle((0, 0, win_w, BAR), radius=14, fill=(24, 30, 44, 255))
    wd.rectangle((0, BAR - 14, win_w, BAR), fill=(24, 30, 44, 255))
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = 22 + i * 22
        wd.ellipse((cx - 6, BAR // 2 - 6, cx + 6, BAR // 2 + 6), fill=color)

    icon = Image.open(ROOT / "assets" / "icon.png").convert("RGBA").resize((26, 26), Image.LANCZOS)
    win.alpha_composite(icon, (110, (BAR - 26) // 2))
    from PIL import ImageFont

    font = None
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf", "segoeui.ttf"):
        try:
            font = ImageFont.truetype(candidate, 14)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    wd.text((148, BAR // 2 - 8), "GitHub 中文雷达 · StarScout", font=font, fill=(210, 220, 235, 255))

    bg = bg.convert("RGBA")
    bg.alpha_composite(win, (PAD, PAD))
    bg.convert("RGB").save(OUT, quality=92)
    print("已生成", OUT)


if __name__ == "__main__":
    main()
