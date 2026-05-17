from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "ui_mockups"
RESOURCE_DIR = ROOT / "resources"
LOGO_PATH = RESOURCE_DIR / "biobot_logo.png"
SELECTOR_IMAGE_PATH = RESOURCE_DIR / "Screenshot 2026-04-01 132426.png"

WIDTH = 1600
HEIGHT = 960


@dataclass(frozen=True)
class Palette:
    background_top: str = "#FFFDFC"
    background_bottom: str = "#FFF2E8"
    shell: str = "#FFFFFF"
    shell_soft: str = "#FFF8F1"
    card: str = "#FFFFFF"
    card_alt: str = "#FFF6EE"
    border: str = "#F1DFD0"
    border_soft: str = "#F6E8DD"
    text: str = "#473025"
    text_muted: str = "#8C6D58"
    accent: str = "#F28A34"
    accent_soft: str = "#FFF0E2"
    accent_deep: str = "#D96C1E"
    success: str = "#3DB37C"
    warning: str = "#EEA33A"
    danger: str = "#D85858"
    info: str = "#5B8DEE"
    nav_bg: str = "#FFF8F2"
    nav_active: str = "#FFE5CE"
    graph_bg: str = "#FFF8F2"


PALETTE = Palette()


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = []
    if bold:
        font_candidates.extend(
            [
                "C:/Windows/Fonts/segoeuib.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
            ]
        )
    else:
        font_candidates.extend(
            [
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/arial.ttf",
            ]
        )

    for candidate in font_candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


FONT_12 = load_font(12)
FONT_13 = load_font(13)
FONT_14 = load_font(14)
FONT_15 = load_font(15)
FONT_16 = load_font(16)
FONT_18 = load_font(18, bold=True)
FONT_20 = load_font(20, bold=True)
FONT_24 = load_font(24, bold=True)
FONT_28 = load_font(28, bold=True)
FONT_32 = load_font(32, bold=True)


def make_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (WIDTH, HEIGHT), PALETTE.background_top)
    draw = ImageDraw.Draw(image)
    draw_vertical_gradient(image, PALETTE.background_top, PALETTE.background_bottom)

    glow_specs = [
        ((180, 120), 220, "#FFB57B55"),
        ((WIDTH - 170, 180), 240, "#FFDAB588"),
        ((WIDTH - 50, HEIGHT - 50), 280, "#FFEFD7A8"),
    ]
    for center, radius, color in glow_specs:
        draw_glow(image, center, radius, color)

    return image, draw


def draw_vertical_gradient(image: Image.Image, top: str, bottom: str) -> None:
    overlay = Image.new("RGBA", image.size, 0)
    top_rgb = hex_to_rgba(top)
    bottom_rgb = hex_to_rgba(bottom)
    pixels = overlay.load()
    height = image.size[1]
    width = image.size[0]
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = tuple(
            int(top_rgb[channel] + (bottom_rgb[channel] - top_rgb[channel]) * ratio)
            for channel in range(4)
        )
        for x in range(width):
            pixels[x, y] = color
    image.alpha_composite(overlay)


def draw_glow(image: Image.Image, center: tuple[int, int], radius: int, color: str) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    glow = ImageDraw.Draw(overlay)
    fill = hex_to_rgba(color)
    x, y = center
    glow.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=48))
    image.alpha_composite(overlay)


def hex_to_rgba(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    if len(value) == 6:
        value += "FF"
    return tuple(int(value[i : i + 2], 16) for i in range(0, 8, 2))


def add_shadow(image: Image.Image, box: tuple[int, int, int, int], radius: int = 24, alpha: int = 48) -> None:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow = ImageDraw.Draw(overlay)
    x1, y1, x2, y2 = box
    shadow.rounded_rectangle((x1, y1 + 8, x2, y2 + 8), radius=radius, fill=(219, 180, 140, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=18))
    image.alpha_composite(overlay)


def card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, outline: str | None = None, radius: int = 26) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline or fill, width=1)


def chip(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: str, text_fill: str, font: ImageFont.ImageFont = FONT_13) -> tuple[int, int, int, int]:
    x, y = xy
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0] + 26
    height = bbox[3] - bbox[1] + 14
    box = (x, y, x + width, y + height)
    draw.rounded_rectangle(box, radius=height // 2, fill=fill)
    draw.text((x + 13, y + 7), text, font=font, fill=text_fill)
    return box


def draw_logo(draw: ImageDraw.ImageDraw, image: Image.Image, xy: tuple[int, int], width: int = 120) -> None:
    if not LOGO_PATH.exists():
        draw.text(xy, "BioBot", font=FONT_24, fill=PALETTE.text)
        return
    logo = Image.open(LOGO_PATH).convert("RGBA")
    ratio = width / logo.width
    size = (width, int(logo.height * ratio))
    logo = logo.resize(size, Image.Resampling.LANCZOS)
    image.alpha_composite(logo, xy)


def draw_topbar(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    title: str,
    subtitle: str,
    project_name: str = "ACCuESS",
    status_chips: list[tuple[str, str, str]] | None = None,
) -> None:
    box = (42, 34, WIDTH - 42, 118)
    add_shadow(image, box, radius=30, alpha=38)
    card(draw, box, fill=PALETTE.shell, outline=PALETTE.border, radius=30)

    draw_logo(draw, image, (70, 50), width=118)
    draw.text((212, 48), title, font=FONT_28, fill=PALETTE.text)
    draw.text((214, 84), subtitle, font=FONT_14, fill=PALETTE.text_muted)

    if status_chips is None:
        status_chips = [
            (project_name, PALETTE.accent_soft, PALETTE.accent_deep),
            ("Bench ready", "#EEF9F3", "#2D8A61"),
            ("v2.0", "#F6F2FF", "#6B5CC8"),
        ]

    right_x = WIDTH - 72
    for text, fill, text_fill in reversed(status_chips):
        bbox = draw.textbbox((0, 0), text, font=FONT_13)
        chip_w = bbox[2] - bbox[0] + 26
        right_x -= chip_w
        chip(draw, (right_x, 53), text, fill, text_fill, FONT_13)
        right_x -= 12


def draw_sidebar(image: Image.Image, draw: ImageDraw.ImageDraw, active: str, project_name: str = "ACCuESS") -> None:
    box = (24, 24, 300, HEIGHT - 24)
    card(draw, box, fill=PALETTE.nav_bg, outline=PALETTE.border_soft, radius=30)
    draw_logo(draw, image, (54, 44), width=120)
    chip(draw, (54, 106), project_name, PALETTE.accent_soft, PALETTE.accent_deep, FONT_12)

    items = [
        "Overview",
        "Firmware",
        "Mechanical",
        "Application",
        "Settings",
    ]
    y = 172
    for item in items:
        is_active = item == active
        if is_active:
            draw.rounded_rectangle((42, y - 8, 282, y + 38), radius=18, fill=PALETTE.nav_active)
            draw.rounded_rectangle((42, y - 8, 52, y + 38), radius=5, fill=PALETTE.accent)
        draw.text((68, y + 3), item, font=FONT_16 if is_active else FONT_15, fill=PALETTE.text)
        y += 54

    draw.rounded_rectangle((42, HEIGHT - 176, 282, HEIGHT - 84), radius=22, fill=PALETTE.card, outline=PALETTE.border_soft)
    draw.text((62, HEIGHT - 154), "Live session", font=FONT_16, fill=PALETTE.text)
    draw.text((62, HEIGHT - 123), "Node scan healthy", font=FONT_13, fill=PALETTE.text_muted)
    chip(draw, (62, HEIGHT - 108), "14 online", "#EEF9F3", "#2D8A61", FONT_12)
    chip(draw, (148, HEIGHT - 108), "2 warnings", "#FFF3E8", "#C26E1E", FONT_12)


def draw_kpi(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, value: str, accent: str) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 18, y1 + 18, x1 + 74, y1 + 74), radius=18, fill=accent)
    draw.text((x1 + 18, y1 + 92), title, font=FONT_13, fill=PALETTE.text_muted)
    draw.text((x1 + 18, y1 + 122), value, font=FONT_24, fill=PALETTE.text)


