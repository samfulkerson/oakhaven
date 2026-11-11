"""Make a generated image look like it came off the camp's cheap mid-2000s digital camera.

  python3 photos/camera.py IN.png OUT.jpg --day 5 [--time 14:32] [--flash]

Crops to Instagram's 4:5 (1080x1350), softens it a touch, adds CCD-style noise (heavier in the
shadows), a little flash falloff if --flash, two rounds of JPEG compression, and the orange
seven-segment date stamp in the lower right: "DAY 05  14:32". The stamp is drawn here, never by
the image model, so it is identical on every photo.
"""
import argparse, io, random
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import numpy as np

W, H = 1080, 1350

# seven segments: a top, b upper right, c lower right, d bottom, e lower left, f upper left, g middle
SEG = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc",
       "8": "abcdefg", "9": "abcdfg", "D": "bcdeg", "A": "abcefg", "Y": "bcdfg", "-": "g", " ": ""}


def seg_char(d, x, y, ch, s, col):
    """One character, s = segment length in px."""
    t = max(2, s // 4)                      # stroke thickness
    on = SEG.get(ch.upper(), "")
    boxes = {"a": (x + t, y, x + s, y + t), "g": (x + t, y + s, x + s, y + s + t), "d": (x + t, y + 2 * s, x + s, y + 2 * s + t),
             "f": (x, y + t, x + t, y + s), "b": (x + s, y + t, x + s + t, y + s),
             "e": (x, y + s + t, x + t, y + 2 * s), "c": (x + s, y + s + t, x + s + t, y + 2 * s)}
    for k in on:
        d.rectangle(boxes[k], fill=col)


def stamp(img, text, s=22):
    """Draw text in orange seven-segment digits with a soft glow, lower right."""
    t = max(2, s // 4)
    adv = s + t + int(s * .55)
    w = sum(int(s * .45) if c == ":" else adv for c in text)
    x0, y0 = img.width - w - 46, img.height - 2 * s - t - 44
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x = x0
    for c in text:
        if c == ":":
            d.rectangle((x, y0 + s // 2, x + t, y0 + s // 2 + t), fill=(255, 150, 40, 255))
            d.rectangle((x, y0 + s + s // 2, x + t, y0 + s + s // 2 + t), fill=(255, 150, 40, 255))
            x += int(s * .45)
            continue
        seg_char(d, x, y0, c, s, (255, 150, 40, 255))
        x += adv
    glow = layer.filter(ImageFilter.GaussianBlur(5))
    out = Image.alpha_composite(img.convert("RGBA"), glow)
    out = Image.alpha_composite(out, layer.filter(ImageFilter.GaussianBlur(.6)))
    return out.convert("RGB")


def fit(img):
    """Center-crop to 4:5 and resize to 1080x1350."""
    r = W / H
    if img.width / img.height > r:
        nw = int(img.height * r); img = img.crop(((img.width - nw) // 2, 0, (img.width - nw) // 2 + nw, img.height))
    else:
        nh = int(img.width / r); img = img.crop((0, (img.height - nh) // 2, img.width, (img.height - nh) // 2 + nh))
    return img.resize((W, H), Image.LANCZOS)


def develop(img, flash=False, seed=0):
    rng = np.random.default_rng(seed)
    img = fit(img.convert("RGB")).filter(ImageFilter.GaussianBlur(.7))
    a = np.asarray(img).astype(np.float32) / 255
    if flash:                                   # flash falls off toward the edges of the frame
        yy, xx = np.mgrid[0:H, 0:W]
        r = np.hypot((xx - W / 2) / (W * .75), (yy - H * .45) / (H * .75))
        a *= np.clip(1.08 - r * r * .9, .35, 1.08)[..., None]
    lum = a.mean(axis=2, keepdims=True)
    noise = rng.normal(0, 1, a.shape[:2] + (1,)) * .035 + rng.normal(0, 1, a.shape) * .02   # luminance + color noise
    a = a + noise * (1.4 - lum)                 # small sensors are noisiest in the shadows
    a = np.clip((a - .02) * 1.04, 0, 1)         # slightly crushed blacks, hot highlights
    img = Image.fromarray((a * 255).astype(np.uint8))
    # a hint of chromatic aberration: shift red out, blue in
    r_, g_, b_ = img.split()
    img = Image.merge("RGB", (ImageChops.offset(r_, 1, 0), g_, ImageChops.offset(b_, -1, 0)))
    for q in (78, 84):                          # saved by the camera, then again by whoever copied it off the card
        buf = io.BytesIO(); img.save(buf, "JPEG", quality=q); buf.seek(0); img = Image.open(buf).convert("RGB")
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--day", type=int, required=True)
    ap.add_argument("--time", default=None, help="HH:MM on the stamp; random daytime if omitted")
    ap.add_argument("--flash", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed or a.src)
    t = a.time or f"{rng.randint(9, 17):02d}:{rng.randint(0, 59):02d}"
    out = stamp(develop(Image.open(a.src), a.flash, a.seed), f"DAY {a.day:02d} {t}")
    out.save(a.dst, "JPEG", quality=90)


if __name__ == "__main__":
    main()
