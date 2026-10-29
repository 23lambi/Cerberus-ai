"""Draw the pixel Cerberus mascot: python scripts/make_mascot.py

Writes three SVGs into static/:
  mascot.svg           still, for the README and anywhere else
  mascot-thinking.svg  the heads bob one after another (waiting for an answer)
  mascot-talking.svg   the heads nod together and the tail wags (answering)

The animations live inside the SVG files, so the page only shows an image.
Each letter in the drawings below is one pixel; edit them and run this again.
"""
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
}

# Three heads, three moods: happy with tongue, the grinning leader, winking.
HEADS = {
    "head head-1": (1, 2, [
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
    ]),
    "head head-2": (13, 0, [
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
    ]),
    "head head-3": (25, 2, [
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
    ]),
}


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


def draw():
    tail, body = Layer(), Layer()
    for x, y in ((30, 16), (31, 15), (32, 14), (32, 13), (33, 12)):
        tail.put(x, y, "P")
    tail.put(33, 11, "L")

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
    for name, (left, top, rows) in HEADS.items():
        head = Layer()
        head.stamp(left, top, rows)
        parts.append((name, head))
    return parts


# steps(1) jumps from one pose to the next, like a pixel-art sprite.
STILL = ""
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


def write(name, animation):
    style = ""
    if animation:
        style = ("<style>" + animation +
                 "  @media (prefers-reduced-motion: reduce) { * { animation: none !important; } }\n</style>\n")
    groups = "\n".join(f'<g class="{part}">{layer.svg()}</g>' for part, layer in draw())
    (STATIC / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" shape-rendering="crispEdges">\n'
        f"<title>Cerberus mascot</title>\n{style}{groups}\n</svg>\n")


if __name__ == "__main__":
    write("mascot.svg", STILL)
    write("mascot-thinking.svg", THINKING)
    write("mascot-talking.svg", TALKING)