def draw_line_chart(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, line_color: str) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), title, font=FONT_16, fill=PALETTE.text)
    draw.text((x2 - 96, y1 + 22), "24 min", font=FONT_12, fill=PALETTE.text_muted)
    chart = (x1 + 24, y1 + 66, x2 - 24, y2 - 24)
    draw.rounded_rectangle(chart, radius=18, fill=PALETTE.graph_bg)

    chart_x1, chart_y1, chart_x2, chart_y2 = chart
    for step in range(4):
        y = chart_y1 + (chart_y2 - chart_y1) * step / 3
        draw.line((chart_x1 + 18, y, chart_x2 - 18, y), fill="#F2DED0", width=1)

    points = [
        (chart_x1 + 32, chart_y2 - 52),
        (chart_x1 + 110, chart_y2 - 76),
        (chart_x1 + 190, chart_y2 - 62),
        (chart_x1 + 280, chart_y2 - 118),
        (chart_x1 + 360, chart_y2 - 94),
        (chart_x1 + 448, chart_y2 - 148),
        (chart_x1 + 534, chart_y2 - 102),
        (chart_x2 - 36, chart_y2 - 126),
    ]
    draw.line(points, fill=line_color, width=5)
    for point in points:
        draw.ellipse((point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5), fill=line_color)


def draw_table(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, columns: Iterable[str], rows: list[list[str]]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), title, font=FONT_16, fill=PALETTE.text)
    inner = (x1 + 20, y1 + 58, x2 - 20, y2 - 20)
    draw.rounded_rectangle(inner, radius=18, fill="#FFF9F4")
    inner_x1, inner_y1, inner_x2, inner_y2 = inner
    header_h = 42
    draw.rounded_rectangle((inner_x1, inner_y1, inner_x2, inner_y1 + header_h), radius=18, fill="#FFF1E3")
    columns = list(columns)
    col_width = (inner_x2 - inner_x1) / len(columns)
    for index, column in enumerate(columns):
        x = inner_x1 + index * col_width + 14
        draw.text((x, inner_y1 + 12), column, font=FONT_13, fill=PALETTE.text)

    row_h = (inner_y2 - inner_y1 - header_h) / max(len(rows), 1)
    for row_index, row in enumerate(rows):
        y = inner_y1 + header_h + row_index * row_h
        draw.line((inner_x1 + 12, y, inner_x2 - 12, y), fill="#F3E3D6", width=1)
        for col_index, value in enumerate(row):
            x = inner_x1 + col_index * col_width + 14
            fill = PALETTE.text if col_index < 2 else PALETTE.text_muted
            draw.text((x, y + 14), value, font=FONT_13, fill=fill)


def draw_button(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, primary: bool = False, danger: bool = False) -> None:
    fill = "#FFFFFF"
    outline = "#F0D9C6"
    text_fill = PALETTE.text
    if primary:
        fill = PALETTE.accent
        outline = PALETTE.accent
        text_fill = "#FFFFFF"
    elif danger:
        fill = "#FFF0F0"
        outline = "#F0C8C8"
        text_fill = PALETTE.danger
    draw.rounded_rectangle(box, radius=14, fill=fill, outline=outline, width=2)
    bbox = draw.textbbox((0, 0), text, font=FONT_13)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x1, y1, x2, y2 = box
    draw.text((x1 + (x2 - x1 - text_w) / 2, y1 + (y2 - y1 - text_h) / 2 - 1), text, font=FONT_13, fill=text_fill)


def draw_field(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], label: str, value: str, kind: str = "input") -> None:
    x1, y1, x2, y2 = box
    draw.text((x1, y1), label, font=FONT_12, fill=PALETTE.text_muted)
    field_box = (x1, y1 + 18, x2, y2)
    fill = "#FFFFFF"
    if kind == "readonly":
        fill = "#FFF8F2"
    draw.rounded_rectangle(field_box, radius=14, fill=fill, outline="#EFD7C5", width=2)
    draw.text((x1 + 14, y1 + 30), value, font=FONT_13, fill=PALETTE.text)
    if kind == "select":
        arrow_x = x2 - 24
        arrow_y = y1 + 36
        draw.polygon([(arrow_x - 6, arrow_y - 2), (arrow_x + 6, arrow_y - 2), (arrow_x, arrow_y + 6)], fill=hex_to_rgba(PALETTE.accent))


