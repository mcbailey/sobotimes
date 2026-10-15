"""Build the southborough.info logo as SVG, with all text converted to outlines.

Needs fontTools and the Oswald and Public Sans variable fonts from
github.com/google/fonts (set GF below to their ofl/ folder). The built files
live in static/brand/.

Outputs (in ./out):
  logo.svg            horizontal lockup, for light backgrounds
  logo-dark.svg       horizontal lockup, for dark backgrounds
  mark.svg            emblem only (square), for favicons and social avatars
  favicon.svg         simplified emblem for tiny sizes
"""
from __future__ import annotations

import os
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

HERE = os.path.dirname(os.path.abspath(__file__))
GF = os.path.join(HERE, "..", "gfonts", "ofl")
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

NAVY = "#1d3557"
BRICK = "#b3502c"
BRICK_DARK = "#933f22"
BRICK_LIGHT = "#c4613a"
CREAM = "#f6ead6"
PAPER = "#ffffff"


def load(path: str, wght: int) -> TTFont:
    f = TTFont(path)
    return instantiateVariableFont(f, {"wght": wght}, inplace=False)


OSWALD = load(os.path.join(GF, "oswald", "Oswald[wght].ttf"), 700)
PUBLIC = load(os.path.join(GF, "publicsans", "PublicSans[wght].ttf"), 600)


def text_path(font: TTFont, text: str, x: float, baseline: float, size: float, tracking: float = 0.0) -> tuple[str, float]:
    """SVG path data for `text` with its left edge at x; returns (d, width)."""
    upem = font["head"].unitsPerEm
    scale = size / upem
    cmap = font.getBestCmap()
    gs = font.getGlyphSet()
    hmtx = font["hmtx"]
    pen = SVGPathPen(gs)
    cx = x
    for i, ch in enumerate(text):
        g = cmap.get(ord(ch))
        if g is None:
            continue
        tp = TransformPen(pen, (scale, 0, 0, -scale, cx, baseline))
        gs[g].draw(tp)
        cx += hmtx[g][0] * scale
        if i < len(text) - 1:
            cx += tracking * size
    return pen.getCommands(), cx - x


def cap_height(font: TTFont, size: float) -> float:
    os2 = font["OS/2"]
    return os2.sCapHeight * size / font["head"].unitsPerEm


# ---------------------------------------------------------------------------
# Emblem: the Town House (brick, central bell tower) over an open book with a
# play button, inside a ring. Drawn on a 240 x 240 grid.
# ---------------------------------------------------------------------------

def windows(xs, y, w=9, h=15, fill=CREAM):
    out = []
    for x in xs:
        r = w / 2
        out.append(
            f'<path d="M{x} {y + h}V{y + r}a{r} {r} 0 0 1 {w} 0V{y + h}z" fill="{fill}"/>'
        )
    return "".join(out)


def emblem(ring=NAVY, inner=PAPER, detail=True) -> str:
    parts = []
    # Ring and inner disc
    parts.append(f'<circle cx="120" cy="124" r="104" fill="{inner}" stroke="{ring}" stroke-width="9"/>')

    # Main building: hip roof + brick block
    parts.append(f'<path d="M40 118 L66 96 H174 L200 118 Z" fill="{NAVY}"/>')
    parts.append(f'<rect x="46" y="116" width="148" height="66" fill="{BRICK}"/>')
    # Cornice line and base course
    parts.append(f'<rect x="44" y="114" width="152" height="5" fill="{NAVY}"/>')
    # Chimneys
    parts.append(f'<rect x="60" y="88" width="9" height="14" fill="{BRICK_DARK}"/>')
    parts.append(f'<rect x="171" y="88" width="9" height="14" fill="{BRICK_DARK}"/>')

    # Wing windows: two floors
    left = [56, 72, 88]
    right = [143, 159, 175]
    parts.append(windows(left + right, 126, 9, 17))
    parts.append(windows(left + right, 153, 9, 17))

    # Central tower (projecting, a shade lighter)
    parts.append(f'<rect x="100" y="70" width="40" height="112" fill="{BRICK_LIGHT}"/>')
    # Tower cornice + belfry band
    parts.append(f'<rect x="96" y="66" width="48" height="6" fill="{NAVY}"/>')
    parts.append(f'<rect x="104" y="40" width="32" height="27" fill="{BRICK_LIGHT}"/>')
    parts.append(f'<rect x="101" y="37" width="38" height="5" fill="{NAVY}"/>')
    # Belfry opening with bell
    parts.append(f'<path d="M111 66V52a9 9 0 0 1 18 0V66z" fill="{NAVY}"/>')
    if detail:
        parts.append(
            f'<path d="M120 50.5c-3.6 0-5.4 3-5.4 6.6v3.4h-1.6v2.4h14v-2.4h-1.6v-3.4c0-3.6-1.8-6.6-5.4-6.6z" fill="{CREAM}"/>'
            f'<circle cx="120" cy="64.3" r="1.5" fill="{CREAM}"/>'
        )
    # Spire and finial
    parts.append(f'<path d="M99 38 L120 8 L141 38 Z" fill="{NAVY}"/>')
    parts.append(f'<rect x="119" y="1" width="2" height="9" fill="{NAVY}"/>')
    # Tower window and arched door
    parts.append(windows([115.5], 80, 9, 18))
    parts.append(f'<path d="M110 182V161a10 10 0 0 1 20 0V182z" fill="{NAVY}"/>')
    if detail:
        parts.append(f'<path d="M113 182V162a7 7 0 0 1 14 0V182z" fill="{BRICK_DARK}"/>')

    # Open book, overlapping the base of the building and the ring
    parts.append(
        f'<path d="M120 194 C104 184 82 182 62 186 V226 C82 222 104 224 120 234 '
        f'C136 224 158 222 178 226 V186 C158 182 136 184 120 194 Z" '
        f'fill="{PAPER}" stroke="{NAVY}" stroke-width="5" stroke-linejoin="round"/>'
    )
    parts.append(f'<path d="M120 194 V234" stroke="{NAVY}" stroke-width="4"/>')
    # Play button on the left page
    parts.append(f'<rect x="78" y="197" width="27" height="20" rx="5" fill="{BRICK}"/>')
    parts.append(f'<path d="M88 201.5 L97 207 L88 212.5 Z" fill="{PAPER}"/>')
    # "Text" lines on the right page
    if detail:
        for i, (y, w) in enumerate([(200, 34), (207.5, 30), (215, 34)]):
            parts.append(f'<rect x="{132}" y="{y}" width="{w}" height="3" rx="1.5" fill="{NAVY}" opacity="0.75"/>')
    return "".join(parts)


