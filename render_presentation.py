#!/usr/bin/env python3
"""Draw the network as high resolution PNGs for a presentation.

Reads the layout written by site/layout-presentation.mjs (in $TMPDIR/sib-presentation/),
so every image uses the same node positions. Each image hides one more layer than the
one before it: papers, courses, people, groups, institutions.

Usage: venv/bin/python render_presentation.py
"""
import json
import os
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
LAYOUT = os.path.join(os.environ.get("TMPDIR", tempfile.gettempdir()), "sib-presentation", "layout.json")
OUT = os.path.join(HERE, "presentation")
FONT = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"

SCALE = 1.5  # layout units to pixels; 4000 units wide gives 6000 px
RADIUS = {"sib": 60, "institution": 44, "group": 34, "person": 22, "course": 12, "paper": 10}
FILL = {
    "sib": (11, 114, 133),
    "institution": (90, 125, 26),
    "group": (130, 80, 223),
    "person": (9, 105, 218),
    "course": (149, 56, 0),
    "paper": (140, 149, 159),
}
NAME = {
    "sib": "SIB",
    "institution": "Institutions",
    "group": "Groups",
    "person": "People",
    "course": "Courses",
    "paper": "Papers",
}
INK = (31, 35, 40)
WHITE = (255, 255, 255)
LABELLED = {"sib", "institution", "group"}
LABEL_SIZE = {"sib": 56, "institution": 30, "group": 30}
# Each step hides the layers listed, on top of the previous steps.
STEPS = [
    ("01-full-network", "All layers", []),
    ("02-without-papers", "Without papers", ["paper"]),
    ("03-without-papers-and-courses", "Without papers and courses", ["paper", "course"]),
    ("04-without-people", "Without people", ["paper", "course", "person"]),
    ("05-without-groups", "Without groups", ["paper", "course", "person", "group"]),
    ("06-without-institutions", "Without institutions", ["paper", "course", "person", "group", "institution"]),
]
# Drawn in this order, so big nodes sit on top of small ones.
DRAW_ORDER = ["paper", "course", "group", "institution", "person", "sib"]


def px(value):
    return int(round(value * SCALE))


def load_font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        sys.exit(f"font not found: {path}")


def circle_photo(path, diameter, cache):
    """A square photo, centre-cropped and cut to a circle."""
    key = (path, diameter)
    if key not in cache:
        img = Image.open(path).convert("RGB")
        side = min(img.size)
        left, top = (img.width - side) // 2, (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side)).resize((diameter, diameter), Image.LANCZOS)
        mask = Image.new("L", (diameter, diameter), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, diameter - 1, diameter - 1), fill=255)
        cutout = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
        cutout.paste(img, (0, 0), mask)
        cache[key] = cutout
    return cache[key]


def fit_logo(path, box, cache):
    """A logo scaled to fit inside a square box, keeping its proportions."""
    key = (path, box)
    if key not in cache:
        img = Image.open(path).convert("RGBA")
        img.thumbnail((box, box), Image.LANCZOS)
        cache[key] = img
    return cache[key]


def draw_legend(draw, counts, caption, fonts):
    # The title sits on its own line, and the legend row below it.
    draw.text((px(120), px(200)), caption, font=fonts["title"], fill=INK, anchor="ls")
    # Items are spaced by their measured text width, so long labels never overlap the next item.
    x = px(120)
    gap = px(120)
    r = px(34)
    cy = px(400)
    for kind in ["sib", "institution", "group", "person", "course", "paper"]:
        if not counts.get(kind):
            continue
        text = f"{NAME[kind]} ({counts[kind]})"
        draw.ellipse((x - r, cy - r, x + r, cy + r), fill=FILL[kind])
        draw.text((x + px(56), cy), text, font=fonts["legend"], fill=INK, anchor="lm")
        x += px(56) + fonts["legend"].getlength(text) + gap


