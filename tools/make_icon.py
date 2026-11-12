"""Render the KeyTapper icon: a keycap whose legend is an endless loop, with tap ripples."""
import math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = 1024
out_dir = sys.argv[1]
os.makedirs(out_dir, exist_ok=True)


def lerp_stops(t, stops):
    t = np.clip(t, 0, 1)[..., None]
    res = np.zeros(t.shape[:-1] + (3,))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        m = ((t >= t0) & (t <= t1))[..., 0]
        k = (t - t0) / (t1 - t0)
        res[m] = (np.array(c0) * (1 - k) + np.array(c1) * k)[m]
    return res


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gradient(stops, angle_deg, size=S):
    y, x = np.mgrid[0:size, 0:size] / (size - 1)
    a = math.radians(angle_deg)
    t = (x - 0.5) * math.cos(a) + (y - 0.5) * math.sin(a) + 0.5
    arr = lerp_stops(t, [(p, hexc(c)) for p, c in stops])
    return Image.fromarray(arr.astype("uint8"), "RGB")


def rr_mask(box, r):
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle(box, r, fill=255)
    return m


canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))

# background squircle: violet -> blue -> cyan
bg = gradient([(0, "#8B5CF6"), (0.5, "#5B6CFF"), (1, "#22D3EE")], 40)
bg_mask = rr_mask((44, 44, S - 44, S - 44), 232)
canvas.paste(bg, (0, 0), bg_mask)
# soft top-left sheen
sheen = Image.new("L", (S, S), 0)
ImageDraw.Draw(sheen).ellipse((-300, -420, 800, 420), fill=70)
sheen = sheen.filter(ImageFilter.GaussianBlur(120))
canvas.paste(Image.new("RGB", (S, S), "white"), (0, 0), Image.composite(sheen, Image.new("L", (S, S), 0), bg_mask))

KX0, KX1, KY0, KY1, KR, LIP = 222, 802, 272, 716, 112, 78

# drop shadow under the key
sh = Image.new("L", (S, S), 0)
ImageDraw.Draw(sh).rounded_rectangle((KX0 + 10, KY0 + 70, KX1 - 10, KY1 + LIP + 46), KR, fill=150)
sh = sh.filter(ImageFilter.GaussianBlur(34))
canvas.paste(Image.new("RGB", (S, S), "#17104F"), (0, 0), Image.composite(sh, Image.new("L", (S, S), 0), bg_mask))

# key side (the lip that shows the key's height)
side = gradient([(0, "#C9CEFF"), (1, "#8E97F2")], 90)
canvas.paste(side, (0, 0), rr_mask((KX0, KY0 + LIP, KX1, KY1 + LIP), KR))
# key top face
face = gradient([(0.25, "#FFFFFF"), (0.75, "#EEF0FF")], 90)
canvas.paste(face, (0, 0), rr_mask((KX0, KY0, KX1, KY1), KR))

# legend: an endless loop (lemniscate), filled with the brand gradient
loop = Image.new("L", (S, S), 0)
d = ImageDraw.Draw(loop)
cx, cy, a, w = (KX0 + KX1) / 2, (KY0 + KY1) / 2, 196, 31
for i in range(1400):
    t = 2 * math.pi * i / 1400
    den = 1 + math.sin(t) ** 2
    x = cx + a * math.cos(t) / den
    y = cy + a * 1.18 * math.sin(t) * math.cos(t) / den
    d.ellipse((x - w, y - w, x + w, y + w), fill=255)
ink = gradient([(0.28, "#7C3AED"), (0.5, "#5B6CFF"), (0.72, "#06B6D4")], 0)
canvas.paste(ink, (0, 0), loop)

# tap ripples off the top-right corner
rip = Image.new("L", (S, S), 0)
d = ImageDraw.Draw(rip)
ox, oy = 742, 318
for radius, alpha, width in ((134, 245, 36), (200, 150, 32)):
    a0, a1 = math.radians(-74), math.radians(-16)
    for i in range(300):
        t = a0 + (a1 - a0) * i / 299
        x, y = ox + radius * math.cos(t), oy + radius * math.sin(t)
        d.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=alpha)
canvas.paste(Image.new("RGB", (S, S), "white"), (0, 0), rip)

big = canvas.resize((256, 256), Image.LANCZOS)
big.save(os.path.join(out_dir, "icon.png"))
canvas.resize((512, 512), Image.LANCZOS).save(os.path.join(out_dir, "icon_512.png"))
big.save(os.path.join(out_dir, "keytapper.ico"),
         sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
# preview sheet: large + small sizes on dark and light
sheet = Image.new("RGB", (900, 560), "#101218")
sheet.paste(Image.new("RGB", (450, 560), "#F2F3F7"), (450, 0))
for ox_ in (0, 450):
    im = canvas.resize((320, 320), Image.LANCZOS)
    sheet.paste(im, (ox_ + 65, 30), im)
    x = ox_ + 40
    for sz in (96, 64, 48, 32, 24, 16):
        im = canvas.resize((sz, sz), Image.LANCZOS)
        sheet.paste(im, (x, 400 + (96 - sz) // 2), im)
        x += sz + 22
sheet.save(os.path.join(out_dir, "preview.png"))
print("ok")