def draw_listbox(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    label: str,
    items: list[str],
    selected_index: int = 0,
    max_visible: int = 4,
) -> None:
    x1, y1, x2, y2 = box
    draw.text((x1, y1), label, font=FONT_12, fill=PALETTE.text_muted)
    list_box = (x1, y1 + 18, x2, y2)
    draw.rounded_rectangle(list_box, radius=14, fill="#FFFFFF", outline="#EFD7C5", width=2)

    inner_x1, inner_y1, inner_x2, inner_y2 = list_box
    row_h = 28
    available_h = max(30, inner_y2 - inner_y1 - 10)
    visible_rows = min(max_visible, max(1, available_h // row_h), max(1, len(items)))
    start_y = inner_y1 + 6
    scroll_needed = len(items) > visible_rows
    content_x2 = inner_x2 - (18 if scroll_needed else 8)

    for index in range(visible_rows):
        item_y1 = start_y + index * row_h
        item_y2 = item_y1 + row_h - 4
        if index >= len(items):
            break
        is_selected = index == selected_index
        fill = PALETTE.nav_active if is_selected else "#FFF9F4"
        draw.rounded_rectangle((inner_x1 + 6, item_y1, content_x2, item_y2), radius=10, fill=fill)
        draw.text((inner_x1 + 16, item_y1 + 6), items[index], font=FONT_13, fill=PALETTE.text)

    if scroll_needed:
        track = (inner_x2 - 12, inner_y1 + 8, inner_x2 - 6, inner_y2 - 8)
        draw.rounded_rectangle(track, radius=3, fill="#F4E8DD")
        thumb_h = max(24, int((visible_rows / len(items)) * (track[3] - track[1])))
        draw.rounded_rectangle((track[0], track[1] + 8, track[2], track[1] + 8 + thumb_h), radius=3, fill=PALETTE.accent_soft)


def draw_toggle(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, enabled: bool) -> None:
    x, y = xy
    draw.text((x, y + 2), label, font=FONT_13, fill=PALETTE.text)
    pill = (x + 180, y, x + 236, y + 28)
    fill = "#E9F7EF" if enabled else "#F4E8DD"
    knob_x = pill[2] - 20 if enabled else pill[0] + 20
    draw.rounded_rectangle(pill, radius=14, fill=fill)
    draw.ellipse((knob_x - 10, y + 4, knob_x + 10, y + 24), fill="#FFFFFF", outline="#D9C9BC")


def draw_command_console(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Command debug", font=FONT_16, fill=PALETTE.text)
    draw_listbox(draw, (x1 + 24, y1 + 56, x1 + 258, y1 + 152), "Command", ["GET_NODE_ID", "GET_UUID", "GET_INTERRUPT", "Get ZPOSS"], 0, 4)
    draw_listbox(draw, (x1 + 276, y1 + 56, x1 + 470, y1 + 152), "Target", ["Broadcast", "Node 03", "Node 11"], 0, 3)
    draw_button(draw, (x2 - 116, y1 + 96, x2 - 24, y1 + 138), "Send", primary=True)
    draw_field(draw, (x1 + 24, y1 + 172, x2 - 24, y1 + 224), "Payload", "0x00 0x00", "input")
    chip(draw, (x1 + 24, y1 + 248), "Binary mode", "#EEF6FF", "#4A77D1", FONT_12)
    chip(draw, (x1 + 118, y1 + 248), "Text mode", "#FFF3E8", "#C26E1E", FONT_12)
    terminal = (x1 + 24, y1 + 282, x2 - 24, y2 - 24)
    draw.rounded_rectangle(terminal, radius=18, fill="#FFF7EF")
    lines = [
        "[13:22:04.104] TX  0x7E 0x04 0x10 ...",
        "[13:22:04.115] RX  node=3  MCU version=2.1.4",
        "[13:22:04.133] RX  node=7  UUID=4F-A3-11-82",
        "[13:22:04.155] RX  node=11 interrupt=0",
        "[13:22:04.177] INFO frame loss monitor stable",
    ]
    y = y1 + 306
    for line in lines:
        draw.text((x1 + 40, y), line, font=FONT_13, fill="#6D5B4D")
        y += 28


def draw_joint_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, items: list[tuple[str, str]]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), title, font=FONT_16, fill=PALETTE.text)
    y = y1 + 68
    for label, value in items:
        draw.text((x1 + 24, y), label, font=FONT_13, fill=PALETTE.text_muted)
        draw.text((x2 - 90, y), value, font=FONT_13, fill=PALETTE.text)
        track = (x1 + 24, y + 24, x2 - 24, y + 36)
        draw.rounded_rectangle(track, radius=6, fill="#FFF5EA")
        draw.rounded_rectangle((track[0], track[1], track[0] + int((track[2] - track[0]) * 0.62), track[3]), radius=6, fill=PALETTE.accent)
        knob_x = track[0] + int((track[2] - track[0]) * 0.62)
        draw.ellipse((knob_x - 8, track[1] - 6, knob_x + 8, track[3] + 6), fill="#FFFFFF", outline=PALETTE.accent)
        y += 72


def draw_robot_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str) -> None:
    card(draw, box, fill=PALETTE.card_alt, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), title, font=FONT_16, fill=PALETTE.text)
    center_x = (x1 + x2) // 2
    base_y = y2 - 48
    segments = [
        (center_x - 80, base_y, center_x - 20, base_y - 38),
        (center_x - 20, base_y - 38, center_x + 34, base_y - 118),
        (center_x + 34, base_y - 118, center_x + 88, base_y - 84),
        (center_x + 88, base_y - 84, center_x + 118, base_y - 144),
    ]
    draw.rounded_rectangle((center_x - 106, base_y, center_x + 26, base_y + 24), radius=12, fill="#FFD6B0")
    for x_start, y_start, x_end, y_end in segments:
        draw.line((x_start, y_start, x_end, y_end), fill=PALETTE.accent_deep, width=16)
        draw.ellipse((x_start - 10, y_start - 10, x_start + 10, y_start + 10), fill="#FFFFFF", outline=PALETTE.accent_deep, width=4)
    end_x, end_y = segments[-1][2], segments[-1][3]
    draw.ellipse((end_x - 11, end_y - 11, end_x + 11, end_y + 11), fill="#FFFFFF", outline=PALETTE.accent_deep, width=4)
    draw.rounded_rectangle((end_x + 8, end_y - 12, end_x + 70, end_y + 10), radius=8, fill="#FFE7D1")


def draw_connection_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Connection and bench session", font=FONT_16, fill=PALETTE.text)
    draw_listbox(draw, (x1 + 24, y1 + 56, x1 + 220, y1 + 150), "COM port", ["COM9", "COM10", "COM11", "COM12"], 2, 4)
    draw_listbox(draw, (x1 + 240, y1 + 56, x1 + 436, y1 + 150), "Baud rate", ["115200", "230400", "345600"], 0, 3)
    draw_field(draw, (x1 + 456, y1 + 56, x1 + 720, y1 + 108), "Project config", "ACCuESS.yaml", "readonly")
    draw_button(draw, (x2 - 236, y1 + 92, x2 - 134, y1 + 134), "Scan ports")
    draw_button(draw, (x2 - 122, y1 + 92, x2 - 24, y1 + 134), "Connect", primary=True)

    chip(draw, (x1 + 24, y1 + 172), "Auto scan on connect", "#EEF9F3", "#2D8A61", FONT_12)
    chip(draw, (x1 + 176, y1 + 172), "MCU query enabled", "#EEF6FF", "#4A77D1", FONT_12)
    chip(draw, (x1 + 326, y1 + 172), "Last sync 13:26", "#FFF3E8", "#C26E1E", FONT_12)


