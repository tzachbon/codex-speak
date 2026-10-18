"""The app icon, drawn in code so every size stays sharp."""
from PIL import Image, ImageDraw

BACK = "#3b4bd8"


def icon_image(size=64):
    """Two speech bubbles on an indigo rounded square, the front one with sound bars.
    Drawn 4x larger on a 64-unit grid and scaled down for smooth edges."""
    k = size * 4 / 64
    img = Image.new("RGBA", (size * 4, size * 4))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return x0 * k, y0 * k, x1 * k, y1 * k

    def poly(points):
        return [(x * k, y * k) for x, y in points]

    d.rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=14 * k, fill=BACK)
    # back bubble, tail to the lower right
    d.rounded_rectangle(box(27, 12, 56, 34), radius=8 * k, fill="#a9b4ff")
    d.polygon(poly([(44, 34), (53, 30), (55, 41)]), fill="#a9b4ff")
    # front bubble, tail to the lower left, with a gap cut around it so the two read apart
    d.rounded_rectangle(box(5, 21, 45, 51), radius=10 * k, fill=BACK)
    d.rounded_rectangle(box(8, 24, 42, 48), radius=8 * k, fill="white")
    d.polygon(poly([(12, 45), (22, 46), (10, 56)]), fill="white")
    for x, half in ((16, 4), (23, 8), (30, 4)):  # sound bars, centred on y = 36
        d.rounded_rectangle(box(x, 36 - half, x + 4, 36 + half), radius=2 * k, fill=BACK)
    return img.resize((size, size), Image.LANCZOS)
