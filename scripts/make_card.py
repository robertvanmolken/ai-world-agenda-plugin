"""Business card for the AI World Agenda Assistant: front, back and a print PDF with bleed.

Usage:  python scripts/make_card.py [output_dir]      (default: dist/card)
Needs (dev only, not for the server):  pip install segno fonttools brotli pillow
Size: 85 x 55 mm at 300 dpi plus 3 mm bleed on every side. Keep text inside the 4 mm safe margin.
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import segno
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
URL = "https://aiworld.exoblock.it/"
SHOW_URL = "aiworld.exoblock.it"
DPI = 300
BURGUNDY, DARK, ACCENT, SOFT, WARM, MUTED = "#481F2B", "#37151F", "#B8321F", "#F6D4CF", "#F8F4F0", "#76686B"


def mm(v: float) -> int:
    return round(v * DPI / 25.4)


TRIM_W, TRIM_H, BLEED, SAFE = mm(85), mm(55), mm(3), mm(4)
W, H = TRIM_W + 2 * BLEED, TRIM_H + 2 * BLEED
X0, Y0 = BLEED + SAFE, BLEED + SAFE  # top-left of the safe area
X1, Y1 = W - BLEED - SAFE, H - BLEED - SAFE


def fonts(tmp: Path) -> dict[str, Path]:
    """Pillow cannot read woff2, so convert the site's own fonts once."""
    out = {}
    for name in ("source-serif-4", "plus-jakarta-sans"):
        f = TTFont(ROOT / "static" / "fonts" / f"{name}.woff2")
        f.flavor = None
        out[name] = tmp / f"{name}.ttf"
        f.save(out[name])
    return out


class Fonts:
    def __init__(self, paths: dict[str, Path]):
        self.paths = paths

    def get(self, name: str, pt: float, weight: int) -> ImageFont.FreeTypeFont:
        f = ImageFont.truetype(str(self.paths[name]), round(pt * DPI / 72))
        f.set_variation_by_axes([weight])
        return f


def wrap(d: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if d.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur]


def qr_image(size_mm: float) -> Image.Image:
    """Burgundy on white, error correction Q, 4 module quiet zone, scaled to whole pixels per module."""
    code = segno.make(URL, error="q", micro=False)
    modules = code.symbol_size(scale=1, border=4)[0]
    scale = max(1, mm(size_mm) // modules)
    buf = io.BytesIO()
    code.save(buf, kind="png", scale=scale, border=4, dark=BURGUNDY, light="#FFFFFF")
    return Image.open(buf).convert("RGB")


def front(fn: Fonts) -> Image.Image:
    img = Image.new("RGB", (W, H), BURGUNDY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - BLEED - mm(3), W, H], fill=DARK)  # footer band runs into the bleed
    emblem = Image.open(ROOT / "AI World Agenda Assistant Emblem.png").convert("RGB")
    tile = mm(18)
    emblem = emblem.resize((tile, tile), Image.LANCZOS)
    d.rounded_rectangle([X0, Y0, X0 + tile, Y0 + tile], radius=mm(2.5), fill="#FFFFFF")
    img.paste(emblem, (X0, Y0))
    tag = fn.get("plus-jakarta-sans", 6.5, 700)
    d.text((X0 + tile + mm(4), Y0 + tile // 2), "UNOFFICIAL COMMUNITY TOOL", font=tag, fill=SOFT, anchor="lm")
    title = fn.get("source-serif-4", 19, 600)
    y = Y0 + tile + mm(5)
    for line in ("AI World", "Agenda Assistant"):
        d.text((X0, y), line, font=title, fill="#FFFFFF")
        y += round(title.size * 1.1)
    body = fn.get("plus-jakarta-sans", 8, 400)
    for line in wrap(d, "Plan your Oracle AI World days from Claude or ChatGPT.", body, X1 - X0):
        d.text((X0, y + mm(1.5)), line, font=body, fill="#E3D3D6")
        y += round(body.size * 1.35)
    return img


def back(fn: Fonts) -> Image.Image:
    img = Image.new("RGB", (W, H), WARM)
    d = ImageDraw.Draw(img)
    qr = qr_image(31)
    qy = (H - qr.height) // 2
    d.rounded_rectangle([X0 - mm(1), qy - mm(1), X0 + qr.width + mm(1), qy + qr.height + mm(1)], radius=mm(2),
                        fill="#FFFFFF", outline="#E5D9D0", width=3)
    img.paste(qr, (X0, qy))
    tx = X0 + qr.width + mm(6)
    head = fn.get("source-serif-4", 13, 600)
    d.text((tx, Y0), "Scan to try it", font=head, fill=BURGUNDY)
    y = Y0 + round(head.size * 1.5)
    small = fn.get("plus-jakarta-sans", 8, 500)
    for item in ("Find sessions", "Can I make it?", "Walking routes"):
        d.ellipse([tx, y + mm(1.1), tx + mm(1.8), y + mm(2.9)], fill=ACCENT)
        d.text((tx + mm(4), y), item, font=small, fill="#2B1A20")
        y += round(small.size * 1.5)
    url = fn.get("plus-jakarta-sans", 9, 700)
    d.text((tx, y + mm(3)), SHOW_URL, font=url, fill=ACCENT)
    logo = Image.open(ROOT / "static" / "exoblock_logo.png").convert("RGBA")
    lw = mm(22)
    logo = logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS)
    img.paste(logo, (tx, Y1 - mm(8) - logo.height), logo)
    fine = fn.get("plus-jakarta-sans", 5.5, 400)
    d.text((tx, Y1 - fine.size - mm(1)), "Unofficial, not affiliated with Oracle.", font=fine, fill=MUTED)
    return img


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        fn = Fonts(fonts(Path(t)))
        f, b = front(fn), back(fn)
    f.save(out / "card-front.png", dpi=(DPI, DPI))
    b.save(out / "card-back.png", dpi=(DPI, DPI))
    f.save(out / "card-print.pdf", save_all=True, append_images=[b], resolution=DPI)
    code = segno.make(URL, error="q")
    code.save(str(out / "qr-aiworld.svg"), scale=10, border=4, dark=BURGUNDY, light="#FFFFFF")
    code.save(str(out / "qr-aiworld.png"), scale=40, border=4, dark=BURGUNDY, light="#FFFFFF")
    print(f"Wrote card files to {out} ({W}x{H}px with 3 mm bleed, trim {TRIM_W}x{TRIM_H}px)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "card")
