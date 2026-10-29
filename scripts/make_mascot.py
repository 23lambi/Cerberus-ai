"""Draw the pixel Cerberus mascot: python scripts/make_mascot.py

Writes into static/:
  mascot.svg           still, for the README and anywhere else
  mascot-idle.svg      wags its tail now and then (the empty chat)
  mascot-thinking.svg  the heads bob one after another (waiting for an answer)
  mascot-talking.svg   the heads nod together and the tail wags (answering)
  mascot-sad.svg       ears down, a tear, a slow sigh (something went wrong)
  mascot.png           512 px wide, for places that need a picture file
  mascot-small.png     one pixel per pixel, for the launcher to enlarge sharply

The animations live inside the SVG files, so the page only shows an image.
Each letter in the drawings below is one pixel; edit them and run this again.
"""
import struct
import zlib
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
WIDTH, HEIGHT = 36, 27
COLORS = {
    "P": "#dc143c",  # crimson fur
    "D": "#9e0f2c",  # shade
    "L": "#f0607a",  # light muzzle and belly
    "K": "#17181d",  # eyes, nose, mouth
    "W": "#ffffff",  # eye shine
    "T": "#ffb3c1",  # tongue
    "C": "#3a3d48",  # collar
    "G": "#f2c14e",  # collar tag
    "B": "#7fc4ff",  # tear
}

# Where each head sits (left, top); the middle one is higher, like the leader.
PLACES = {"head head-1": (1, 2), "head head-2": (13, 0), "head head-3": (25, 2)}

# Three heads, three moods: happy with tongue, the grinning leader, winking.
HAPPY = {
    "head head-1": [
        ".DD....DD.",
        ".DPD..DPD.",
        "PPPPPPPPPP",
        "PPPPPPPPPP",
        "PWKPPPPWKP",
        "PKKPPPPKKP",
        "PPLLKKLLPP",
        "PPLLLLLLPP",
        ".PLLTTLLP.",
        "..PPTTPP..",
    ],
    "head head-2": [
        ".DD....DD.",
        ".DPD..DPD.",
        "PPPPPPPPPP",
        "PPPPPPPPPP",
        "PWKPPPPWKP",
        "PKKPPPPKKP",
        "PPLLKKLLPP",
        "PPLLLLLLPP",
        ".PKLLLLKP.",
        "..PKKKKP..",
    ],
    "head head-3": [
        ".DD....DD.",
        ".DPD..DPD.",
        "PPPPPPPPPP",
        "PPPPPPPPPP",
        "PWKPPPPPPP",
        "PKKPPPKKKP",
        "PPLLKKLLPP",
        "PPLLLLLLPP",
        ".PLLLLLLP.",
        "..PLKKLP..",
    ],
}

# The same three when something went wrong: ears flop down, the eyes look
# down (the shine sits low), the mouths turn down, and the leader sheds a tear.
SAD_HEAD = [
    "..........",
    "D........D",
    "DPPPPPPPPD",
    "DPPPPPPPPD",
    "PKKPPPPKKP",
    "PKWPPPPKWP",
    "PPLLKKLLPP",
    "PPLLLLLLPP",
    ".PLLKKLLP.",
    "..PKLLKP..",
]
SAD = {name: SAD_HEAD for name in PLACES}
SAD["head head-2"] = SAD_HEAD[:6] + ["PBLLKKLLPP"] + SAD_HEAD[7:]

HAPPY_TAIL = ((30, 16), (31, 15), (32, 14), (32, 13), (33, 12)), (33, 11)
SAD_TAIL = ((30, 17), (31, 18), (31, 19), (32, 20)), (32, 21)


class Layer:
    """One movable part of the mascot, drawn on its own grid."""

    def __init__(self):
        self.pixels = {}

    def put(self, x, y, color):
        self.pixels[x, y] = color

    def rect(self, x1, y1, x2, y2, color):
        for y in range(y1, y2 + 1):
            for x in range(x1, x2 + 1):
                self.put(x, y, color)

    def stamp(self, left, top, rows):
        for dy, row in enumerate(rows):
            for dx, color in enumerate(row):
                if color != ".":
                    self.put(left + dx, top + dy, color)

    def svg(self):
        # Runs of the same color in a row become one rectangle: a smaller file.
        rects = []
        for y in range(HEIGHT):
            x = 0
            while x < WIDTH:
                color = self.pixels.get((x, y))
                start = x
                while x < WIDTH and self.pixels.get((x, y)) == color:
                    x += 1
                if color:
                    rects.append(f'<rect x="{start}" y="{y}" width="{x - start}" height="1" fill="{COLORS[color]}"/>')
        return "".join(rects)


