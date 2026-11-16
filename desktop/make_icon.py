"""Generate the placeholder Yoraito icon: desktop/assets/icon.ico and desktop/assets/icon.png.

The template ships these two files. Replace desktop/assets/icon.ico with the tool's own logo when there is one;
nothing else needs to change. Usage:  python desktop/make_icon.py        (needs Pillow)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "assets"
BLUE = (67, 97, 238, 255)
SIZE = 1024


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=SIZE // 5, fill=BLUE)
    font = None
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, int(SIZE * 0.62))
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    d.text((SIZE / 2, SIZE / 2), "Y", font=font, fill=(255, 255, 255, 255), anchor="mm")
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    big = draw_icon()
    big.resize((512, 512), Image.LANCZOS).save(OUT / "icon.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT / "icon.ico")
