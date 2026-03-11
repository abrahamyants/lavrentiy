"""Generate Lavrentiy branded .ico file — hi-fi stereo aesthetic."""
from PIL import Image, ImageDraw, ImageFont
import math, os

def draw_icon(size):
    """Draw the Lavrentiy icon at a given size."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2
    r = size * 0.46  # outer radius

    # ── Background: dark crimson circle with subtle gradient feel ──
    # Outer ring (brushed metal bezel)
    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=(60, 60, 62),  # dark gunmetal
        outline=(40, 40, 42)
    )

    # Inner bezel highlight
    r_inner = r * 0.88
    draw.ellipse(
        [cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
        fill=(45, 45, 48),
        outline=(55, 55, 58)
    )

    # Main face: deep crimson
    r_face = r * 0.80
    draw.ellipse(
        [cx - r_face, cy - r_face, cx + r_face, cy + r_face],
        fill=(120, 18, 18),
        outline=(90, 12, 12)
    )

    # Center knob / VU meter hub
    r_hub = r * 0.25
    draw.ellipse(
        [cx - r_hub, cy - r_hub, cx + r_hub, cy + r_hub],
        fill=(50, 50, 54),
        outline=(70, 70, 74)
    )
    # Hub highlight (specular dot)
    r_spec = r * 0.08
    spec_x, spec_y = cx - r_hub * 0.25, cy - r_hub * 0.25
    draw.ellipse(
        [spec_x - r_spec, spec_y - r_spec, spec_x + r_spec, spec_y + r_spec],
        fill=(110, 110, 115)
    )

    # ── Acid green LED indicator ──
    led_r = r * 0.09
    led_x = cx + r_face * 0.55
    led_y = cy - r_face * 0.55
    # Glow halo
    glow_r = led_r * 2.5
    for i in range(int(glow_r), 0, -1):
        alpha = int(60 * (1 - i / glow_r))
        glow_color = (138, 255, 0, alpha)
        glow_img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_img)
        glow_draw.ellipse(
            [led_x - i, led_y - i, led_x + i, led_y + i],
            fill=glow_color
        )
        img = Image.alpha_composite(img, glow_img)
        draw = ImageDraw.Draw(img)
    # LED body
    draw.ellipse(
        [led_x - led_r, led_y - led_r, led_x + led_r, led_y + led_r],
        fill=(138, 255, 0),
        outline=(100, 200, 0)
    )

    # ── Tick marks around the dial (like a volume knob) ──
    if size >= 48:
        num_ticks = 12
        tick_start = r_face * 0.85
        tick_end = r_face * 0.95
        for i in range(num_ticks):
            angle = (2 * math.pi * i / num_ticks) - math.pi / 2
            x1 = cx + tick_start * math.cos(angle)
            y1 = cy + tick_start * math.sin(angle)
            x2 = cx + tick_end * math.cos(angle)
            y2 = cy + tick_end * math.sin(angle)
            width = max(1, size // 64)
            draw.line([(x1, y1), (x2, y2)], fill=(180, 140, 140), width=width)

    # ── Pointer / needle (pointing ~10 o'clock for "idle") ──
    if size >= 32:
        needle_angle = math.radians(225)  # ~10 o'clock
        nx1 = cx + r_hub * 0.5 * math.cos(needle_angle)
        ny1 = cy + r_hub * 0.5 * math.sin(needle_angle)
        nx2 = cx + r_face * 0.7 * math.cos(needle_angle)
        ny2 = cy + r_face * 0.7 * math.sin(needle_angle)
        width = max(1, size // 48)
        draw.line([(nx1, ny1), (nx2, ny2)], fill=(220, 200, 200), width=width)

    return img


# Generate all standard Windows icon sizes
sizes = [16, 24, 32, 48, 64, 128, 256]
icons = [draw_icon(s) for s in sizes]

out_path = os.path.join(os.path.dirname(__file__), 'lavrentiy.ico')
icons[0].save(
    out_path,
    format='ICO',
    sizes=[(s, s) for s in sizes],
    append_images=icons[1:]
)
print(f"Icon saved to {out_path}")
print(f"Sizes: {', '.join(f'{s}x{s}' for s in sizes)}")