def draw(heads=HAPPY, tail_pixels=HAPPY_TAIL):
    tail, body = Layer(), Layer()
    pixels, tip = tail_pixels
    for x, y in pixels:
        tail.put(x, y, "P")
    tail.put(*tip, "L")

    # A chunky body with a lighter belly and a shaded underside.
    body.rect(6, 15, 29, 21, "P")
    body.rect(7, 14, 28, 14, "P")
    body.rect(7, 22, 28, 22, "D")
    body.rect(13, 17, 22, 21, "L")
    # Front legs bright, back legs shaded for depth; light paws.
    for x, shade in ((7, "P"), (12, "D"), (21, "D"), (26, "P")):
        body.rect(x, 22, x + 2, 24, shade)
        body.rect(x, 25, x + 2, 25, "L")
    # Necks start one pixel under each head, so a bobbing head leaves no gap.
    body.rect(4, 11, 8, 15, "P")
    body.rect(15, 9, 20, 15, "P")
    body.rect(27, 11, 31, 15, "P")
    # Collars with little gold tags.
    body.rect(4, 13, 8, 13, "C")
    body.put(6, 14, "G")
    body.rect(15, 11, 20, 11, "C")
    body.put(17, 12, "G")
    body.put(18, 12, "G")
    body.rect(27, 13, 31, 13, "C")
    body.put(29, 14, "G")

    parts = [("tail", tail), ("body", body)]
    for name, (left, top) in PLACES.items():
        head = Layer()
        head.stamp(left, top, heads[name])
        parts.append((name, head))
    return parts


# steps(1) jumps from one pose to the next, like a pixel-art sprite.
IDLE = """
  .tail { animation: wag 4s steps(1, end) infinite; }
  @keyframes wag { 0%, 70%, 80%, 90%, 100% { transform: none; } 75%, 85% { transform: translate(1px, -1px); } }
"""
THINKING = """
  .head { animation: bob 1.2s steps(1, end) infinite; }
  .head-2 { animation-delay: 0.2s; }
  .head-3 { animation-delay: 0.4s; }
  .tail { animation: wag 1.2s steps(1, end) infinite; }
  @keyframes bob { 0% { transform: none; } 15% { transform: translateY(-1px); } 30% { transform: none; } }
  @keyframes wag { 0% { transform: none; } 50% { transform: translate(1px, -1px); } }
"""
TALKING = """
  .head { animation: nod 0.5s steps(1, end) infinite; }
  .head-2 { animation-delay: 0.1s; }
  .tail { animation: wag 0.3s steps(1, end) infinite; }
  @keyframes nod { 0% { transform: none; } 50% { transform: translateY(1px); } }
  @keyframes wag { 0% { transform: none; } 50% { transform: translate(1px, -1px); } }
"""
SIGH = """
  .head { animation: sigh 3s steps(1, end) infinite; }
  @keyframes sigh { 0%, 60% { transform: none; } 70%, 90% { transform: translateY(1px); } }
"""


def write_svg(name, animation, parts):
    style = ""
    if animation:
        style = ("<style>" + animation +
                 "  @media (prefers-reduced-motion: reduce) { * { animation: none !important; } }\n</style>\n")
    groups = "\n".join(f'<g class="{part}">{layer.svg()}</g>' for part, layer in parts)
    (STATIC / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" shape-rendering="crispEdges">\n'
        f"<title>Cerberus mascot</title>\n{style}{groups}\n</svg>\n")


def write_png(name, parts, scale):
    """A PNG straight from the pixels: every pixel becomes a sharp square."""
    pixels = {}
    for _part, layer in parts:
        pixels.update(layer.pixels)  # later parts (the heads) on top
    rows = []
    for y in range(HEIGHT):
        row = b""
        for x in range(WIDTH):
            color = pixels.get((x, y))
            row += (bytes.fromhex(COLORS[color][1:]) + b"\xff" if color else b"\0\0\0\0") * scale
        rows.append(b"\0" + row)  # filter type 0 for each row
    data = b"".join(row for row in rows for _ in range(scale))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    header = struct.pack(">IIBBBBB", WIDTH * scale, HEIGHT * scale, 8, 6, 0, 0, 0)  # 8-bit RGBA
    (STATIC / name).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
                                chunk(b"IDAT", zlib.compress(data, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    happy, sad = draw(), draw(SAD, SAD_TAIL)
    write_svg("mascot.svg", "", happy)
    write_svg("mascot-idle.svg", IDLE, happy)
    write_svg("mascot-thinking.svg", THINKING, happy)
    write_svg("mascot-talking.svg", TALKING, happy)
    write_svg("mascot-sad.svg", SIGH, sad)
    write_png("mascot.png", happy, 14)  # 504 x 378
    write_png("mascot-small.png", happy, 1)