def draw_node(draw, canvas, node, fonts, caches):
    kind = node["type"]
    r = px(RADIUS[kind])
    cx, cy = px(node["x"]), px(node["y"])
    box = (cx - r, cy - r, cx + r, cy + r)

    if kind == "group":
        draw.rounded_rectangle(box, radius=px(8), fill=FILL["group"], outline=WHITE, width=px(3))
    else:
        fill = WHITE if kind == "institution" else FILL[kind]
        draw.ellipse(box, fill=fill, outline=WHITE, width=px(3))

    image = node.get("image")
    if image and os.path.exists(image):
        if kind == "institution":
            logo = fit_logo(image, int(2 * r * 0.86), caches["logo"])
            canvas.alpha_composite(logo, (cx - logo.width // 2, cy - logo.height // 2))
        else:
            photo = circle_photo(image, 2 * r, caches["photo"])
            canvas.alpha_composite(photo, (cx - r, cy - r))
    elif kind == "person":
        parts = node["label"].split()
        initials = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper() if parts else ""
        draw.text((cx, cy), initials, font=fonts["initials"], fill=WHITE, anchor="mm")



def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def draw_labels(canvas, nodes, fonts):
    """Write the labels of big nodes. A label that would overlap one already placed is left out.

    Labels are placed in priority order, so the SIB, then institutions, then groups.
    """
    draw = ImageDraw.Draw(canvas)
    priority = {"sib": 0, "institution": 1, "group": 2}
    placed = []
    pad = px(6)
    for n in sorted((n for n in nodes if n["type"] in priority), key=lambda n: priority[n["type"]]):
        kind = n["type"]
        label = "SIB" if kind == "sib" else n["label"]
        font = fonts["label"][kind]
        x = px(n["x"])
        y = px(n["y"]) + px(RADIUS[kind]) + px(6)
        stroke = px(4)
        bbox = draw.textbbox((x, y), label, font=font, anchor="mt", stroke_width=stroke)
        box = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
        if any(overlaps(box, other) for other in placed):
            continue
        placed.append(box)
        draw.text((x, y), label, font=font, fill=INK, anchor="mt", stroke_width=stroke, stroke_fill=WHITE)


def render(layout, hidden, caption, fonts, caches):
    width, height, band = layout["width"], layout["height"], layout["band"]
    canvas = Image.new("RGBA", (px(width), px(height + band)), WHITE + (255,))
    draw = ImageDraw.Draw(canvas)

    nodes = [n for n in layout["nodes"] if n["type"] not in hidden]
    visible = {n["id"] for n in nodes}
    # Node positions are in the network area, which starts below the legend band.
    for n in nodes:
        n["y"] = n["y"] + band
    positions = {n["id"]: (n["x"], n["y"]) for n in nodes}

    links = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    link_draw = ImageDraw.Draw(links)
    for link in layout["links"]:
        if link["source"] in visible and link["target"] in visible:
            x1, y1 = positions[link["source"]]
            x2, y2 = positions[link["target"]]
            link_draw.line((px(x1), px(y1), px(x2), px(y2)), fill=(140, 149, 159, 90), width=px(3))
    canvas.alpha_composite(links)
    draw = ImageDraw.Draw(canvas)

    for kind in DRAW_ORDER:
        for n in nodes:
            if n["type"] == kind:
                draw_node(draw, canvas, n, fonts, caches)
                draw = ImageDraw.Draw(canvas)

    draw_labels(canvas, nodes, fonts)

    counts = {}
    for n in nodes:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    draw_legend(ImageDraw.Draw(canvas), counts, caption, fonts)
    return canvas.convert("RGB")


def main():
    with open(LAYOUT, encoding="utf-8") as f:
        layout = json.load(f)
    # Positions are shifted by the band once, so keep an unshifted copy for every step.
    base = {
        "width": layout["width"],
        "height": layout["height"],
        "band": layout["band"],
        "links": layout["links"],
        "nodes": [dict(n) for n in layout["nodes"]],
    }
    fonts = {
        "title": load_font(FONT_BOLD, px(110)),
        "legend": load_font(FONT, px(72)),
        "initials": load_font(FONT_BOLD, px(30)),
        "label": {kind: load_font(FONT, px(size)) for kind, size in LABEL_SIZE.items()},
    }
    caches = {"photo": {}, "logo": {}}
    os.makedirs(OUT, exist_ok=True)

    for name, caption, hidden in STEPS:
        layout_copy = {**base, "nodes": [dict(n) for n in base["nodes"]]}
        image = render(layout_copy, hidden, caption, fonts, caches)
        out = os.path.join(OUT, f"{name}.png")
        image.save(out, optimize=True)
        print(f"wrote {out} ({image.width}x{image.height})", file=sys.stderr)


if __name__ == "__main__":
    main()
