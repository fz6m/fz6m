#!/usr/bin/env python3
"""Generate Kanamio's profile README and self-contained SVG assets.

Inspired by the hero and pill links in https://github.com/caru-ini/caru-ini.
Typography, metrics, and icon shapes follow the reference, with requested changes.
Emoji graphics by Twitter, Inc. and contributors, https://github.com/twitter/twemoji
Twemoji graphics are licensed under CC BY 4.0. See assets/emoji/LICENSE-GRAPHICS.
Run `just generate`, or `just generate https://example.com/new-avatar.png`.
The avatar is fetched on every run. Its compressed cache is ignored by Git.
Font and Twemoji source files are downloaded only when their ignored cache is missing.
Figtree is the default font. Use --font to select another font family.
Run `just font=chillround generate` to select the optional rounded font.
Open html/index.html to check the generated README at different viewport widths.
"""

from __future__ import annotations

import argparse
import base64
import colorsys
import io
import json
import math
import xml.etree.ElementTree as ET
from functools import lru_cache
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageCms, ImageOps

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
DEFAULT_FONT = "figtree"
FONT_FAMILY = DEFAULT_FONT
FONT_SOURCES = {
    "figtree": (
        "Figtree.ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/figtree/Figtree%5Bwght%5D.ttf",
    ),
    "chillround": (
        "ChillRoundF-v3.ttf",
        "https://raw.githubusercontent.com/Warren2060/ChillRound/main/ChillRoundF%20v3.0.ttf",
    ),
}
FONT_FILENAME, FONT_URL = FONT_SOURCES[FONT_FAMILY]
FONT_PATH = ASSETS / "fonts" / FONT_FILENAME
AVATAR_URL = "https://bafkreiezqlkiu2ypbvlih7sjz72owpz54uisjcdjhnvieajoj66njptgia.ipfs.inbrowser.link/"
NAME = "Kanamio"
ROLE = "AI & Software Engineer"
INTRO = (
    "Software engineer focused on AI, frontend infrastructure, and developer productivity",
    "Building frontend architecture and enterprise systems while I follow my heart",
    "Programming with love",
)
LINKS = (
    ("website", "kanamio.dev", "https://kanamio.dev/"),
    ("x", "kanamiox", "https://x.com/kanamiox"),
)
WIDTH, HEIGHT = 900, 256
PADDING, CORNER_RADIUS = 40, 32
AVATAR_SIZE, AVATAR_BORDER = 160, 4
MOBILE_WIDTH, MOBILE_BREAKPOINT = 360, 640
STACK_BREAKPOINT, BUTTON_GAP = 384, 32
NAME_SIZE, NAME_WEIGHT, INTRO_SIZE = 64, 800, 16
BUTTON_HEIGHT, BUTTON_SIZE, BUTTON_ICON_SIZE = 44, 16, 18
INK, RULE = "#0E2336", "#C3D4E0"
EMOJI_FILES = ("2728.svg", "1f6e0.svg", "1f497.svg")
EMOJI_BASE_URL = "https://raw.githubusercontent.com/twitter/twemoji/v14.0.2/assets/svg"
ET.register_namespace("", "http://www.w3.org/2000/svg")


def download(url: str) -> bytes:
    """Fetch a resource with equivalent IPFS or repository CDN fallbacks."""
    urls = [url]
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    if ".ipfs." in hostname:
        content_id = hostname.split(".")[0]
        urls.append(f"https://gateway.pinata.cloud/ipfs/{content_id}{parsed.path}")
    elif hostname == "raw.githubusercontent.com":
        owner, repository, revision, resource = parsed.path.lstrip("/").split("/", 3)
        urls.append(f"https://cdn.jsdelivr.net/gh/{owner}/{repository}@{revision}/{resource}")
    failures = []
    for source in urls:
        try:
            request = Request(source, headers={"User-Agent": "Kanamio-README/1.0"})
            with urlopen(request, timeout=20) as response:
                return response.read()
        except (URLError, TimeoutError) as error:
            failures.append(f"{source}: {error}")
            print(f"Download source unavailable: {source}")
    raise RuntimeError("Could not download the resource.\n" + "\n".join(failures))


