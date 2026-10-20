"""用 Playwright 录一组交互截图，合成 README 演示 GIF。"""

from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots" / "demo.gif"
URL = os.environ.get("RADAR_DEMO_URL", "http://127.0.0.1:8765")
FRAME_W = 1000
FRAME_MS = 900


def main() -> None:
    shots: list[Image.Image] = []

    with sync_playwright() as p:
        try:
            # 本机装了 Edge 时直接复用（国内环境通常比临时下载 Chromium 稳定）
            browser = p.chromium.launch(channel="msedge", args=["--hide-scrollbars"])
        except Exception:
            browser = p.chromium.launch(args=["--hide-scrollbars"])
        page = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=1)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(2200)
        shots.append(Image.open(__import__("io", fromlist=["BytesIO"]).BytesIO(page.screenshot())))
        page.wait_for_timeout(400)

        # 往下扫
        page.mouse.wheel(0, 420)
        page.wait_for_timeout(900)
        shots.append(Image.open(__import__("io", fromlist=["BytesIO"]).BytesIO(page.screenshot())))

        # 打开第一行详情
        try:
            page.click("#rows .row", timeout=5000)
            page.wait_for_timeout(1400)
            shots.append(Image.open(__import__("io", fromlist=["BytesIO"]).BytesIO(page.screenshot())))
            page.mouse.wheel(0, 520)
            page.wait_for_timeout(900)
            shots.append(Image.open(__import__("io", fromlist=["BytesIO"]).BytesIO(page.screenshot())))
            page.keyboard.press("Escape")
            page.wait_for_timeout(600)
        except Exception:
            pass

        # 组合筛选面板
        try:
            page.keyboard.press("f")
            page.wait_for_timeout(900)
            shots.append(Image.open(__import__("io", fromlist=["BytesIO"]).BytesIO(page.screenshot())))
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass

        # 日报
        try:
            page.click("a[href='/daily']", timeout=4000)
            page.wait_for_timeout(1700)
            shots.append(Image.open(__import__("io", fromlist=["BytesIO"]).BytesIO(page.screenshot())))
        except Exception:
            pass

        # 榜单
        try:
            page.click("a[href='/rank']", timeout=4000)
            page.wait_for_timeout(1500)
            shots.append(Image.open(__import__("io", fromlist=["BytesIO"]).BytesIO(page.screenshot())))
        except Exception:
            pass

        browser.close()

    if not shots:
        raise SystemExit("没有截到任何画面")

    frames = []
    for img in shots:
        ratio = FRAME_W / img.width
        resized = img.resize((FRAME_W, max(1, int(img.height * ratio))), Image.LANCZOS).convert("RGB")
        frames.append(resized.quantize(colors=128, method=Image.MEDIANCUT))
    max_h = max(f.height for f in frames)
    padded = []
    for f in frames:
        if f.height < max_h:
            base = Image.new("P", (FRAME_W, max_h), 0)
            base.paste(f, (0, 0))
            padded.append(base)
        else:
            padded.append(f)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    padded[0].save(
        OUT,
        save_all=True,
        append_images=padded[1:],
        duration=FRAME_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"已生成 {OUT}：{len(padded)} 帧，约 {len(padded) * FRAME_MS / 1000:.1f} 秒，{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
