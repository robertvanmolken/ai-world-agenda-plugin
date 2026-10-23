"""Share image (Open Graph, 1200x630) for Slack and LinkedIn, with a QR code to the live site.

Usage:  python scripts/make_og_image.py [output_file]      (default: static/og-image.png)
Needs (dev only, not for the server):  pip install -r requirements-dev.txt
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
BURGUNDY, ACCENT, SOFT = "#481F2B", "#B8321F", "#F6D4CF"





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


def px_font(fn: Fonts, name: str, px: int, weight: int, fit: int | None = None, text: str = "") -> ImageFont.FreeTypeFont:
    """Font in pixels; with fit, shrink until `text` is at most fit pixels wide."""
    while True:
        f = ImageFont.truetype(str(fn.paths[name]), px)
        f.set_variation_by_axes([weight])
        if fit is None or f.getlength(text) <= fit or px <= 10:
            return f
        px -= 1


def og_image(fn: Fonts) -> Image.Image:
    """1200x630 share image (Slack, LinkedIn). Emblem, text and QR share one band (top T to bottom B),
    centred on the canvas, with equal 60 px side margins."""
    img = Image.new("RGB", (1200, 630), BURGUNDY)
    d = ImageDraw.Draw(img)
    T, B, M = 150, 480, 60
    emblem = Image.open(ROOT / "AI World Agenda Assistant Emblem.png").convert("RGB").resize((B - T, B - T), Image.LANCZOS)
    img.paste(emblem, (M, T))

    # text column: first glyph top at T, tag bottom at B
    tx, width = M + (B - T) + 40, 420

    def top_at(text: str, font: ImageFont.FreeTypeFont, y: float) -> float:
        return y - font.getbbox(text)[1]  # so the ink starts exactly at y

    f1 = px_font(fn, "source-serif-4", 44, 600, width, "Oracle AI World 2026")
    d.text((tx, top_at("Oracle AI World 2026", f1, T)), "Oracle AI World 2026", font=f1, fill="#FFFFFF")
    y = T + round(f1.size * 1.25)
    f2 = px_font(fn, "source-serif-4", 58, 600, width, "Agenda Assistant")
    d.text((tx, top_at("Agenda Assistant", f2, y)), "Agenda Assistant", font=f2, fill=SOFT)
    y += round(f2.size * 1.35)
    f3 = px_font(fn, "plus-jakarta-sans", 23, 400)
    for line in wrap(d, "Search sessions, check rooms, check if you can walk between sessions and plan your day. "
                        "Works with Claude and ChatGPT.", f3, width):
        d.text((tx, top_at(line, f3, y)), line, font=f3, fill="#E3D3D6")
        y += round(f3.size * 1.45)
    f4 = px_font(fn, "plus-jakarta-sans", 21, 700)
    label = "Unofficial community tool"
    tw = d.textlength(label, font=f4)
    d.rounded_rectangle([tx, B - 44, tx + tw + 36, B], radius=10, fill=ACCENT)
    d.text((tx + 18, B - 22), label, font=f4, fill="#FFFFFF", anchor="lm")

    # QR column: tile top at T, URL baseline at B, right edge at the same margin as the emblem
    code = segno.make(URL, error="q")
    scale = max(1, 214 // code.symbol_size(scale=1, border=4)[0])
    buf = io.BytesIO()
    code.save(buf, kind="png", scale=scale, border=4, dark=BURGUNDY, light="#FFFFFF")
    qr = Image.open(buf).convert("RGB")
    pad = 14
    tile_w, tile_h = qr.width + 2 * pad, qr.height + 2 * pad
    f6 = px_font(fn, "plus-jakarta-sans", 22, 700, tile_w, SHOW_URL)
    col_w = max(tile_w, round(f6.getlength(SHOW_URL)))
    cx = 1200 - M - col_w / 2
    tile_x = round(cx - tile_w / 2)
    d.rounded_rectangle([tile_x, T, tile_x + tile_w, T + tile_h], radius=16, fill="#FFFFFF")
    img.paste(qr, (tile_x + pad, T + pad))
    d.text((cx, B), SHOW_URL, font=f6, fill=SOFT, anchor="ms")
    url_top = B - f6.size * 0.72
    f5 = px_font(fn, "source-serif-4", 28, 600)
    d.text((cx, (T + tile_h + url_top) / 2), "Scan to try it", font=f5, fill="#FFFFFF", anchor="mm")
    return img


def main(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        og_image(Fonts(fonts(Path(t)))).save(out)
    print(f"Wrote {out} (1200x630)")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "static" / "og-image.png")
