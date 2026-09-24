"""Generate the application icon (no third-party artwork)."""
from pathlib import Path

from PIL import Image, ImageDraw

size = 256
image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill=(57, 116, 237))
draw.rounded_rectangle((68, 44, 188, 212), radius=12, fill=(255, 255, 255))
for y in (84, 118, 152):
    draw.rectangle((88, y, 168, y + 16), fill=(20, 30, 50))
draw.rectangle((88, 182, 140, 190), fill=(67, 214, 174))
image.save(Path(__file__).with_name("anonimato.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
