"""The app icon, drawn in code so every size stays sharp."""
from PIL import Image, ImageDraw


def icon_image(size=64):
    """Speaker on a blue rounded square, drawn 4x larger and scaled down for smooth edges."""
    k = size * 4 / 64
    img = Image.new("RGBA", (size * 4, size * 4))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=14 * k, fill="#005fb8")
    d.polygon([(p[0] * k, p[1] * k) for p in [(12, 26), (22, 26), (34, 15), (34, 49), (22, 38), (12, 38)]],
              fill="white")
    for r in (8, 15):
        d.arc(((37 - r) * k, (32 - r) * k, (37 + r) * k, (32 + r) * k), -50, 50, fill="white",
              width=round(4 * k))
    return img.resize((size, size), Image.LANCZOS)