def draw_firmware_setup(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Command and validation setup", font=FONT_16, fill=PALETTE.text)
    draw_field(draw, (x1 + 24, y1 + 56, x1 + 230, y1 + 108), "Command", "GET_NODE_ID", "select")
    draw_field(draw, (x1 + 248, y1 + 56, x1 + 410, y1 + 108), "Target node", "Broadcast", "select")
    draw_field(draw, (x1 + 428, y1 + 56, x1 + 666, y1 + 108), "Payload", "0x00 0x00", "input")
    draw_button(draw, (x2 - 116, y1 + 74, x2 - 24, y1 + 118), "Send", primary=True)

    chip(draw, (x1 + 24, y1 + 130), "Binary mode", "#EEF6FF", "#4A77D1", FONT_12)
    chip(draw, (x1 + 118, y1 + 130), "Text mode", "#FFF3E8", "#C26E1E", FONT_12)
    chip(draw, (x1 + 200, y1 + 130), "Loss trace", "#EEF9F3", "#2D8A61", FONT_12)


def draw_axis_control_grid(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Axis motion control", font=FONT_16, fill=PALETTE.text)
    draw_button(draw, (x2 - 174, y1 + 18, x2 - 100, y1 + 52), "Apply")
    draw_button(draw, (x2 - 92, y1 + 18, x2 - 24, y1 + 52), "Stop", danger=True)
    headers = ["Axis", "Current", "Target", "Jog", "Move"]
    start_y = y1 + 62
    col_x = [x1 + 24, x1 + 82, x1 + 156, x1 + 286, x1 + 356]
    for header, x in zip(headers, col_x):
        draw.text((x, start_y), header, font=FONT_12, fill=PALETTE.text_muted)

    axes = [("A1", "+18.2"), ("A2", "-07.2"), ("A3", "+42.0"), ("A4", "-13.8")]
    y = start_y + 34
    for axis, current in axes:
        draw.rounded_rectangle((x1 + 18, y - 10, x2 - 18, y + 42), radius=14, fill="#FFF9F4")
        draw.text((x1 + 28, y + 4), axis, font=FONT_13, fill=PALETTE.text)
        draw.text((x1 + 82, y + 4), current, font=FONT_13, fill=PALETTE.text)
        draw.rounded_rectangle((x1 + 150, y - 4, x1 + 256, y + 32), radius=12, fill="#FFFFFF", outline="#EFD7C5", width=2)
        draw.text((x1 + 164, y + 6), "18.4 deg", font=FONT_13, fill=PALETTE.text)
        draw_button(draw, (x1 + 278, y - 4, x1 + 314, y + 32), "-")
        draw_button(draw, (x1 + 320, y - 4, x1 + 356, y + 32), "+")
        draw_button(draw, (x1 + 366, y - 4, x1 + 420, y + 32), "Move", primary=True)
        y += 62


def draw_stress_setup(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Stress run setup", font=FONT_16, fill=PALETTE.text)
    draw_listbox(draw, (x1 + 24, y1 + 56, x1 + 240, y1 + 150), "Command", ["GET_NODE_ID", "GET_UUID", "GET_INTERRUPT"], 0, 3)
    draw_field(draw, (x1 + 258, y1 + 56, x1 + 438, y1 + 108), "Count per node", "1000", "input")
    draw_listbox(draw, (x1 + 456, y1 + 56, x1 + 690, y1 + 150), "Node scope", ["All online nodes", "Selected nodes", "Sensors only"], 0, 3)
    draw_button(draw, (x2 - 224, y1 + 92, x2 - 124, y1 + 134), "Stop", danger=True)
    draw_button(draw, (x2 - 112, y1 + 92, x2 - 24, y1 + 134), "Start", primary=True)
    chip(draw, (x1 + 24, y1 + 172), "Capture dropped frames", "#FFF3E8", "#C26E1E", FONT_12)
    chip(draw, (x1 + 184, y1 + 172), "Per-node summary", "#EEF9F3", "#2D8A61", FONT_12)


def draw_settings_form(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Bench defaults", font=FONT_16, fill=PALETTE.text)
    draw_listbox(draw, (x1 + 24, y1 + 56, x1 + 244, y1 + 150), "Preferred COM port", ["COM9", "COM10", "COM11", "COM12"], 2, 4)
    draw_listbox(draw, (x1 + 262, y1 + 56, x2 - 24, y1 + 150), "Baud rate", ["115200", "230400", "345600"], 0, 3)
    draw_listbox(draw, (x1 + 24, y1 + 170, x2 - 24, y1 + 264), "Report export", ["JSON + CSV", "JSON only", "CSV only"], 0, 3)
    draw_toggle(draw, (x1 + 24, y1 + 292), "Auto node scan", True)
    draw_toggle(draw, (x1 + 24, y1 + 332), "Restore last project", True)
    draw_toggle(draw, (x1 + 24, y1 + 372), "Write trace log", False)


def draw_enabled_tools_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Enabled tool areas", font=FONT_16, fill=PALETTE.text)
    items = [
        ("Overview workspace", True),
        ("Firmware tools", True),
        ("Mechanical tools", True),
        ("Application tools", True),
        ("Stress testing module", True),
        ("Settings page", True),
    ]
    y = y1 + 62
    for label, enabled in items:
        draw.rounded_rectangle((x1 + 18, y - 8, x2 - 18, y + 30), radius=14, fill="#F9FCFA")
        draw.text((x1 + 28, y + 1), label, font=FONT_13, fill=PALETTE.text)
        pill = (x2 - 90, y - 2, x2 - 34, y + 26)
        fill = "#E9F7EF" if enabled else "#F4E8DD"
        knob_x = pill[2] - 20 if enabled else pill[0] + 20
        draw.rounded_rectangle(pill, radius=14, fill=fill)
        draw.ellipse((knob_x - 10, y + 2, knob_x + 10, y + 22), fill="#FFFFFF", outline="#D9C9BC")
        y += 48


def draw_settings_actions_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Configuration actions", font=FONT_16, fill=PALETTE.text)
    draw_button(draw, (x1 + 24, y1 + 58, x2 - 24, y1 + 100), "Open config folder")
    draw_button(draw, (x1 + 24, y1 + 114, x2 - 24, y1 + 156), "Validate YAML")
    draw_button(draw, (x1 + 24, y1 + 170, x2 - 24, y1 + 212), "Save bench defaults", primary=True)
    draw_button(draw, (x1 + 24, y1 + 226, x2 - 24, y1 + 268), "Export bench preset")


def draw_quick_actions(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Quick actions", font=FONT_16, fill=PALETTE.text)
    draw_button(draw, (x1 + 24, y1 + 60, x1 + 178, y1 + 104), "Open firmware", primary=True)
    draw_button(draw, (x1 + 196, y1 + 60, x1 + 350, y1 + 104), "Run node scan")
    draw_button(draw, (x1 + 24, y1 + 122, x1 + 178, y1 + 166), "Start stress")
    draw_button(draw, (x1 + 196, y1 + 122, x1 + 350, y1 + 166), "Open settings")


def draw_capabilities_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Project capabilities", font=FONT_16, fill=PALETTE.text)
    chip(draw, (x1 + 24, y1 + 62), "5 axes", "#EEF6FF", "#4A77D1", FONT_12)
    chip(draw, (x1 + 102, y1 + 62), "HMI node", PALETTE.accent_soft, PALETTE.accent_deep, FONT_12)
    chip(draw, (x1 + 206, y1 + 62), "ZPOSS", "#EEF9F3", "#2D8A61", FONT_12)
    chip(draw, (x1 + 286, y1 + 62), "TOF", "#EEF9F3", "#2D8A61", FONT_12)
    draw.text((x1 + 24, y1 + 112), "Current focus", font=FONT_12, fill=PALETTE.text_muted)
    draw.text((x1 + 24, y1 + 136), "Transport stable. Mechanical repeatability still pending.", font=FONT_13, fill=PALETTE.text)


def draw_tuning_form(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Motion command panel", font=FONT_16, fill=PALETTE.text)
    mid = (x1 + x2) // 2
    draw_listbox(draw, (x1 + 24, y1 + 56, mid - 12, y1 + 150), "Node", ["Axis A", "Axis B", "Axis C"], 0, 3)
    draw_listbox(draw, (mid + 12, y1 + 56, x2 - 24, y1 + 150), "Control mode", ["Velocity PID", "Position PID", "Open-loop PWM"], 0, 3)
    draw_listbox(draw, (x1 + 24, y1 + 170, mid - 12, y1 + 264), "Command preset", ["Set Velocity 20", "Set Velocity 40", "Set Velocity 80"], 1, 3)
    draw_field(draw, (mid + 12, y1 + 170, x2 - 24, y1 + 222), "Value", "40", "input")
    draw_listbox(draw, (mid + 12, y1 + 242, x2 - 24, y1 + 336), "Query", ["Get Position", "Get Velocity", "Get Node Type"], 0, 3)
    draw_button(draw, (x1 + 24, y2 - 64, x1 + 124, y2 - 24), "Query")
    draw_button(draw, (x2 - 210, y2 - 64, x2 - 118, y2 - 24), "Run")
    draw_button(draw, (x2 - 106, y2 - 64, x2 - 24, y2 - 24), "Stop", danger=True)


def draw_operator_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Test run setup", font=FONT_16, fill=PALETTE.text)
    draw_listbox(draw, (x1 + 24, y1 + 56, x1 + 190, y1 + 150), "Run type", ["Integration", "Regression", "Production"], 0, 3)
    draw_field(draw, (x1 + 208, y1 + 56, x1 + 374, y1 + 108), "Operator", "Y. Wang", "input")
    draw_listbox(draw, (x1 + 392, y1 + 56, x1 + 558, y1 + 150), "Report", ["JSON + CSV", "JSON only", "CSV only"], 0, 3)
    draw_button(draw, (x2 - 200, y1 + 96, x2 - 114, y1 + 138), "Pause")
    draw_button(draw, (x2 - 102, y1 + 96, x2 - 24, y1 + 138), "Start", primary=True)

    draw.text((x1 + 24, y1 + 182), "Useful actions", font=FONT_13, fill=PALETTE.text_muted)
    draw_button(draw, (x1 + 24, y1 + 208, x1 + 146, y1 + 248), "Open HMI")
    draw_button(draw, (x1 + 158, y1 + 208, x1 + 280, y1 + 248), "Stress run")
    draw_button(draw, (x1 + 292, y1 + 208, x1 + 414, y1 + 248), "Export report")
    draw_button(draw, (x1 + 426, y1 + 208, x1 + 548, y1 + 248), "Stop all")

    draw.text((x1 + 24, y1 + 282), "Run progress", font=FONT_13, fill=PALETTE.text_muted)
    draw.rounded_rectangle((x1 + 24, y1 + 308, x2 - 24, y1 + 324), radius=8, fill="#FFF5EA")
    draw.rounded_rectangle((x1 + 24, y1 + 308, x1 + int((x2 - x1 - 48) * 0.68), y1 + 324), radius=8, fill=PALETTE.accent)
    draw.text((x1 + 24, y1 + 338), "Step 4 / 6 - Sensor calibration and controller validation", font=FONT_12, fill=PALETTE.text_muted)


def draw_controller_config_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Controller profile", font=FONT_16, fill=PALETTE.text)
    draw_listbox(draw, (x1 + 24, y1 + 56, x2 - 24, y1 + 150), "Profile", ["ACCuESS_Default_v2", "Bench_A_Quick", "ML2_Validation"], 0, 3)
    draw_listbox(draw, (x1 + 24, y1 + 170, x2 - 24, y1 + 264), "Motion preset", ["Velocity 20", "Velocity 40", "Velocity 80"], 1, 3)
    draw_listbox(draw, (x1 + 24, y1 + 284, x2 - 24, y1 + 378), "Retry policy", ["1 retry", "3 retries", "5 retries"], 1, 3)
    draw_button(draw, (x1 + 24, y2 - 64, x1 + 126, y2 - 24), "Load")
    draw_button(draw, (x1 + 138, y2 - 64, x1 + 240, y2 - 24), "Apply")
    draw_button(draw, (x2 - 116, y2 - 64, x2 - 24, y2 - 24), "Save", primary=True)


def draw_stress_summary_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Stress testing", font=FONT_16, fill=PALETTE.text)
    chip(draw, (x1 + 24, y1 + 56), "Last run: Pass", "#EEF9F3", "#2D8A61", FONT_12)
    chip(draw, (x1 + 132, y1 + 56), "14 nodes", "#EEF6FF", "#4A77D1", FONT_12)
    chip(draw, (x1 + 220, y1 + 56), "1000 frames", PALETTE.accent_soft, PALETTE.accent_deep, FONT_12)
    draw.text((x1 + 24, y1 + 106), "Last summary", font=FONT_12, fill=PALETTE.text_muted)
    draw.text((x1 + 24, y1 + 130), "All nodes completed. 42 missing frames were automatically retried.", font=FONT_13, fill=PALETTE.text)
    draw_button(draw, (x1 + 24, y2 - 64, x1 + 156, y2 - 24), "Export")
    draw_button(draw, (x2 - 116, y2 - 64, x2 - 24, y2 - 24), "Run", primary=True)


def draw_transport_summary_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Transport summary", font=FONT_16, fill=PALETTE.text)
    rows = [
        ("Frame loss", "0.09%"),
        ("Retries", "12"),
        ("Avg latency", "12 ms"),
        ("Last scan", "13:26"),
    ]
    y = y1 + 64
    for label, value in rows:
        draw.rounded_rectangle((x1 + 18, y - 8, x2 - 18, y + 30), radius=14, fill="#FFF9F4")
        draw.text((x1 + 32, y + 1), label, font=FONT_13, fill=PALETTE.text_muted)
        draw.text((x2 - 96, y + 1), value, font=FONT_13, fill=PALETTE.text)
        y += 48


def draw_frame_loss_summary_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Frame loss summary", font=FONT_16, fill=PALETTE.text)
    rows = [
        ("Window", "24 min"),
        ("Dropped", "42"),
        ("Recovered", "36"),
        ("Worst node", "Node 11"),
    ]
    y = y1 + 64
    for label, value in rows:
        draw.rounded_rectangle((x1 + 18, y - 8, x2 - 18, y + 30), radius=14, fill="#FFF9F4")
        draw.text((x1 + 32, y + 1), label, font=FONT_13, fill=PALETTE.text_muted)
        draw.text((x2 - 120, y + 1), value, font=FONT_13, fill=PALETTE.text)
        y += 48
    draw.text((x1 + 24, y2 - 72), "Recent incidents", font=FONT_12, fill=PALETTE.text_muted)
    draw.text((x1 + 24, y2 - 48), "Node 11 retry escalation", font=FONT_13, fill=PALETTE.text)


def draw_sensor_snapshot_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Sensor snapshot", font=FONT_16, fill=PALETTE.text)
    draw_table(
        draw,
        (x1 + 16, y1 + 46, x2 - 16, y2 - 16),
        "",
        ["Sensor", "Value", "State"],
        [
            ["ZPOSS", "224", "OK"],
            ["TOF", "198", "OK"],
            ["INT", "0", "OK"],
            ["Node 14", "Warn", "Review"],
        ],
    )


def draw_axis_snapshot_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Selected axis snapshot", font=FONT_16, fill=PALETTE.text)
    rows = [
        ("Axis", "A2"),
        ("Position", "-07.2"),
        ("Velocity", "0.21 m/s"),
        ("PWM", "22%"),
        ("Limit state", "Normal"),
    ]
    y = y1 + 64
    for label, value in rows:
        draw.rounded_rectangle((x1 + 18, y - 8, x2 - 18, y + 30), radius=14, fill="#FFF9F4")
        draw.text((x1 + 32, y + 1), label, font=FONT_13, fill=PALETTE.text_muted)
        draw.text((x2 - 120, y + 1), value, font=FONT_13, fill=PALETTE.text)
        y += 48


def draw_motion_observation_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Motor behaviour observation", font=FONT_16, fill=PALETTE.text)
    rows = [
        ("A1", "+18.2", "34%", "0.42 m/s"),
        ("A2", "-07.2", "22%", "0.21 m/s"),
        ("A3", "+42.0", "47%", "0.53 m/s"),
        ("A4", "-13.8", "16%", "0.18 m/s"),
    ]
    header_y = y1 + 64
    headers = ["Axis", "Offset", "PWM", "Velocity"]
    xs = [x1 + 28, x1 + 114, x1 + 212, x1 + 304]
    for header, x in zip(headers, xs):
        draw.text((x, header_y), header, font=FONT_12, fill=PALETTE.text_muted)
    y = header_y + 32
    for axis, offset, pwm, vel in rows:
        draw.rounded_rectangle((x1 + 18, y - 8, x2 - 18, y + 30), radius=14, fill="#FFF9F4")
        for value, x in zip((axis, offset, pwm, vel), xs):
            draw.text((x, y + 1), value, font=FONT_13, fill=PALETTE.text)
        y += 48


def draw_repeatability_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Repeatability check", font=FONT_16, fill=PALETTE.text)
    mid = (x1 + x2) // 2
    draw_listbox(draw, (x1 + 24, y1 + 56, mid - 12, y1 + 150), "Axis", ["Axis A", "Axis B", "Axis C"], 0, 3)
    draw_field(draw, (mid + 12, y1 + 56, x2 - 24, y1 + 108), "Cycles", "5", "input")
    draw_field(draw, (mid + 12, y1 + 128, x2 - 24, y1 + 180), "Tolerance", "+/-0.20", "input")
    draw_button(draw, (x2 - 116, y1 + 192, x2 - 24, y1 + 232), "Run", primary=True)
    chip(draw, (x1 + 24, y1 + 202), "Last max dev 0.14", "#EEF9F3", "#2D8A61", FONT_12)
    chip(draw, (x1 + 180, y1 + 202), "Pass rate 5 / 5", "#EEF6FF", "#4A77D1", FONT_12)
    chart = (x1 + 24, y1 + 250, x2 - 24, y2 - 24)
    draw.rounded_rectangle(chart, radius=18, fill=PALETTE.graph_bg)
    bars = [72, 88, 80, 92, 84]
    labels = ["C1", "C2", "C3", "C4", "C5"]
    cx1, cy1, cx2, cy2 = chart
    base_y = cy2 - 28
    left = cx1 + 34
    for idx, value in enumerate(bars):
        x = left + idx * 58
        h = (cy2 - cy1 - 70) * value / 100
        draw.rounded_rectangle((x, base_y - h, x + 28, base_y), radius=10, fill=PALETTE.success)
        draw.text((x - 2, base_y + 8), labels[idx], font=FONT_12, fill=PALETTE.text_muted)


def draw_project_summary_card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card_alt, outline=PALETTE.border_soft, radius=22)
    x1, y1, x2, y2 = box
    draw.text((x1 + 20, y1 + 18), "Selected project summary", font=FONT_16, fill=PALETTE.text)
    chip(draw, (x1 + 20, y1 + 54), "5 axes", "#EEF6FF", "#4A77D1", FONT_12)
    chip(draw, (x1 + 96, y1 + 54), "Sensors", "#EEF9F3", "#2D8A61", FONT_12)
    chip(draw, (x1 + 182, y1 + 54), "HMI node", PALETTE.accent_soft, PALETTE.accent_deep, FONT_12)
    draw.text((x1 + 20, y1 + 104), "Config-driven workspace with role-based tools for the selected project.", font=FONT_13, fill=PALETTE.text_muted)

def draw_status_tiles(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], items: list[tuple[str, str, str]]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    tile_w = (x2 - x1 - 48) // len(items)
    for idx, (title, value, accent) in enumerate(items):
        tx1 = x1 + 18 + idx * tile_w
        tx2 = tx1 + tile_w - 12
        draw.rounded_rectangle((tx1, y1 + 18, tx2, y2 - 18), radius=18, fill="#FFF9F4")
        draw.rounded_rectangle((tx1 + 18, y1 + 34, tx1 + 60, y1 + 76), radius=14, fill=accent)
        draw.text((tx1 + 18, y1 + 92), title, font=FONT_12, fill=PALETTE.text_muted)
        draw.text((tx1 + 18, y1 + 122), value, font=FONT_20, fill=PALETTE.text)


def draw_diag_filters(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Trace filters", font=FONT_16, fill=PALETTE.text)
    draw_field(draw, (x1 + 24, y1 + 56, x1 + 214, y1 + 108), "Time range", "Last 24 min", "select")
    draw_field(draw, (x1 + 232, y1 + 56, x1 + 388, y1 + 108), "Node", "All", "select")
    draw_field(draw, (x1 + 406, y1 + 56, x1 + 562, y1 + 108), "Severity", "Warn + Error", "select")
    draw_button(draw, (x2 - 220, y1 + 64, x2 - 122, y1 + 108), "Export")
    draw_button(draw, (x2 - 110, y1 + 64, x2 - 24, y1 + 108), "Apply", primary=True)


def draw_incident_table(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), "Incident queue", font=FONT_16, fill=PALETTE.text)
    rows = [
        ("Warn", "Node 14 sensor outlier", "Watch"),
        ("Warn", "Node 11 retry escalation", "Escalate"),
        ("Info", "Auto reconnect succeeded", "Close"),
        ("Warn", "Persistent log export pending", "Export"),
    ]
    y = y1 + 60
    colors = {"Warn": "#FFF3E8", "Info": "#EEF6FF"}
    text_colors = {"Warn": "#C26E1E", "Info": "#4A77D1"}
    for level, message, action in rows:
        draw.rounded_rectangle((x1 + 18, y, x2 - 18, y + 48), radius=16, fill="#FFF9F4")
        chip(draw, (x1 + 30, y + 10), level, colors[level], text_colors[level], FONT_12)
        draw.text((x1 + 110, y + 15), message, font=FONT_13, fill=PALETTE.text)
        draw_button(draw, (x2 - 108, y + 8, x2 - 28, y + 40), action)
        y += 58


def draw_runtime_alerts_compact(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=20)
    x1, y1, x2, y2 = box
    draw.text((x1 + 18, y1 + 16), "Runtime alerts", font=FONT_14, fill=PALETTE.text)
    items = [
        ("TOF node has 1 warning", False),
        ("HMI handshake still pending", False),
        ("Last node scan completed", True),
    ]
    y = y1 + 46
    for label, positive in items:
        fill = "#EEF9F3" if positive else "#FFF5EA"
        draw.rounded_rectangle((x1 + 18, y, x2 - 18, y + 24), radius=12, fill=fill)
        accent_fill = PALETTE.success if positive else PALETTE.warning
        accent_text = "OK" if positive else "!"
        draw.ellipse((x1 + 26, y + 3, x1 + 44, y + 21), fill=accent_fill)
        draw.text((x1 + 31, y + 4), accent_text, font=FONT_12, fill="#FFFFFF")
        draw.text((x1 + 54, y + 5), label, font=FONT_12, fill=PALETTE.text)
        y += 30


def draw_quick_actions_compact(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=20)
    x1, y1, x2, y2 = box
    draw.text((x1 + 18, y1 + 16), "Quick actions", font=FONT_14, fill=PALETTE.text)
    draw_button(draw, (x1 + 18, y1 + 48, x1 + 160, y1 + 86), "Open firmware", primary=True)
    draw_button(draw, (x1 + 176, y1 + 48, x1 + 318, y1 + 86), "Run node scan")


def draw_capabilities_compact(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=20)
    x1, y1, x2, y2 = box
    draw.text((x1 + 18, y1 + 16), "Project capabilities", font=FONT_14, fill=PALETTE.text)
    chip(draw, (x1 + 18, y1 + 48), "5 axes", "#EEF6FF", "#4A77D1", FONT_12)
    chip(draw, (x1 + 94, y1 + 48), "HMI node", PALETTE.accent_soft, PALETTE.accent_deep, FONT_12)
    chip(draw, (x1 + 196, y1 + 48), "ZPOSS", "#EEF9F3", "#2D8A61", FONT_12)
    chip(draw, (x1 + 274, y1 + 48), "TOF", "#EEF9F3", "#2D8A61", FONT_12)
    draw.text((x1 + 18, y1 + 88), "Feature set loaded from the selected project config.", font=FONT_12, fill=PALETTE.text_muted)

def draw_checklist(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, items: list[tuple[str, bool]]) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), title, font=FONT_16, fill=PALETTE.text)
    y = y1 + 66
    for label, done in items:
        fill = "#EAF7EF" if done else "#FFF5EA"
        accent = PALETTE.success if done else PALETTE.warning
        draw.rounded_rectangle((x1 + 24, y - 6, x2 - 24, y + 34), radius=14, fill=fill)
        draw.ellipse((x1 + 38, y + 4, x1 + 58, y + 24), fill=accent)
        draw.text((x1 + 41, y + 5), "OK" if done else "!", font=FONT_12, fill="#FFFFFF")
        draw.text((x1 + 74, y + 4), label, font=FONT_14, fill=PALETTE.text)
        y += 50


def draw_metric_bars(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, labels: list[str], values: list[int], color: str) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=24)
    x1, y1, x2, y2 = box
    draw.text((x1 + 24, y1 + 20), title, font=FONT_16, fill=PALETTE.text)
    left = x1 + 28
    base_y = y2 - 42
    max_height = 150
    bar_w = 34
    gap = 28
    for idx, (label, value) in enumerate(zip(labels, values)):
        x = left + idx * (bar_w + gap)
        h = max_height * value / 100
        draw.rounded_rectangle((x, base_y - h, x + bar_w, base_y), radius=10, fill=color)
        draw.text((x - 2, base_y + 12), label, font=FONT_12, fill=PALETTE.text_muted)
        draw.text((x - 4, base_y - h - 24), f"{value}", font=FONT_12, fill=PALETTE.text)


def draw_console_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], lines: list[str] | None = None) -> None:
    card(draw, box, fill=PALETTE.card, outline=PALETTE.border_soft, radius=20)
    x1, y1, x2, y2 = box
    draw.text((x1 + 18, y1 + 14), "Console", font=FONT_14, fill=PALETTE.text)
    draw_button(draw, (x2 - 186, y1 + 8, x2 - 104, y1 + 42), "Clear")
    draw_button(draw, (x2 - 92, y1 + 8, x2 - 18, y1 + 42), "Save")
    terminal = (x1 + 18, y1 + 52, x2 - 18, y2 - 16)
    draw.rounded_rectangle(terminal, radius=14, fill="#2A221D")
    if lines is None:
        lines = [
            "[13:28:02.104] INFO  Bench session active",
            "[13:28:03.115] RX    Node 03 MCU version OK",
            "[13:28:04.122] WARN  Node 14 sensor outlier",
            "[13:28:05.144] INFO  Stress setup ready",
        ]
    y = terminal[1] + 14
    for line in lines[:4]:
        draw.text((terminal[0] + 16, y), line, font=FONT_12, fill="#F5EDE7")
        y += 24