def favicon() -> str:
    """Tiny-size version: the bell tower alone on a navy disc."""
    return (
        f'<circle cx="32" cy="32" r="32" fill="{NAVY}"/>'
        f'<path d="M24 22 L32 7 L40 22 Z" fill="{PAPER}"/>'
        f'<rect x="25" y="21" width="14" height="36" fill="{BRICK_LIGHT}"/>'
        f'<rect x="23" y="20" width="18" height="3" fill="{PAPER}"/>'
        f'<path d="M29 33V28a3 3 0 0 1 6 0V33z" fill="{NAVY}"/>'
        f'<path d="M29 57V48a3 3 0 0 1 6 0V57z" fill="{NAVY}"/>'
        f'<rect x="12" y="38" width="13" height="19" fill="{BRICK}"/>'
        f'<rect x="39" y="38" width="13" height="19" fill="{BRICK}"/>'
        f'<path d="M10 39 L15 33 H25 V39 Z M54 39 L49 33 H39 V39 Z" fill="{PAPER}"/>'
    )


def svg(width, height, body, title, view=None) -> str:
    vb = view or f"0 0 {width} {height}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{width}" height="{height}" '
        f'role="img" aria-labelledby="t"><title id="t">{title}</title>{body}</svg>\n'
    )


def lockup(dark: bool) -> str:
    word = "#ffffff" if dark else NAVY
    accent = "#e0784f" if dark else BRICK
    tag = "#d9e2ec" if dark else NAVY
    ring = "#ffffff" if dark else NAVY

    # Emblem at left, 240 grid scaled to 200 high
    s = 200 / 240
    mark = f'<g transform="translate(10 6) scale({s:.5f})">{emblem(ring=ring, inner=PAPER)}</g>'

    x0 = 245
    size1 = 96
    base1 = 118
    d1, w1 = text_path(OSWALD, "SOUTHBOROUGH", x0, base1, size1, tracking=0.01)
    d2, w2 = text_path(OSWALD, ".INFO", x0 + w1 + size1 * 0.01, base1, size1, tracking=0.01)
    word_w = w1 + w2 + size1 * 0.01
    # Tagline sized to roughly match the wordmark width
    probe_d, probe_w = text_path(PUBLIC, "Town Meetings & Summaries", 0, 0, 40)
    size2 = 40 * word_w / probe_w
    d3, w3 = text_path(PUBLIC, "Town Meetings & Summaries", x0 + 2, base1 + 22 + cap_height(PUBLIC, size2), size2)

    # Small "spark" strokes off the top-right of INFO
    sx = x0 + word_w + 8
    sy = base1 - cap_height(OSWALD, size1) - 4
    spark = (
        f'<g stroke="{accent}" stroke-width="5" stroke-linecap="round" opacity="0.85">'
        f'<path d="M{sx} {sy + 10} l12 -6"/><path d="M{sx - 6} {sy - 4} l4 -12"/><path d="M{sx + 6} {sy + 26} l13 1"/></g>'
    )
    width = int(sx + 30)
    body = (
        mark
        + f'<path d="{d1}" fill="{word}"/>'
        + f'<path d="{d2}" fill="{accent}"/>'
        + f'<path d="{d3}" fill="{tag}"/>'
        + spark
    )
    return svg(width, 212, body, "southborough.info: Town Meetings &amp; Summaries")


def main():
    files = {
        "logo.svg": lockup(dark=False),
        "logo-dark.svg": lockup(dark=True),
        "mark.svg": svg(240, 240, emblem(), "southborough.info", view="0 -2 240 242"),
        "favicon.svg": svg(64, 64, favicon(), "southborough.info"),
    }
    for name, content in files.items():
        with open(os.path.join(OUT, name), "w") as fh:
            fh.write(content)
        print(name, len(content), "bytes")


if __name__ == "__main__":
    main()
