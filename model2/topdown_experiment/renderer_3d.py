"""추가 API 없이 실제 3D 도형과 직교 카메라로 방을 렌더링한다."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
from matplotlib import font_manager
from mpl_toolkits.mplot3d.art3d import Poly3DCollection


INK = "#332d28"


def _font_path() -> str | None:
    candidate = Path("C:/Windows/Fonts/malgunbd.ttf")
    return str(candidate) if candidate.exists() else None


def _valid_color(value: Any, fallback: str) -> str:
    text = str(value or "")
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    return fallback


def _shade(color: str, factor: float) -> str:
    channels = [int(color[index : index + 2], 16) for index in (1, 3, 5)]
    values = [max(0, min(255, round(channel * factor))) for channel in channels]
    return "#" + "".join(f"{channel:02x}" for channel in values)


def _rotate(x: float, y: float, angle: float) -> tuple[float, float]:
    radians = math.radians(angle)
    cosine, sine = math.cos(radians), math.sin(radians)
    return x * cosine - y * sine, x * sine + y * cosine


def _box_vertices(
    cx: float,
    cy: float,
    width: float,
    depth: float,
    z: float,
    height: float,
    rotation: float = 0,
):
    bottom = []
    top = []
    for local_x, local_y in (
        (-width / 2, -depth / 2),
        (width / 2, -depth / 2),
        (width / 2, depth / 2),
        (-width / 2, depth / 2),
    ):
        dx, dy = _rotate(local_x, local_y, rotation)
        bottom.append((cx + dx, cy + dy, z))
        top.append((cx + dx, cy + dy, z + height))
    return bottom, top


def _cuboid(
    ax,
    cx: float,
    cy: float,
    width: float,
    depth: float,
    z: float,
    height: float,
    color: str,
    rotation: float = 0,
    edge: str = INK,
    linewidth: float = 0.8,
) -> None:
    bottom, top = _box_vertices(cx, cy, width, depth, z, height, rotation)
    faces = [
        top,
        [bottom[0], bottom[1], top[1], top[0]],
        [bottom[1], bottom[2], top[2], top[1]],
        [bottom[2], bottom[3], top[3], top[2]],
        [bottom[3], bottom[0], top[0], top[3]],
    ]
    collection = Poly3DCollection(
        faces,
        facecolors=[
            _shade(color, 1.12),
            _shade(color, 0.72),
            _shade(color, 0.82),
            _shade(color, 0.62),
            _shade(color, 0.9),
        ],
        edgecolors=edge,
        linewidths=linewidth,
    )
    ax.add_collection3d(collection)


def _cylinder(
    ax,
    cx: float,
    cy: float,
    radius: float,
    z: float,
    height: float,
    color: str,
    segments: int = 20,
) -> None:
    angles = [2 * math.pi * index / segments for index in range(segments)]
    bottom = [(cx + radius * math.cos(a), cy + radius * math.sin(a), z) for a in angles]
    top = [(x, y, z + height) for x, y, _ in bottom]
    faces = [top]
    for index in range(segments):
        next_index = (index + 1) % segments
        faces.append([bottom[index], bottom[next_index], top[next_index], top[index]])
    colors = [_shade(color, 1.1)] + [
        _shade(color, 0.65 + 0.25 * (index / segments))
        for index in range(segments)
    ]
    ax.add_collection3d(
        Poly3DCollection(faces, facecolors=colors, edgecolors=INK, linewidths=0.45)
    )


def _local_point(
    cx: float,
    cy: float,
    local_x: float,
    local_y: float,
    rotation: float,
) -> tuple[float, float]:
    dx, dy = _rotate(local_x, local_y, rotation)
    return cx + dx, cy + dy


def _bed(ax, obj: dict[str, Any]) -> float:
    cx, cy = float(obj["x"]), float(obj["y"])
    width, depth = float(obj["width"]), float(obj["depth"])
    rotation = float(obj.get("rotation_deg", 0))
    wood = "#79502f"
    fabric = _valid_color(obj.get("color"), "#b84f50")
    _cuboid(ax, cx, cy, width, depth, 0.0, 0.08, wood, rotation)
    _cuboid(ax, cx, cy, width * 0.94, depth * 0.93, 0.08, 0.09, "#eee6d6", rotation)
    # 이불은 침대 발치 64%
    blanket_cx, blanket_cy = _local_point(cx, cy, 0, depth * 0.15, rotation)
    _cuboid(
        ax,
        blanket_cx,
        blanket_cy,
        width * 0.91,
        depth * 0.62,
        0.17,
        0.025,
        fabric,
        rotation,
    )
    # 베개 두 개
    for offset_x in (-width * 0.24, width * 0.24):
        pillow_x, pillow_y = _local_point(cx, cy, offset_x, -depth * 0.33, rotation)
        _cuboid(
            ax,
            pillow_x,
            pillow_y,
            width * 0.4,
            depth * 0.18,
            0.17,
            0.055,
            _shade(fabric, 1.15),
            rotation,
        )
    # 헤드보드
    head_x, head_y = _local_point(cx, cy, 0, -depth * 0.48, rotation)
    _cuboid(ax, head_x, head_y, width, depth * 0.06, 0, 0.28, wood, rotation)
    # 체크 패턴을 이불의 실제 윗면에 그린다.
    z = 0.198
    for fraction in (-0.35, -0.12, 0.12, 0.35):
        x1, y1 = _local_point(cx, cy, width * fraction, -depth * 0.15, rotation)
        x2, y2 = _local_point(cx, cy, width * fraction, depth * 0.45, rotation)
        ax.plot((x1, x2), (y1, y2), (z, z), color="#f1ddd2", linewidth=1.5)
    for fraction in (-0.08, 0.12, 0.31):
        x1, y1 = _local_point(cx, cy, -width * 0.44, depth * fraction, rotation)
        x2, y2 = _local_point(cx, cy, width * 0.44, depth * fraction, rotation)
        ax.plot((x1, x2), (y1, y2), (z, z), color="#f1ddd2", linewidth=1.5)
    return 0.3


def _cabinet(ax, obj: dict[str, Any]) -> float:
    cx, cy = float(obj["x"]), float(obj["y"])
    width, depth = float(obj["width"]), float(obj["depth"])
    rotation = float(obj.get("rotation_deg", 0))
    color = _valid_color(obj.get("color"), "#8a5e3c")
    height = 0.24
    _cuboid(ax, cx, cy, width, depth, 0, height, color, rotation)
    # 상판과 손잡이 행
    _cuboid(ax, cx, cy, width * 1.04, depth * 1.04, height, 0.025, _shade(color, 1.13), rotation)
    for row in (-0.3, 0.0, 0.3):
        for column in (-0.28, 0.0, 0.28):
            x, y = _local_point(cx, cy, width * column, depth * row, rotation)
            _cylinder(ax, x, y, min(width, depth) * 0.018, height + 0.026, 0.018, "#d8b275", 10)
    return height + 0.07


def _desk(ax, obj: dict[str, Any]) -> float:
    cx, cy = float(obj["x"]), float(obj["y"])
    width, depth = float(obj["width"]), float(obj["depth"])
    rotation = float(obj.get("rotation_deg", 0))
    color = _valid_color(obj.get("color"), "#e7e2d7")
    top_height = 0.22
    # 네 다리
    for local_x in (-width * 0.42, width * 0.42):
        for local_y in (-depth * 0.38, depth * 0.38):
            x, y = _local_point(cx, cy, local_x, local_y, rotation)
            _cuboid(ax, x, y, width * 0.055, depth * 0.055, 0, top_height, _shade(color, 0.75), rotation)
    _cuboid(ax, cx, cy, width, depth, top_height, 0.035, color, rotation)
    # 책과 컵
    for index, book_color in enumerate(("#b45c55", "#d7b85c", "#6f8e83")):
        x, y = _local_point(cx, cy, width * (0.12 + index * 0.08), -depth * 0.2, rotation)
        _cuboid(ax, x, y, width * 0.055, depth * 0.3, top_height + 0.035, 0.018, book_color, rotation)
    cup_x, cup_y = _local_point(cx, cy, width * 0.3, depth * 0.22, rotation)
    _cylinder(ax, cup_x, cup_y, min(width, depth) * 0.06, top_height + 0.035, 0.06, "#f4efe4")
    return top_height + 0.11


def _chair(ax, obj: dict[str, Any]) -> float:
    cx, cy = float(obj["x"]), float(obj["y"])
    width, depth = float(obj["width"]), float(obj["depth"])
    rotation = float(obj.get("rotation_deg", 0))
    wood = _valid_color(obj.get("color"), "#b88758")
    seat_z = 0.14
    for local_x in (-width * 0.34, width * 0.34):
        for local_y in (-depth * 0.3, depth * 0.3):
            x, y = _local_point(cx, cy, local_x, local_y, rotation)
            _cuboid(ax, x, y, width * 0.055, depth * 0.055, 0, seat_z, wood, rotation)
    _cuboid(ax, cx, cy, width * 0.76, depth * 0.68, seat_z, 0.045, "#aeb9ae", rotation)
    back_x, back_y = _local_point(cx, cy, 0, -depth * 0.38, rotation)
    _cuboid(ax, back_x, back_y, width * 0.78, depth * 0.07, seat_z, 0.2, wood, rotation)
    return 0.37


def _sofa(ax, obj: dict[str, Any]) -> float:
    cx, cy = float(obj["x"]), float(obj["y"])
    width, depth = float(obj["width"]), float(obj["depth"])
    rotation = float(obj.get("rotation_deg", 0))
    color = _valid_color(obj.get("color"), "#9a6e56")
    _cuboid(ax, cx, cy, width, depth, 0, 0.11, _shade(color, 0.78), rotation)
    # 좌석 쿠션
    count = 2 if max(width, depth) > min(width, depth) * 1.25 else 1
    for index in range(count):
        local_y = (index - (count - 1) / 2) * depth * 0.44 if depth > width else 0
        local_x = (index - (count - 1) / 2) * width * 0.44 if width >= depth else 0
        x, y = _local_point(cx, cy, local_x, local_y, rotation)
        cushion_width = width * (0.8 if depth > width else 0.42)
        cushion_depth = depth * (0.42 if depth > width else 0.8)
        _cuboid(ax, x, y, cushion_width, cushion_depth, 0.11, 0.08, _shade(color, 1.08), rotation)
    return 0.23


def _rug(ax, obj: dict[str, Any]) -> float:
    cx, cy = float(obj["x"]), float(obj["y"])
    width, depth = float(obj["width"]), float(obj["depth"])
    color = _valid_color(obj.get("color"), "#cbb08b")
    _cuboid(ax, cx, cy, width, depth, 0.002, 0.008, color, float(obj.get("rotation_deg", 0)), linewidth=0.5)
    return 0.012


def _plant(ax, obj: dict[str, Any]) -> float:
    cx, cy = float(obj["x"]), float(obj["y"])
    radius = min(float(obj["width"]), float(obj["depth"])) * 0.22
    _cylinder(ax, cx, cy, radius, 0, 0.13, "#a66d46")
    for index in range(10):
        angle = 2 * math.pi * index / 10
        length = radius * (1.8 + (index % 3) * 0.4)
        end_x = cx + math.cos(angle) * length
        end_y = cy + math.sin(angle) * length
        ax.plot((cx, end_x), (cy, end_y), (0.13, 0.28), color="#466b45", linewidth=3)
        ax.scatter([end_x], [end_y], [0.28], s=45, color="#789b69", edgecolors=INK, linewidths=0.4)
    return 0.32


def _generic(ax, obj: dict[str, Any]) -> float:
    category = str(obj.get("category") or "")
    height = {
        "table": 0.17,
        "electronics": 0.12,
        "appliance": 0.18,
        "curtain": 0.04,
        "lamp": 0.18,
        "decor": 0.06,
    }.get(category, 0.12)
    _cuboid(
        ax,
        float(obj["x"]),
        float(obj["y"]),
        float(obj["width"]),
        float(obj["depth"]),
        0,
        height,
        _valid_color(obj.get("color"), "#c3b8a4"),
        float(obj.get("rotation_deg", 0)),
    )
    return height + 0.03


def render_room_3d(layout: dict[str, Any], output_path: Path) -> None:
    """가구를 실제 3D 면으로 만들고 직교 카메라로 PNG를 렌더링한다."""
    room = layout.get("room") or {}
    aspect = max(0.35, min(2.5, float(room.get("aspect_ratio_width_to_depth", 0.75))))
    figure = plt.figure(figsize=(9, 12), dpi=160, facecolor="#d8d4ca")
    ax = figure.add_subplot(111, projection="3d")
    ax.set_proj_type("ortho")

    floor = _valid_color(room.get("floor_color"), "#6b4935")
    _cuboid(ax, 0.5, 0.5, 1.0, 1.0, -0.025, 0.025, floor, linewidth=1.2)
    # 실제 바닥 위에 원목 판재 선을 놓는다.
    for y in [index / 18 for index in range(1, 18)]:
        ax.plot((0, 1), (y, y), (0.002, 0.002), color=_shade(floor, 0.72), linewidth=0.45)
    for row in range(18):
        offset = 0.0 if row % 2 == 0 else 0.1
        for x in [offset + index * 0.2 for index in range(6)]:
            if 0 < x < 1:
                y1, y2 = row / 18, (row + 1) / 18
                ax.plot((x, x), (y1, y2), (0.002, 0.002), color=_shade(floor, 0.75), linewidth=0.4)

    objects = list(layout.get("objects") or [])
    objects.sort(key=lambda item: 0 if item.get("category") == "rug" else 1)
    label_positions = []
    for obj in objects:
        category = str(obj.get("category") or "")
        if category == "bed":
            label_z = _bed(ax, obj)
        elif category in {"cabinet", "dresser", "nightstand"}:
            label_z = _cabinet(ax, obj)
        elif category == "desk":
            label_z = _desk(ax, obj)
        elif category == "chair":
            label_z = _chair(ax, obj)
        elif category == "sofa":
            label_z = _sofa(ax, obj)
        elif category == "rug":
            label_z = _rug(ax, obj)
        elif category == "plant":
            label_z = _plant(ax, obj)
        else:
            label_z = _generic(ax, obj)
        if category in {"bed", "desk", "chair", "cabinet", "dresser", "nightstand", "sofa", "plant"}:
            label_positions.append(
                (
                    float(obj["x"]),
                    float(obj["y"]),
                    label_z,
                    str(obj.get("label_ko") or category),
                )
            )

    font_properties = (
        font_manager.FontProperties(fname=_font_path(), size=11, weight="bold")
        if _font_path()
        else None
    )
    for x, y, z, label in label_positions:
        text = ax.text(
            x,
            y,
            z + 0.025,
            label,
            ha="center",
            va="center",
            color="#fffdf8",
            fontproperties=font_properties,
            zorder=100,
        )
        text.set_path_effects(
            [path_effects.withStroke(linewidth=3.5, foreground="#302c28")]
        )

    # 첨부 예시처럼 거의 수직인 탑뷰를 유지하면서 상판과 측면이 조금만 보이게 한다.
    ax.view_init(elev=82, azim=-90)
    ax.set_xlim(0, 1)
    ax.set_ylim(1, 0)
    ax.set_zlim(0, 0.48)
    ax.set_box_aspect((aspect, 1.0, 0.3))
    ax.set_axis_off()
    figure.subplots_adjust(left=0, right=1, bottom=0, top=1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=160, bbox_inches="tight", pad_inches=0.08, facecolor=figure.get_facecolor())
    plt.close(figure)