def ensure_cached_assets() -> None:
    """Download and validate missing font and emoji sources before caching them."""
    resources = [(FONT_PATH, FONT_URL)]
    resources.extend(
        (ASSETS / "emoji" / filename, f"{EMOJI_BASE_URL}/{filename}")
        for filename in EMOJI_FILES
    )
    for path, url in resources:
        if path.is_file() and path.stat().st_size:
            continue
        data = download(url)
        if path.suffix == ".ttf":
            TTFont(io.BytesIO(data)).close()
        else:
            ET.fromstring(data)
        write_atomic(path, data)
        print(f"Cached {path.name} ({len(data):,} bytes)")


def compress_avatar(source: bytes) -> bytes:
    """Use a 2x display-size image, quality 90, maximum WebP encoding effort."""
    with Image.open(io.BytesIO(source)) as original:
        image = ImageOps.exif_transpose(original)
        if profile := image.info.get("icc_profile"):
            image = ImageCms.profileToProfile(
                image, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                ImageCms.createProfile("sRGB"), outputMode="RGBA",
            )
        image = image.convert("RGBA")
        # Flatten transparency against white before sampling colors and encoding.
        background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(background, image).convert("RGB")
        image = ImageOps.fit(
            image, (AVATAR_SIZE * 2, AVATAR_SIZE * 2), method=Image.Resampling.LANCZOS,
        )
        output = io.BytesIO()
        image.save(output, format="WEBP", quality=90, method=6)
        return output.getvalue()


def background_colors(avatar: bytes) -> tuple[str, str]:
    """Find the dominant purple and derive a light-to-dark horizontal gradient."""
    with Image.open(io.BytesIO(avatar)) as image:
        palette = image.convert("RGB").resize((128, 128)).quantize(colors=16)
        colors = sorted(palette.convert("RGB").getcolors(128 * 128), reverse=True)
    purple = (163, 140, 197)
    for _, rgb in colors:
        hue, saturation, value = colorsys.rgb_to_hsv(*(channel / 255 for channel in rgb))
        if 0.68 <= hue <= 0.82 and saturation >= 0.2 and value >= 0.35:
            purple = rgb
            break
    stops = []
    for strength in (0.12, 0.4):
        tint = tuple(round(channel * strength + 255 * (1 - strength)) for channel in purple)
        stops.append("#" + "".join(f"{channel:02X}" for channel in tint))
    return tuple(stops)


@lru_cache(maxsize=None)
def font_face(weight: int) -> tuple[hb.Font, TTFont]:
    """Use true variable weights when available and the supplied static face otherwise."""
    source = TTFont(FONT_PATH)
    outline_font = source
    if "fvar" in source:
        outline_font = instantiateVariableFont(source, {"wght": weight}, inplace=False)
    data = io.BytesIO()
    outline_font.save(data)
    return hb.Font(hb.Face(data.getvalue())), outline_font


def baseline(top: float, line_height: float, size: float, weight: int) -> float:
    """Match the reference's font-metric baseline and half-leading calculation."""
    font, outline_font = font_face(weight)
    metrics = outline_font["hhea"]
    content_height = (metrics.ascent - metrics.descent) * size / font.face.upem
    return top + (line_height - content_height) / 2 + metrics.ascent * size / font.face.upem


def number(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def measure(value: str, size: float, weight: int = 400) -> float:
    """Measure a shaped line without drawing its outlines."""
    font, _ = font_face(weight)
    buffer = hb.Buffer()
    buffer.add_str(value)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"kern": True, "liga": True, "calt": True})
    return sum(position.x_advance for position in buffer.glyph_positions) * size / font.face.upem


def wrap_text(value: str, size: float, max_width: float) -> list[str]:
    """Wrap the original descriptions on word boundaries for narrow cards."""
    lines = []
    current = ""
    for word in value.split():
        candidate = f"{current} {word}" if current else word
        if current and measure(candidate, size) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + [current]


