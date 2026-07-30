"""관계·벽 고정·충돌 규칙으로 Gemini의 대략적인 좌표를 보정한다."""
from __future__ import annotations

import math
from typing import Any


FLOOR_LAYERS = {"rug"}
NON_FLOOR_OBJECTS = {"decor", "lamp", "door", "window"}
ALLOWED_RELATIONS = {
    "left_of",
    "right_of",
    "above",
    "below",
    "near",
    "aligned_x",
    "aligned_y",
}
DEFAULT_GAP = 0.018


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _bounds(obj: dict[str, Any], x: float | None = None, y: float | None = None):
    center_x = float(obj["x"] if x is None else x)
    center_y = float(obj["y"] if y is None else y)
    width = float(obj["width"])
    depth = float(obj["depth"])
    angle = math.radians(float(obj.get("rotation_deg", 0)))
    # 회전된 사각형의 축 정렬 외접 영역. 충돌 검사는 의도적으로 보수적이다.
    box_width = abs(width * math.cos(angle)) + abs(depth * math.sin(angle))
    box_depth = abs(width * math.sin(angle)) + abs(depth * math.cos(angle))
    return (
        center_x - box_width / 2,
        center_y - box_depth / 2,
        center_x + box_width / 2,
        center_y + box_depth / 2,
    )


