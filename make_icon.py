"""Generate the app icon (a tach/gauge motif) as icon.ico. Run once; committed
output is icon.ico. Supersamples then downscales for smooth edges."""
import math
from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# rounded-square background (app dark)
d.rounded_rectangle([0, 0, S-1, S-1], radius=200, fill=(18, 20, 26, 255))

cx = cy = S // 2
R = 390                       # dial radius (nearly fills the tile)

# dial face
d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(230, 232, 236, 255), outline=(40, 44, 54), width=10)

# redline arc on the upper-right rim (PIL: 0deg=3 o'clock, clockwise, y-down)
rr = R - 34
d.arc([cx-rr, cy-rr, cx+rr, cy+rr], start=300, end=352, fill=(224, 87, 74), width=58)

# tick marks around the dial
for a in range(140, 401, 26):           # sweep across the bottom/around
    ang = math.radians(a)
    x1 = cx + (R-30) * math.cos(ang); y1 = cy + (R-30) * math.sin(ang)
    x2 = cx + (R-70) * math.cos(ang); y2 = cy + (R-70) * math.sin(ang)
    d.line([x1, y1, x2, y2], fill=(90, 96, 108), width=12)

# needle: from center up into the redline (~ -58deg)
na = math.radians(-58)
tipx = cx + (R-70) * math.cos(na); tipy = cy + (R-70) * math.sin(na)
perp = na + math.pi/2
bw = 34
bx1 = cx + bw*math.cos(perp); by1 = cy + bw*math.sin(perp)
bx2 = cx - bw*math.cos(perp); by2 = cy - bw*math.sin(perp)
d.polygon([(tipx, tipy), (bx1, by1), (bx2, by2)], fill=(224, 87, 74))

# hub
d.ellipse([cx-52, cy-52, cx+52, cy+52], fill=(40, 44, 54))

# downscale + multi-size .ico
base = img.resize((256, 256), Image.LANCZOS)
base.save("icon.ico", sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])
base.save("icon-preview.png")
print("wrote icon.ico + icon-preview.png")