def draw_shell_base(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    page_title: str,
    page_subtitle: str,
    active_nav: str,
    project_name: str = "ACCuESS",
) -> tuple[int, int, int, int]:
    draw_sidebar(image, draw, active_nav, project_name)
    content_box = (324, 24, WIDTH - 24, HEIGHT - 24)
    card(draw, content_box, fill="#FFFFFFCC", outline=PALETTE.border_soft, radius=32)
    x1, y1, x2, y2 = content_box
    console_box = (x2 - 340, y1 + 20, x2 - 20, y2 - 20)
    draw_console_panel(draw, console_box)
    body_box = (x1 + 20, y1 + 20, console_box[0] - 18, y2 - 20)
    return body_box


def render_selector(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    main_box = (96, 78, WIDTH - 96, HEIGHT - 64)
    add_shadow(image, main_box, radius=36, alpha=28)
    card(draw, main_box, fill=PALETTE.shell, outline=PALETTE.border_soft, radius=34)

    if SELECTOR_IMAGE_PATH.exists():
        brand = Image.open(SELECTOR_IMAGE_PATH).convert("RGBA")
        ratio = 356 / brand.width
        resized = brand.resize((356, int(brand.height * ratio)), Image.Resampling.LANCZOS)
        image.alpha_composite(resized, (148, 182))
    else:
        draw_logo(draw, image, (148, 182), width=220)

    draw.text((148, 448), "BioBot Robot Arm Tester", font=FONT_28, fill=PALETTE.text)
    draw.text((148, 494), "Select a project and open its workspace.", font=FONT_15, fill=PALETTE.text_muted)

    draw.text((704, 174), "Select Project", font=FONT_28, fill=PALETTE.text)
    draw.text((704, 216), "Project list", font=FONT_14, fill=PALETTE.text_muted)

    draw_listbox(
        draw,
        (704, 246, 1346, 738),
        "",
        ["ACCuESS", "ML2.0", "Future_Project_03", "Future_Project_04", "Future_Project_05", "Future_Project_06"],
        0,
        8,
    )
    draw_button(draw, (1092, 772, 1218, 828), "Cancel")
    draw_button(draw, (1232, 772, 1346, 828), "Open", primary=True)


def render_overview(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    x1, y1, x2, y2 = draw_shell_base(image, draw, "Project Overview", "Default landing page for the selected project", "Overview")
    gap = 18
    inner_x1, inner_y1, inner_x2, inner_y2 = x1, y1, x2, y2
    width = inner_x2 - inner_x1
    connection_h = 190
    draw_connection_panel(draw, (inner_x1, inner_y1, inner_x2, inner_y1 + connection_h))

    kpi_y = inner_y1 + connection_h + gap
    kpi_h = 146
    kpi_w = (width - gap * 3) // 4
    kpi_boxes = []
    for idx in range(4):
        left = inner_x1 + idx * (kpi_w + gap)
        kpi_boxes.append((left, kpi_y, left + kpi_w, kpi_y + kpi_h))
    draw_kpi(draw, kpi_boxes[0], "Nodes online", "14 / 16", "#FFF0E2")
    draw_kpi(draw, kpi_boxes[1], "Motor health", "Stable", "#EEF9F3")
    draw_kpi(draw, kpi_boxes[2], "Frame loss", "0.09%", "#EEF6FF")
    draw_kpi(draw, kpi_boxes[3], "Active alerts", "2", "#FFF4E6")

    mid_y = kpi_y + kpi_h + gap
    mid_h = 214
    left_w = int((width - gap) * 0.52)
    draw_transport_summary_panel(draw, (inner_x1, mid_y, inner_x1 + left_w, mid_y + mid_h))
    draw_table(
        draw,
        (inner_x1 + left_w + gap, mid_y, inner_x2, mid_y + mid_h),
        "Node summary",
        ["Node", "Role", "State", "Version"],
        [
            ["3", "Axis A", "Online", "2.1.4"],
            ["7", "Axis C", "Online", "2.1.4"],
            ["11", "HMI", "Online", "1.9.8"],
            ["14", "TOF", "Warn", "2.0.1"],
        ],
    )

    bottom_y = mid_y + mid_h + gap
    card_h = inner_y2 - bottom_y
    small_w = (width - gap * 2) // 3
    draw_runtime_alerts_compact(draw, (inner_x1, bottom_y, inner_x1 + small_w, inner_y2))
    draw_quick_actions_compact(draw, (inner_x1 + small_w + gap, bottom_y, inner_x1 + small_w * 2 + gap, inner_y2))
    draw_capabilities_compact(draw, (inner_x1 + (small_w + gap) * 2, bottom_y, inner_x2, inner_y2))


def render_firmware(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    x1, y1, x2, y2 = draw_shell_base(image, draw, "Firmware Tools", "Protocol validation, command debug, sensor data and motion tuning", "Firmware")
    gap = 18
    width = x2 - x1
    top_h = 400
    left_w = int((width - gap) * 0.58)
    draw_command_console(draw, (x1, y1, x1 + left_w, y1 + top_h))
    draw_table(
        draw,
        (x1 + left_w + gap, y1, x2, y1 + top_h),
        "UART protocol monitor",
        ["Time", "Dir", "Node", "Summary"],
        [
            ["13:22:04", "TX", "broadcast", "GET_NODE_ID"],
            ["13:22:04", "RX", "3", "MCU version OK"],
            ["13:22:05", "RX", "11", "Interrupt=0"],
            ["13:22:05", "RX", "14", "TOF range=219"],
        ],
    )
    bottom_y = y1 + top_h + gap
    bottom_h = y2 - bottom_y
    col_w = (width - gap * 2) // 3
    draw_frame_loss_summary_panel(draw, (x1, bottom_y, x1 + col_w, y2))
    draw_tuning_form(draw, (x1 + col_w + gap, bottom_y, x1 + col_w * 2 + gap, y2))
    draw_sensor_snapshot_panel(draw, (x1 + (col_w + gap) * 2, bottom_y, x2, y2))


def render_mechanical(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    x1, y1, x2, y2 = draw_shell_base(image, draw, "Mechanical Tools", "Motor movement, offset observation, limits and repeatability", "Mechanical")
    gap = 18
    width = x2 - x1
    top_h = 414
    left_w = 280
    draw_motion_observation_panel(draw, (x1, y1, x1 + left_w, y1 + top_h))
    draw_axis_control_grid(draw, (x1 + left_w + gap, y1, x2, y1 + top_h))

    bottom_y = y1 + top_h + gap
    col_w = (width - gap * 2) // 3
    draw_repeatability_panel(draw, (x1, bottom_y, x1 + col_w, y2))
    draw_table(
        draw,
        (x1 + col_w + gap, bottom_y, x1 + col_w * 2 + gap, y2),
        "Sensor limits and offsets",
        ["Item", "Current", "Lower", "Upper"],
        [
            ["ZPOSS", "224", "180", "260"],
            ["TOF", "198", "140", "260"],
            ["Axis 2 offset", "-0.7", "-2.0", "+2.0"],
            ["Axis 4 offset", "+0.2", "-2.0", "+2.0"],
        ],
    )
    draw_axis_snapshot_panel(draw, (x1 + (col_w + gap) * 2, bottom_y, x2, y2))


def render_application(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    x1, y1, x2, y2 = draw_shell_base(image, draw, "Application / Production", "Integration flow, guided control and production-facing tools", "Application")
    gap = 18
    width = x2 - x1
    top_h = 388
    col_w = (width - gap * 2) // 3
    draw_checklist(
        draw,
        (x1, y1, x1 + col_w, y1 + top_h),
        "Integration checklist",
        [
            ("Serial connection", True),
            ("MCU version query", True),
            ("Node identity validation", True),
            ("Robot HMI handshake", False),
            ("Motion profile validation", False),
            ("Final report export", False),
        ],
    )
    draw_controller_config_panel(draw, (x1 + col_w + gap, y1, x1 + col_w * 2 + gap, y1 + top_h))
    draw_stress_summary_panel(draw, (x1 + (col_w + gap) * 2, y1, x2, y1 + top_h))
    draw_operator_panel(draw, (x1, y1 + top_h + gap, x2, y2))


def render_diagnostics(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    x1, y1, x2, y2 = draw_shell_base(image, draw, "Diagnostics", "Deep monitoring for transport, node health and runtime incidents", "Diagnostics")
    draw_diag_filters(draw, (x1 + 26, y1 + 30, x2 - 26, y1 + 170))
    draw_line_chart(draw, (x1 + 26, y1 + 194, x1 + 530, y1 + 470), "Transport latency", "#5B8DEE")
    draw_line_chart(draw, (x1 + 552, y1 + 194, x2 - 26, y1 + 470), "Warning and retry trend", "#D85858")
    draw_table(
        draw,
        (x1 + 26, y1 + 494, x1 + 720, y2 - 26),
        "Protocol trace",
        ["Time", "Node", "Type", "Message"],
        [
            ["13:28:02", "3", "INFO", "Node ready"],
            ["13:28:04", "11", "WARN", "Intermittent timeout"],
            ["13:28:06", "14", "WARN", "TOF outlier filtered"],
            ["13:28:07", "7", "INFO", "Recovery successful"],
            ["13:28:09", "11", "ERROR", "2 retries consumed"],
        ],
    )
    draw_incident_table(draw, (x1 + 742, y1 + 494, x2 - 26, y2 - 26))


def render_settings(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    x1, y1, x2, y2 = draw_shell_base(image, draw, "Settings & Config", "Project metadata, feature toggles and bench-level preferences", "Settings")
    gap = 18
    width = x2 - x1
    left_w = int((width - gap) * 0.56)
    top_h = 328
    draw_table(
        draw,
        (x1, y1, x1 + left_w, y1 + top_h),
        "Project metadata",
        ["Field", "Value"],
        [
            ["Project", "ACCuESS"],
            ["Config file", "project_configs/ACCuESS.yaml"],
            ["Axis count", "5"],
            ["HMI", "Enabled"],
            ["Primary sensors", "ZPOSS, TOF"],
        ],
    )
    draw_enabled_tools_panel(draw, (x1 + left_w + gap, y1, x2, y1 + top_h))
    draw_settings_form(draw, (x1, y1 + top_h + gap, x1 + left_w, y2))
    draw_settings_actions_panel(draw, (x1 + left_w + gap, y1 + top_h + gap, x2, y2))


def compose_overview_board(screen_paths: list[Path]) -> None:
    columns = 2
    thumb_w = 720
    thumb_h = 432
    padding = 52
    title_h = 140
    board_w = padding * 3 + thumb_w * columns
    rows = (len(screen_paths) + columns - 1) // columns
    board_h = title_h + padding * (rows + 1) + thumb_h * rows

    board = Image.new("RGBA", (board_w, board_h), PALETTE.background_top)
    draw = ImageDraw.Draw(board)
    draw_vertical_gradient(board, PALETTE.background_top, PALETTE.background_bottom)
    draw_glow(board, (180, 140), 240, "#FFB57B4E")
    draw_glow(board, (board_w - 180, board_h - 160), 260, "#FFE6CA92")
    draw.text((padding, 42), "Phase 2 UI Mockup Board", font=FONT_32, fill=PALETTE.text)
    draw.text((padding, 88), "Selector plus six core workspace screens for the BioBot platform.", font=FONT_16, fill=PALETTE.text_muted)

    for index, path in enumerate(screen_paths):
        row = index // columns
        col = index % columns
        x = padding + col * (thumb_w + padding)
        y = title_h + padding + row * (thumb_h + padding)
        box = (x, y, x + thumb_w, y + thumb_h)
        add_shadow(board, box, radius=28, alpha=36)
        card(draw, box, fill="#FFFFFF", outline=PALETTE.border_soft, radius=26)
        preview = Image.open(path).convert("RGBA").resize((thumb_w - 28, thumb_h - 60), Image.Resampling.LANCZOS)
        board.alpha_composite(preview, (x + 14, y + 14))
        label = path.stem.replace("_", " ").title()
        draw.text((x + 20, y + thumb_h - 38), label, font=FONT_14, fill=PALETTE.text)

    board.save(OUTPUT_DIR / "00_phase2_ui_overview_board.png")


def render_screen(filename: str, renderer: Callable[[Image.Image, ImageDraw.ImageDraw], None]) -> Path:
    image, draw = make_canvas()
    renderer(image, draw)
    path = OUTPUT_DIR / filename
    image.save(path)
    return path


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    screens = [
        ("01_selector.png", render_selector),
        ("02_workspace_overview.png", render_overview),
        ("03_firmware_tools.png", render_firmware),
        ("04_mechanical_tools.png", render_mechanical),
        ("05_application_production.png", render_application),
        ("06_settings_config.png", render_settings),
    ]

    generated = [render_screen(filename, renderer) for filename, renderer in screens]
    compose_overview_board(generated)


if __name__ == "__main__":
    main()