def _overlap_area(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    depth = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return width * depth


def _can_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    first_category = str(first.get("category") or "")
    second_category = str(second.get("category") or "")
    if first_category in FLOOR_LAYERS or second_category in FLOOR_LAYERS:
        return True
    if first_category in NON_FLOOR_OBJECTS or second_category in NON_FLOOR_OBJECTS:
        return True
    # 의자는 책상 아래에 일부 들어가는 것이 정상적인 배치다.
    return {first_category, second_category} == {"chair", "desk"}


def _inside_room(obj: dict[str, Any], x: float, y: float) -> tuple[float, float]:
    left, top, right, bottom = _bounds(obj, x, y)
    if left < DEFAULT_GAP:
        x += DEFAULT_GAP - left
    if right > 1.0 - DEFAULT_GAP:
        x -= right - (1.0 - DEFAULT_GAP)
    if top < DEFAULT_GAP:
        y += DEFAULT_GAP - top
    if bottom > 1.0 - DEFAULT_GAP:
        y -= bottom - (1.0 - DEFAULT_GAP)
    return _clamp(x, 0.0, 1.0), _clamp(y, 0.0, 1.0)


def _snap_to_walls(obj: dict[str, Any]) -> None:
    anchors = set(obj.get("wall_anchors") or [])
    width, depth = float(obj["width"]), float(obj["depth"])
    if "left" in anchors:
        obj["x"] = width / 2 + DEFAULT_GAP
    if "right" in anchors:
        obj["x"] = 1.0 - width / 2 - DEFAULT_GAP
    if "top" in anchors:
        obj["y"] = depth / 2 + DEFAULT_GAP
    if "bottom" in anchors:
        obj["y"] = 1.0 - depth / 2 - DEFAULT_GAP
    obj["x"], obj["y"] = _inside_room(obj, float(obj["x"]), float(obj["y"]))


def _relation_position(
    source: dict[str, Any],
    target: dict[str, Any],
    relation: str,
    gap: float,
) -> tuple[float, float]:
    x, y = float(source["x"]), float(source["y"])
    if relation == "left_of":
        x = float(target["x"]) - float(target["width"]) / 2 - float(source["width"]) / 2 - gap
    elif relation == "right_of":
        x = float(target["x"]) + float(target["width"]) / 2 + float(source["width"]) / 2 + gap
    elif relation == "above":
        y = float(target["y"]) - float(target["depth"]) / 2 - float(source["depth"]) / 2 - gap
    elif relation == "below":
        y = float(target["y"]) + float(target["depth"]) / 2 + float(source["depth"]) / 2 + gap
    elif relation == "aligned_x":
        x = float(target["x"])
    elif relation == "aligned_y":
        y = float(target["y"])
    elif relation == "near":
        # near는 원래 방향을 유지하면서 너무 멀 때만 거리를 줄인다.
        dx, dy = x - float(target["x"]), y - float(target["y"])
        distance = math.hypot(dx, dy)
        maximum = 0.36
        if distance > maximum:
            scale = maximum / distance
            x = float(target["x"]) + dx * scale
            y = float(target["y"]) + dy * scale
    return _inside_room(source, x, y)


def _apply_relations(objects: list[dict[str, Any]]) -> None:
    by_id = {str(obj["id"]): obj for obj in objects}
    # 서로 참조하는 관계가 있어도 몇 번의 완화 단계 안에서 안정되도록 제한한다.
    for _ in range(3):
        for source in objects:
            anchors = set(source.get("wall_anchors") or [])
            for raw in source.get("relations") or []:
                if not isinstance(raw, dict):
                    continue
                relation = str(raw.get("type") or "").lower()
                target = by_id.get(str(raw.get("target") or ""))
                if relation not in ALLOWED_RELATIONS or target is None or target is source:
                    continue
                x, y = _relation_position(
                    source,
                    target,
                    relation,
                    max(0.008, min(0.08, float(raw.get("gap", DEFAULT_GAP)))),
                )
                # 벽에 고정된 축은 관계 규칙으로 이동시키지 않는다.
                if not ({"left", "right"} & anchors):
                    source["x"] = x
                if not ({"top", "bottom"} & anchors):
                    source["y"] = y
            _snap_to_walls(source)


def _candidate_positions(obj: dict[str, Any]):
    origin_x, origin_y = float(obj["x"]), float(obj["y"])
    anchors = set(obj.get("wall_anchors") or [])
    x_locked = bool({"left", "right"} & anchors)
    y_locked = bool({"top", "bottom"} & anchors)
    yield origin_x, origin_y
    # 가까운 후보부터 나선형으로 탐색한다.
    for radius in (0.025, 0.05, 0.08, 0.12, 0.17, 0.23, 0.3, 0.38):
        for angle in range(0, 360, 30):
            radians = math.radians(angle)
            x = origin_x if x_locked else origin_x + math.cos(radians) * radius
            y = origin_y if y_locked else origin_y + math.sin(radians) * radius
            yield _inside_room(obj, x, y)


def _collision_score(
    obj: dict[str, Any],
    x: float,
    y: float,
    placed: list[dict[str, Any]],
) -> float:
    candidate_box = _bounds(obj, x, y)
    score = 0.0
    for other in placed:
        if _can_overlap(obj, other):
            continue
        overlap = _overlap_area(candidate_box, _bounds(other))
        if overlap:
            score += overlap * 10000.0
    # 원래 Gemini 좌표에서 너무 멀리 이동하는 것도 비용으로 둔다.
    score += math.hypot(x - float(obj["_original_x"]), y - float(obj["_original_y"]))
    return score


def _resolve_collisions(objects: list[dict[str, Any]], adjustments: list[dict[str, Any]]) -> None:
    movable = [
        obj
        for obj in objects
        if str(obj.get("category") or "") not in FLOOR_LAYERS | NON_FLOOR_OBJECTS
    ]
    # 벽에 고정된 큰 가구를 먼저 확정하고 작은/이동 가능한 가구를 나중에 옮긴다.
    movable.sort(
        key=lambda obj: (
            -len(obj.get("wall_anchors") or []),
            -(float(obj["width"]) * float(obj["depth"])),
            -float(obj.get("confidence", 0.5)),
        )
    )
    placed: list[dict[str, Any]] = []
    for obj in movable:
        before = (float(obj["x"]), float(obj["y"]))
        best = before
        best_score = float("inf")
        for candidate_x, candidate_y in _candidate_positions(obj):
            score = _collision_score(obj, candidate_x, candidate_y, placed)
            if score < best_score:
                best, best_score = (candidate_x, candidate_y), score
            if score < 0.0001:
                break
        obj["x"], obj["y"] = best
        if math.hypot(best[0] - before[0], best[1] - before[1]) >= 0.01:
            adjustments.append(
                {
                    "object_id": obj["id"],
                    "reason": "collision",
                    "from": [round(before[0], 4), round(before[1], 4)],
                    "to": [round(best[0], 4), round(best[1], 4)],
                }
            )
        placed.append(obj)


def solve_layout(layout: dict[str, Any]) -> dict[str, Any]:
    """layout을 제자리에서 보정하고 보정 기록을 함께 반환한다."""
    objects = list(layout.get("objects") or [])
    adjustments: list[dict[str, Any]] = []
    for obj in objects:
        obj["_original_x"] = float(obj["x"])
        obj["_original_y"] = float(obj["y"])
        before = (obj["_original_x"], obj["_original_y"])
        _snap_to_walls(obj)
        after = (float(obj["x"]), float(obj["y"]))
        if math.hypot(after[0] - before[0], after[1] - before[1]) >= 0.01:
            adjustments.append(
                {
                    "object_id": obj["id"],
                    "reason": (
                        "wall_anchor"
                        if obj.get("wall_anchors")
                        else "room_boundary"
                    ),
                    "from": [round(before[0], 4), round(before[1], 4)],
                    "to": [round(after[0], 4), round(after[1], 4)],
                }
            )

    _apply_relations(objects)
    _resolve_collisions(objects, adjustments)

    for obj in objects:
        obj.pop("_original_x", None)
        obj.pop("_original_y", None)
        obj["x"] = round(float(obj["x"]), 4)
        obj["y"] = round(float(obj["y"]), 4)
    layout["objects"] = objects
    layout["solver_adjustments"] = adjustments
    return layout
