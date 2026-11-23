"""Make a README poster from a video frame: the frame, a play button and a label.

Usage: python poster.py <frame.png> <out.png> <label>
"""

import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

frame, out, label = sys.argv[1], sys.argv[2], sys.argv[3]
image = Image.open(frame).convert("RGB").resize((1280, 720), Image.LANCZOS)
shade = Image.new("RGBA", image.size, (16, 18, 29, 70))
image = Image.alpha_composite(image.convert("RGBA"), shade)
draw = ImageDraw.Draw(image)

cx, cy, r = 640, 330, 74
glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse(
    (cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14), fill=(0, 0, 0, 120)
)
image = Image.alpha_composite(image, glow.filter(ImageFilter.GaussianBlur(14)))
draw = ImageDraw.Draw(image)
draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(243, 211, 107, 255))
draw.polygon([(cx - 24, cy - 38), (cx - 24, cy + 38), (cx + 42, cy)], fill=(16, 18, 29, 255))

try:
    font = ImageFont.truetype("DejaVuSans-Bold.ttf", 38)
except OSError:
    font = ImageFont.load_default()
box = draw.textbbox((0, 0), label, font=font)
w, h = box[2] - box[0], box[3] - box[1]
x, y = (1280 - w) // 2, cy + r + 34
draw.rounded_rectangle((x - 24, y - 14, x + w + 24, y + h + 22), radius=14, fill=(16, 18, 29, 230))
draw.text((x, y - box[1] + 4), label, font=font, fill=(243, 239, 230, 255))
image.convert("RGB").save(out, optimize=True)
print("poster", out)