def text(value: str, size: float, weight: int = 400, fill: str = INK) -> tuple[str, float]:
    """Outline text so README images render consistently without installed fonts."""
    font, outline_font = font_face(weight)
    glyphs = outline_font.getGlyphSet()
    order = outline_font.getGlyphOrder()
    buffer = hb.Buffer()
    buffer.add_str(value)
    buffer.guess_segment_properties()
    hb.shape(font, buffer, {"kern": True, "liga": True, "calt": True})
    scale = size / font.face.upem
    paths = []
    advance = 0
    for glyph, position in zip(buffer.glyph_infos, buffer.glyph_positions):
        pen = SVGPathPen(glyphs, ntos=number)
        transform = TransformPen(pen, (
            scale, 0, 0, -scale,
            (advance + position.x_offset) * scale, -position.y_offset * scale,
        ))
        glyphs[order[glyph.codepoint]].draw(transform)
        paths.append(pen.getCommands())
        advance += position.x_advance
    stroke = ""
    if FONT_FAMILY == "chillround" and weight > 400:
        # ChillRoundF supplies Regular only. Match browser-style synthetic bold.
        stroke_width = size * (weight - 400) / 16000
        stroke = (
            f' stroke="{fill}" stroke-width="{stroke_width:g}"'
            ' stroke-linejoin="round" paint-order="stroke"'
        )
    return f'<path fill="{fill}"{stroke} d="{" ".join(paths)}"/>', advance * scale


def svg(width: int, height: int, title: str, description: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">\n'
        f'<title id="title">{escape(title)}</title>\n'
        f'<desc id="description">{escape(description)}</desc>\n{body}\n</svg>\n'
    )


def inline_svg(path: Path, x: float, y: float, size: float) -> str:
    """Inline local vector assets while preserving their original paths and colors."""
    element = ET.parse(path).getroot()
    for attribute in ("style", "class", "preserveAspectRatio", "overflow"):
        element.attrib.pop(attribute, None)
    element.attrib.update(x=f"{x:g}", y=f"{y:g}", width=f"{size:g}", height=f"{size:g}")
    return ET.tostring(element, encoding="unicode")


def card_background(width: int, height: int, colors: tuple[str, str]) -> list[str]:
    left, right = colors
    return [
        '<!-- Emoji graphics by Twitter Twemoji, CC BY 4.0, https://github.com/twitter/twemoji -->',
        '<defs><linearGradient id="background" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="{left}"/><stop offset="100%" stop-color="{right}"/>'
        '</linearGradient></defs>',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" '
        f'rx="{CORNER_RADIUS - 0.5}" fill="url(#background)" stroke="{RULE}" stroke-width="1"/>',
    ]


def avatar_image(avatar: bytes, x: float, y: float, size: int) -> str:
    center_x, center_y = x + size / 2, y + size / 2
    encoded = base64.b64encode(avatar).decode("ascii")
    return (
        f'<defs><clipPath id="avatar"><circle cx="{center_x:g}" cy="{center_y:g}" r="{size / 2:g}"/></clipPath></defs>'
        f'<circle cx="{center_x:g}" cy="{center_y:g}" r="{size / 2 + AVATAR_BORDER:g}" fill="#FFFFFF"/>'
        f'<image x="{x:g}" y="{y:g}" width="{size}" height="{size}" '
        f'preserveAspectRatio="xMidYMid slice" clip-path="url(#avatar)" href="data:image/webp;base64,{encoded}"/>'
    )


def hero(avatar: bytes, colors: tuple[str, str]) -> str:
    body = card_background(WIDTH, HEIGHT, colors)
    # Keep the reference's line-height ratios, 10px and 12px gaps, and centering.
    name_lh, role_lh, intro_lh = NAME_SIZE * 0.85, 20 * 1.3, INTRO_SIZE * 1.75
    content_height = name_lh + 10 + role_lh + 12 + intro_lh * len(INTRO)
    top = (HEIGHT - content_height) / 2
    name, _ = text(NAME, NAME_SIZE, NAME_WEIGHT)
    role, _ = text(ROLE, 20, 500)
    name_y = baseline(top, name_lh, NAME_SIZE, NAME_WEIGHT)
    role_top = top + name_lh + 10
    role_y = baseline(role_top, role_lh, 20, 500)
    body.extend((
        f'<g transform="translate({PADDING - 4} {name_y:g})">{name}</g>',
        f'<g transform="translate({PADDING} {role_y:g})">{role}</g>',
    ))
    intro_top = role_top + role_lh + 12
    text_x = PADDING + INTRO_SIZE + 8
    avatar_x, avatar_y = WIDTH - PADDING - AVATAR_SIZE, (HEIGHT - AVATAR_SIZE) / 2
    available_width = avatar_x - 24 - text_x
    widest_line = max(measure(line, INTRO_SIZE) for line in INTRO)
    # Fit wider font metrics within the desktop text column.
    intro_size = min(INTRO_SIZE, INTRO_SIZE * available_width / widest_line)
    for index, (line, emoji) in enumerate(zip(INTRO, EMOJI_FILES)):
        line_top = intro_top + index * intro_lh
        outline, _ = text(line, intro_size)
        icon_y = line_top + (intro_lh - INTRO_SIZE) / 2
        text_y = baseline(line_top, intro_lh, intro_size, 400)
        body.extend((
            inline_svg(ASSETS / "emoji" / emoji, PADDING, icon_y, INTRO_SIZE),
            f'<g transform="translate({text_x} {text_y:g})">{outline}</g>',
        ))
    body.append(avatar_image(avatar, avatar_x, avatar_y, AVATAR_SIZE))
    description = f'{ROLE}. ' + '. '.join(INTRO)
    return svg(WIDTH, HEIGHT, NAME, description, "\n".join(body))


