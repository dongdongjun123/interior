"""Pillow만으로 탑뷰 인테리어 일러스트를 그리는 무료 렌더러."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


CANVAS = 1200
MARGIN = 45
INK = "#302c28"
WALL = "#eee9df"
LABEL_FILL = "#fffdf8"
LABEL_STROKE = "#302c28"


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ("malgunbd.ttf", "malgun.ttf") if bold else ("malgun.ttf", "arial.ttf")
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _hex_color(value: Any, fallback: str) -> str:
    text = str(value or "")
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    return fallback


def _mix(color: str, target: str, amount: float) -> str:
    source_rgb = tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))
    target_rgb = tuple(int(target[index : index + 2], 16) for index in (1, 3, 5))
    mixed = tuple(
        round(source + (destination - source) * amount)
        for source, destination in zip(source_rgb, target_rgb)
    )
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


def _draw_wood_floor(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    base: str,
) -> None:
    left, top, right, bottom = box
    draw.rectangle(box, fill=base)
    plank_height = max(24, (bottom - top) // 25)
    light = _mix(base, "#ffffff", 0.12)
    dark = _mix(base, "#000000", 0.16)
    for row, y in enumerate(range(top, bottom, plank_height)):
        draw.line((left, y, right, y), fill=dark, width=2)
        offset = 0 if row % 2 == 0 else 90
        plank_width = max(140, (right - left) // 5)
        for x in range(left + offset, right, plank_width):
            draw.line((x, y, x, min(y + plank_height, bottom)), fill=dark, width=2)
        draw.line(
            (left, min(y + 4, bottom), right, min(y + 4, bottom)),
            fill=light,
            width=1,
        )


def _rounded(draw: ImageDraw.ImageDraw, box, fill, radius=22, width=4) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=INK, width=width)
    left, top, right, bottom = box
    highlight = _mix(fill, "#ffffff", 0.3)
    shadow = _mix(fill, "#000000", 0.24)
    draw.arc(
        (left + 3, top + 3, right - 3, bottom - 3),
        190,
        350,
        fill=highlight,
        width=max(2, width // 2),
    )
    draw.arc(
        (left + 3, top + 3, right - 3, bottom - 3),
        10,
        170,
        fill=shadow,
        width=max(2, width // 2),
    )


def _plaid(draw: ImageDraw.ImageDraw, box, base: str) -> None:
    left, top, right, bottom = box
    draw.rectangle(box, fill=_mix(base, "#ffffff", 0.52))
    red = _mix(base, "#8e2527", 0.38)
    blue = "#5b7181"
    spacing = max(18, min(right - left, bottom - top) // 7)
    for x in range(left, right + 1, spacing):
        draw.rectangle((x, top, min(x + spacing // 3, right), bottom), fill=red)
        draw.line((x + spacing // 2, top, x + spacing // 2, bottom), fill=blue, width=2)
    for y in range(top, bottom + 1, spacing):
        draw.rectangle((left, y, right, min(y + spacing // 3, bottom)), fill=red)
        draw.line((left, y + spacing // 2, right, y + spacing // 2), fill=blue, width=2)


def _bed(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    wood = "#8c5a32"
    fabric = _hex_color(obj.get("color"), "#b84f50")
    _rounded(draw, (3, 3, width - 4, height - 4), wood, radius=22, width=5)
    # 두꺼운 헤드보드가 만드는 높이감
    draw.rounded_rectangle(
        (8, 8, width - 9, max(18, int(height * 0.09))),
        radius=8,
        fill=_mix(wood, "#000000", 0.18),
        outline=INK,
        width=3,
    )
    inset = max(10, width // 25)
    mattress = (inset, inset, width - inset, height - inset)
    _rounded(draw, mattress, "#f2ead9", radius=20, width=4)
    draw.line(
        (inset + 5, height - inset - 7, width - inset - 5, height - inset - 7),
        fill="#aa9276",
        width=max(3, height // 55),
    )
    blanket_top = int(height * 0.34)
    blanket_box = (inset + 3, blanket_top, width - inset - 3, height - inset - 3)
    _plaid(draw, blanket_box, fabric)
    draw.rounded_rectangle(blanket_box, radius=14, outline=INK, width=3)
    pillow_gap = max(5, width // 35)
    pillow_width = (width - 2 * inset - 3 * pillow_gap) // 2
    pillow_height = max(24, int(height * 0.22))
    for index in range(2):
        left = inset + pillow_gap + index * (pillow_width + pillow_gap)
        box = (left, inset + pillow_gap, left + pillow_width, inset + pillow_gap + pillow_height)
        _plaid(draw, box, fabric)
        draw.rounded_rectangle(box, radius=12, outline=INK, width=3)
        # 베개 중앙의 살짝 들어간 부분
        draw.arc(
            (left + 8, inset + pillow_gap + 5, left + pillow_width - 8, inset + pillow_gap + pillow_height - 5),
            20,
            160,
            fill=_mix(fabric, "#000000", 0.18),
            width=2,
        )
    return image


def _rug(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    base = _hex_color(obj.get("color"), "#cbb08b")
    pattern = str(obj.get("pattern") or "").lower()
    is_round = "circle" in pattern or abs(width - height) < min(width, height) * 0.16
    box = (4, 4, width - 5, height - 5)
    if is_round:
        draw.ellipse(box, fill=base, outline=INK, width=4)
        for inset in range(12, min(width, height) // 2, 12):
            draw.ellipse(
                (inset, inset, width - inset, height - inset),
                outline=_mix(base, "#5a4432", 0.25),
                width=2,
            )
    else:
        draw.rounded_rectangle(box, radius=8, fill=base, outline=INK, width=4)
        for y in range(13, height - 8, 11):
            draw.line(
                (10, y, width - 10, y),
                fill=_mix(base, "#6c5540", 0.23),
                width=2,
            )
        for x in range(10, width - 8, 17):
            draw.line(
                (x, 9, x, height - 9),
                fill=_mix(base, "#ffffff", 0.13),
                width=1,
            )
        # 짧은 술 장식
        for x in range(12, width - 10, 12):
            draw.line((x, 2, x, 8), fill=_mix(base, "#000000", 0.2), width=2)
            draw.line((x, height - 8, x, height - 2), fill=_mix(base, "#000000", 0.2), width=2)
    return image


def _desk(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    base = _hex_color(obj.get("color"), "#eee9dc")
    _rounded(draw, (3, 3, width - 4, height - 4), base, radius=10, width=5)
    draw.line((8, 9, width - 9, 9), fill="#ffffff", width=max(2, height // 35))
    draw.line((width - 9, 10, width - 9, height - 10), fill="#a49b89", width=3)
    drawer_width = max(25, width // 5)
    draw.line((drawer_width, 6, drawer_width, height - 6), fill=INK, width=3)
    for y in (height // 3, 2 * height // 3):
        draw.line((5, y, drawer_width, y), fill=INK, width=2)
    for y in (height // 6, height // 2, 5 * height // 6):
        draw.ellipse(
            (drawer_width // 2 - 3, y - 3, drawer_width // 2 + 3, y + 3),
            fill="#9b744c",
        )
    # 책과 컵
    for index, color in enumerate(("#b85b55", "#e0c66b", "#6e8e84")):
        x = int(width * 0.52) + index * max(7, width // 28)
        draw.rectangle((x, 12, x + max(6, width // 35), int(height * 0.44)), fill=color, outline=INK)
    cup_x, cup_y = int(width * 0.78), int(height * 0.68)
    radius = max(6, min(width, height) // 13)
    draw.ellipse((cup_x - radius, cup_y - radius, cup_x + radius, cup_y + radius), fill="#f8f4e9", outline=INK, width=2)
    draw.ellipse(
        (cup_x - radius + 4, cup_y - radius + 4, cup_x + radius - 4, cup_y + radius - 4),
        fill="#856047",
    )
    return image


def _cabinet(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    base = _hex_color(obj.get("color"), "#8a5e3c")
    _rounded(draw, (3, 3, width - 4, height - 4), base, radius=8, width=5)
    # 상판의 밝은 앞 모서리와 뒤쪽 음영
    draw.rounded_rectangle(
        (7, 7, width - 8, max(15, int(height * 0.12))),
        radius=5,
        fill=_mix(base, "#ffffff", 0.16),
        outline=INK,
        width=2,
    )
    rows, columns = (4, 3) if height >= width else (3, 4)
    cell_width = (width - 14) / columns
    cell_height = (height - 14) / rows
    for row in range(rows):
        for column in range(columns):
            left = 7 + column * cell_width
            top = 7 + row * cell_height
            box = (left, top, left + cell_width - 3, top + cell_height - 3)
            draw.rounded_rectangle(box, radius=3, fill=_mix(base, "#ffffff", 0.08), outline=INK, width=2)
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill="#d6b078")
    return image


def _chair(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    wood = _hex_color(obj.get("color"), "#bf8d59")
    pad = max(5, min(width, height) // 12)
    draw.arc((pad, 1, width - pad, height * 0.72), 180, 360, fill=INK, width=max(4, width // 25))
    draw.arc((pad + 5, 6, width - pad - 5, height * 0.7), 180, 360, fill=wood, width=max(5, width // 20))
    seat = (int(width * 0.23), int(height * 0.38), int(width * 0.77), int(height * 0.78))
    draw.rounded_rectangle(seat, radius=12, fill="#aeb9ae", outline=INK, width=4)
    draw.arc(
        (seat[0] + 5, seat[1] + 5, seat[2] - 5, seat[3] - 5),
        190,
        345,
        fill="#e3e9e3",
        width=3,
    )
    for x in (int(width * 0.27), int(width * 0.73)):
        draw.line((x, int(height * 0.72), x, height - 3), fill=INK, width=5)
        draw.line((x + 3, int(height * 0.72), x + 3, height - 3), fill=wood, width=3)
    return image


def _lamp(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx, cy = width // 2, height // 2
    radius = max(8, min(width, height) // 3)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill="#f2d77d", outline=INK, width=4)
    for angle in range(0, 360, 45):
        dx, dy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        draw.line((cx, cy, cx + dx * radius, cy + dy * radius), fill="#9a743a", width=2)
    return image


def _plant(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx, cy = width // 2, height // 2
    for index in range(12):
        angle = math.radians(index * 137.5)
        length = min(width, height) * (0.25 + (index % 3) * 0.05)
        ex, ey = cx + math.cos(angle) * length, cy + math.sin(angle) * length
        draw.line((cx, cy, ex, ey), fill="#476442", width=3)
        leaf = max(5, min(width, height) // 12)
        draw.ellipse((ex - leaf, ey - leaf // 2, ex + leaf, ey + leaf // 2), fill="#78966b", outline=INK, width=1)
    pot = max(8, min(width, height) // 6)
    draw.ellipse((cx - pot, cy - pot, cx + pot, cy + pot), fill="#a96f48", outline=INK, width=3)
    return image


def _sofa(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    base = _hex_color(obj.get("color"), "#8d4e32")
    _rounded(draw, (3, 3, width - 4, height - 4), base, radius=18, width=5)
    inset = max(7, min(width, height) // 10)
    draw.rounded_rectangle(
        (inset, inset, width - inset, height - inset),
        radius=14,
        fill=_mix(base, "#ffffff", 0.12),
        outline=INK,
        width=3,
    )
    if height > width:
        draw.line((inset, height // 2, width - inset, height // 2), fill=INK, width=3)
        for cy in (height * 0.3, height * 0.7):
            draw.arc(
                (inset + 5, cy - height * 0.16, width - inset - 5, cy + height * 0.16),
                190,
                350,
                fill=_mix(base, "#ffffff", 0.35),
                width=3,
            )
    else:
        draw.line((width // 2, inset, width // 2, height - inset), fill=INK, width=3)
        for cx in (width * 0.3, width * 0.7):
            draw.arc(
                (cx - width * 0.16, inset + 5, cx + width * 0.16, height - inset - 5),
                100,
                260,
                fill=_mix(base, "#ffffff", 0.35),
                width=3,
            )
    return image


def _decor(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    label = str(obj.get("label_ko") or "")
    base = _hex_color(obj.get("color"), "#8b6847")
    if "시계" in label:
        radius = max(7, min(width, height) // 2 - 3)
        cx, cy = width // 2, height // 2
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill="#fffbed", outline=base, width=5)
        for index in range(12):
            angle = math.radians(index * 30 - 90)
            x = cx + math.cos(angle) * radius * 0.75
            y = cy + math.sin(angle) * radius * 0.75
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=INK)
        draw.line((cx, cy, cx, cy - radius * 0.55), fill=INK, width=3)
        draw.line((cx, cy, cx + radius * 0.42, cy), fill="#b43c3c", width=3)
    else:
        draw.rounded_rectangle((2, 2, width - 3, height - 3), radius=4, fill=base, outline=INK, width=4)
        draw.rectangle((8, 8, width - 9, height - 9), fill="#d7c17d")
        draw.polygon(
            ((9, height - 9), (width * 0.38, height * 0.47), (width * 0.55, height * 0.68), (width - 9, height * 0.28), (width - 9, height - 9)),
            fill="#71855a",
        )
    return image


def _generic(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    _rounded(
        draw,
        (3, 3, width - 4, height - 4),
        _hex_color(obj.get("color"), "#c2b7a3"),
        radius=10,
        width=4,
    )
    return image


def _paste_flat(
    canvas: Image.Image,
    sprite: Image.Image,
    position: tuple[int, int],
) -> None:
    """러그처럼 바닥에 붙은 물체를 얕은 접촉 음영과 함께 붙인다."""
    alpha = sprite.getchannel("A")
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(radius=3))
    shadow_alpha = shadow_alpha.point(lambda value: value * 30 // 255)
    shadow = Image.new("RGBA", sprite.size, (31, 25, 20, 0))
    shadow.putalpha(shadow_alpha)
    canvas.paste(shadow, (position[0] + 2, position[1] + 3), shadow)
    canvas.paste(sprite, position, sprite)


def _paste_volume(
    canvas: Image.Image,
    sprite: Image.Image,
    position: tuple[int, int],
    *,
    height: int,
    direction: tuple[int, int] = (1, 1),
) -> None:
    """윗면 이미지를 여러 단계로 압출해 실제 옆면과 높이를 만든다.

    흐린 그림자가 아니라 원본 색을 어둡게 한 불투명 측면이므로 사물 자체가
    바닥 위로 올라온 볼륨으로 보인다.
    """
    height = max(3, height)
    side = ImageEnhance.Brightness(sprite).enhance(0.48)
    side_alpha = sprite.getchannel("A").point(lambda value: 255 if value > 24 else 0)
    side.putalpha(side_alpha)

    # 아래에서 위 순서로 단단한 측면 층을 쌓는다.
    for step in range(height, 0, -1):
        offset_x = direction[0] * step
        offset_y = direction[1] * step
        canvas.paste(
            side,
            (position[0] + offset_x, position[1] + offset_y),
            side,
        )

    # 측면의 아래 모서리를 한 번 더 어둡게 해 두께 경계를 명확히 한다.
    bottom = ImageEnhance.Brightness(sprite).enhance(0.3)
    bottom.putalpha(side_alpha)
    canvas.paste(
        bottom,
        (
            position[0] + direction[0] * height,
            position[1] + direction[1] * height,
        ),
        bottom,
    )
    canvas.paste(sprite, position, sprite)


def _object_image(size: tuple[int, int], obj: dict[str, Any]) -> Image.Image:
    category = str(obj.get("category") or "").lower()
    if category == "bed":
        return _bed(size, obj)
    if category == "rug":
        return _rug(size, obj)
    if category == "desk":
        return _desk(size, obj)
    if category in {"cabinet", "dresser", "nightstand"}:
        return _cabinet(size, obj)
    if category == "chair":
        return _chair(size, obj)
    if category == "lamp":
        return _lamp(size, obj)
    if category == "plant":
        return _plant(size, obj)
    if category == "sofa":
        return _sofa(size, obj)
    if category == "decor":
        return _decor(size, obj)
    return _generic(size, obj)


def _label(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    text: str,
    room_box: tuple[int, int, int, int],
) -> None:
    font = _font(28, bold=True)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=4)
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    left = max(room_box[0] + 5, min(position[0] - width / 2, room_box[2] - width - 5))
    top = max(room_box[1] + 5, min(position[1] - height / 2, room_box[3] - height - 5))
    draw.text(
        (left, top),
        text,
        font=font,
        fill=LABEL_FILL,
        stroke_fill=LABEL_STROKE,
        stroke_width=5,
    )


def render_illustration(layout: dict[str, Any], output_path: Path) -> None:
    """정규화된 layout JSON을 완성형 탑뷰 일러스트 PNG로 렌더한다."""
    room = layout.get("room") or {}
    aspect = max(0.35, min(2.5, float(room.get("aspect_ratio_width_to_depth", 0.75))))
    available = CANVAS - 2 * MARGIN
    if aspect >= 1:
        room_width, room_depth = available, available / aspect
    else:
        room_width, room_depth = available * aspect, available
    left = round((CANVAS - room_width) / 2)
    top = round((CANVAS - room_depth) / 2)
    right, bottom = round(left + room_width), round(top + room_depth)
    room_box = (left, top, right, bottom)

    image = Image.new("RGB", (CANVAS, CANVAS), "#d8d4ca")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (left - 13, top - 13, right + 13, bottom + 13),
        radius=8,
        fill=WALL,
        outline=INK,
        width=5,
    )
    floor = _hex_color(room.get("floor_color"), "#6b4935")
    _draw_wood_floor(draw, room_box, floor)
    # 벽 아래쪽의 부드러운 내부 그림자
    room_shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(room_shadow)
    shadow_draw.rectangle(room_box, outline=(24, 19, 15, 115), width=24)
    room_shadow = room_shadow.filter(ImageFilter.GaussianBlur(radius=10))
    image.paste(room_shadow, (0, 0), room_shadow)

    objects = list(layout.get("objects") or [])
    # 러그처럼 바닥에 놓이는 물체를 먼저 그린다.
    objects.sort(key=lambda item: 0 if item.get("category") == "rug" else 1)
    label_queue: list[tuple[float, float, str]] = []

    for obj in objects:
        category = str(obj.get("category") or "")
        width = max(26, round(float(obj.get("width", 0.12)) * room_width))
        depth = max(26, round(float(obj.get("depth", 0.12)) * room_depth))
        center_x = left + float(obj.get("x", 0.5)) * room_width
        center_y = top + float(obj.get("y", 0.5)) * room_depth
        sprite = _object_image((width, depth), obj)
        rotation = -float(obj.get("rotation_deg", 0))
        if rotation:
            sprite = sprite.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
        paste_x = round(center_x - sprite.width / 2)
        paste_y = round(center_y - sprite.height / 2)
        if category == "rug":
            _paste_flat(image, sprite, (paste_x, paste_y))
        else:
            category_height = {
                "bed": 14,
                "desk": 12,
                "chair": 10,
                "cabinet": 17,
                "dresser": 17,
                "nightstand": 15,
                "sofa": 14,
                "table": 10,
                "plant": 9,
                "lamp": 7,
                "decor": 5,
            }.get(category, 9)
            _paste_volume(
                image,
                sprite,
                (paste_x, paste_y),
                height=category_height,
            )

        # 작은 벽 장식은 자체 모양만으로 충분하고, 주요 항목 위주로 라벨링한다.
        should_label = category in {
            "bed",
            "desk",
            "chair",
            "cabinet",
            "dresser",
            "nightstand",
            "sofa",
            "plant",
        }
        # 작은 원형 러그처럼 다른 가구 아래에 놓인 항목은 라벨 중복을 피한다.
        if category == "rug":
            should_label = (
                float(obj.get("width", 0)) * float(obj.get("depth", 0)) >= 0.08
            )
        if should_label:
            label_queue.append((center_x, center_y, str(obj.get("label_ko") or category)))

    draw = ImageDraw.Draw(image)
    draw.rectangle(room_box, outline=INK, width=7)
    for center_x, center_y, text in label_queue:
        _label(draw, (center_x, center_y), text, room_box)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG")