def mobile_hero(avatar: bytes, colors: tuple[str, str]) -> str:
    """Use a compact header and readable, wrapped description items on phones."""
    width, padding_x, padding_y, avatar_size = MOBILE_WIDTH, 28, 24, 64
    name_size, role_size, intro_size = 32, 15, 17
    name_lh, role_lh = name_size * 0.85, role_size * 1.3
    header_height = max(avatar_size, name_lh + 10 + role_lh)
    header_gap, item_gap = 14, 10
    line_height = intro_size * 1.5
    text_x = padding_x + intro_size + 8
    available_width = width - padding_x - text_x
    descriptions = [wrap_text(line, intro_size, available_width) for line in INTRO]
    intro_top = padding_y + header_height + header_gap
    intro_height = sum(len(lines) * line_height for lines in descriptions) + item_gap * (len(INTRO) - 1)
    height = math.ceil(intro_top + intro_height + padding_y)
    body = card_background(width, height, colors)
    header_top = padding_y + (header_height - name_lh - 10 - role_lh) / 2
    name_y = baseline(header_top, name_lh, name_size, NAME_WEIGHT)
    role_top = header_top + name_lh + 10
    role_y = baseline(role_top, role_lh, role_size, 500)
    name, _ = text(NAME, name_size, NAME_WEIGHT)
    role, role_width = text(ROLE, role_size, 500)
    avatar_x = width - padding_x - avatar_size
    if padding_x + role_width > avatar_x - 12:
        raise ValueError("The role is too wide for the mobile header")
    body.extend((
        f'<g transform="translate({padding_x} {name_y:g})">{name}</g>',
        f'<g transform="translate({padding_x} {role_y:g})">{role}</g>',
        avatar_image(avatar, avatar_x, padding_y, avatar_size),
    ))
    line_top = intro_top
    for lines, emoji in zip(descriptions, EMOJI_FILES):
        icon_y = line_top + (line_height - intro_size) / 2
        body.append(inline_svg(ASSETS / "emoji" / emoji, padding_x, icon_y, intro_size))
        for line in lines:
            outline, _ = text(line, intro_size)
            text_y = baseline(line_top, line_height, intro_size, 400)
            body.append(f'<g transform="translate({text_x} {text_y:g})">{outline}</g>')
            line_top += line_height
        line_top += item_gap
    description = f'{ROLE}. ' + '. '.join(INTRO)
    return svg(width, height, NAME, description, "\n".join(body))


def button(kind: str, label: str, mobile: bool = False, stacked: bool = False) -> str:
    # Full-row canvases center each capsule when the narrow layout wraps.
    height, size, icon_size, padding, icon_gap = BUTTON_HEIGHT, BUTTON_SIZE, BUTTON_ICON_SIZE, 17, 9
    if mobile:
        size, icon_size, padding, icon_gap = 15, 15, 22, 7
    weight = 700
    text_widths = [measure(value, size, weight) for _, value, _ in LINKS]
    pill_width = math.ceil(2 * padding + icon_size + icon_gap + max(text_widths))
    if stacked:
        width = max(240, pill_width)
        pill_x = (width - pill_width) / 2
    else:
        gap = 24 if mobile else BUTTON_GAP
        left_gap = 0 if kind == LINKS[0][0] else gap / 2
        right_gap = 0 if kind == LINKS[-1][0] else gap / 2
        width = int(pill_width + left_gap + right_gap)
        pill_x = left_gap
    top = 8
    outline, text_width = text(label, size, weight)
    icon_x = pill_x + (pill_width - (icon_size + icon_gap + text_width)) / 2
    text_y = top + baseline(0, height, size, weight)
    icon_y = top + (height - icon_size) / 2
    icon = ASSETS / "icons" / ("globe.svg" if kind == "website" else "x.svg")
    body = (
        f'<rect x="{pill_x + 0.5:g}" y="{top + 0.5}" width="{pill_width - 1}" height="{height - 1}" '
        f'rx="{(height - 1) / 2}" fill="#FFFFFF" stroke="{RULE}" stroke-width="1"/>\n'
        + inline_svg(icon, icon_x, icon_y, icon_size) + "\n"
        + f'<g transform="translate({icon_x + icon_size + icon_gap:g} {text_y:g})">{outline}</g>'
    )
    return svg(width, height + top, label, f"Open {label}", body)


def readme() -> str:
    alt = escape(f'{NAME} — {ROLE}. ' + '. '.join(INTRO), quote=True)
    buttons = []
    for kind, label, url in LINKS:
        buttons.append(
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">'
            f'<picture><source media="(max-width: {STACK_BREAKPOINT}px)" srcset="assets/btn-{kind}-stacked.svg">'
            f'<source media="(max-width: {MOBILE_BREAKPOINT}px)" srcset="assets/btn-{kind}-mobile.svg">'
            f'<img src="assets/btn-{kind}.svg" alt="{label}" height="{BUTTON_HEIGHT + 8}"></picture></a>'
        )
    # A zero-width space gives GitHub a wrap point between inline button images.
    return (
        '<!-- Generated with `just generate`. -->\n\n'
        f'<p align="center">\n  <picture><source media="(max-width: {MOBILE_BREAKPOINT}px)" srcset="assets/hero-mobile.svg">'
        f'<img src="assets/hero.svg" alt="{alt}" width="100%"></picture><br>\n'
        '  ' + '&#8203;'.join(buttons) + '\n</p>\n'
    )


def preview_data() -> str:
    """Keep the local HTML preview in sync with the generated README."""
    data = {
        "html": readme().replace('src="assets/', 'src="../assets/').replace('srcset="assets/', 'srcset="../assets/'),
        "breakpoint": MOBILE_BREAKPOINT,
        "stackBreakpoint": STACK_BREAKPOINT,
    }
    return "window.readmePreview = " + json.dumps(data, ensure_ascii=True) + ";\n"


def write_atomic(path: Path, data: bytes) -> None:
    """Replace each complete output atomically, including on repeated runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(data)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def main() -> None:
    global FONT_FAMILY, FONT_PATH, FONT_URL
    parser = argparse.ArgumentParser(description="Generate the profile README and local HTML preview.")
    parser.add_argument("--avatar-url", default=AVATAR_URL, help="Image URL to download on each run.")
    parser.add_argument("--font", choices=FONT_SOURCES, default=DEFAULT_FONT, help="Select the font family. Default is %(default)s.")
    args = parser.parse_args()
    FONT_FAMILY = args.font
    filename, FONT_URL = FONT_SOURCES[FONT_FAMILY]
    FONT_PATH = ASSETS / "fonts" / filename
    font_face.cache_clear()
    ensure_cached_assets()
    avatar = compress_avatar(download(args.avatar_url))
    colors = background_colors(avatar)
    # Finish drawing before replacing any existing outputs.
    outputs = {
        ASSETS / "avatar.webp": avatar,
        ASSETS / "hero.svg": hero(avatar, colors).encode(),
        ASSETS / "hero-mobile.svg": mobile_hero(avatar, colors).encode(),
        ROOT / "README.md": readme().encode(),
        ROOT / "html" / "readme.js": preview_data().encode(),
    }
    for kind, label, _ in LINKS:
        outputs[ASSETS / f"btn-{kind}.svg"] = button(kind, label).encode()
        outputs[ASSETS / f"btn-{kind}-mobile.svg"] = button(kind, label, mobile=True).encode()
        outputs[ASSETS / f"btn-{kind}-stacked.svg"] = button(kind, label, mobile=True, stacked=True).encode()
    for path, data in outputs.items():
        write_atomic(path, data)
        print(f"{path.relative_to(ROOT)} ({len(data):,} bytes)")
    print(f"Avatar quality: 90; background: {colors[0]} to {colors[1]}")


if __name__ == "__main__":
    main()
