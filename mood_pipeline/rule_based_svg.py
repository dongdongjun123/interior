# Gemini layout JSON → rule-based SVG floor plan renderer (v3)
from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Any

# API structured-output enum과 렌더러가 공유하는 객체 타입 vocabulary
LAYOUT_OBJECT_TYPES = [
    "bed", "desk", "table", "low_table", "shelf", "cabinet",
    "chair", "floor_chair", "stool", "rug", "mirror", "lamp",
    "plant", "door", "window", "unknown",
]

# 프롬프트는 코드에 하드코딩하지 않고 프로젝트 루트 prompts/*.txt에서 읽어온다.
# rule_based_svg.py는 mood_pipeline/ 안에 있으므로 부모의 부모가 프로젝트 루트.
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    """prompts/<name>.txt 파일을 읽어 프롬프트 문자열로 반환 (앞뒤 공백 제거)."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


RULE_BASED_LAYOUT_PROMPT = load_prompt("rule_based_layout")

RENDERER_VERSION = "3.7"

# 방/캔버스 크기 — aspect_ratio에 따라 render_svg 시작 시 _set_canvas()가 재계산.
BASE_LONG_SIDE = 820  # 긴 변 기준 길이(px)
ROOM_W, ROOM_H = 860, 560
MARGIN_X, MARGIN_Y = 90, 90
CANVAS_W = ROOM_W + MARGIN_X * 2
CANVAS_H = ROOM_H + MARGIN_Y * 2 + 120
GRID = 50
GRID_SNAP = 20  # 가구 정렬 격자(px)

STYLE = {
    "wall": "#111827",
    "line": "#334155",
    "thin": "#64748b",
    "grid": "#e5e7eb",
    "floor": "#fbfaf7",
    "wood": "#d7b98d",
    "bed": "#f8fafc",
    "glass": "#dff3ff",
    "text": "#111827",
    "rug": "#f3e7d3",
}

STD_SIZE: dict[str, tuple[int, int]] = {
    "bed": (230, 250),
    "desk": (280, 115),
    "table": (210, 110),
    "low_table": (230, 95),
    "shelf": (165, 120),
    "cabinet": (150, 110),
    "chair": (70, 70),
    "floor_chair": (78, 78),
    "stool": (82, 82),
    "rug": (360, 210),
    "mirror": (48, 170),
    "lamp": (118, 105),
    "plant": (55, 55),
    "window": (240, 20),
    "door": (25, 170),
    "unknown": (110, 75),
}

ZONE_POS: dict[str, tuple[float, float]] = {
    "bed": (0.20, 0.25),
    "shelf": (0.43, 0.16),
    "cabinet": (0.43, 0.16),
    "lamp": (0.62, 0.17),
    "stool": (0.76, 0.17),
    "rug": (0.50, 0.50),
    "mirror": (0.10, 0.70),
    "low_table": (0.78, 0.58),
    "table": (0.78, 0.58),
    "desk": (0.76, 0.78),
    "floor_chair": (0.57, 0.75),
    "chair": (0.67, 0.75),
    "window": (0.45, 0.98),
    "door": (0.98, 0.43),
    "plant": (0.88, 0.55),
    "unknown": (0.50, 0.50),
}

TYPE_PRIORITY: dict[str, int] = {
    "rug": 0,
    "bed": 1,
    "desk": 2,
    "table": 2,
    "low_table": 2,
    "shelf": 3,
    "cabinet": 3,
    "mirror": 4,
    "lamp": 4,
    "stool": 4,
    "chair": 4,
    "floor_chair": 4,
    "window": 5,
    "door": 5,
    "plant": 5,
}

LayoutDict = dict[str, Any]
PlacedObject = dict[str, Any]
Rect = tuple[float, float, float, float]


def extract_json_from_text(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("응답에서 JSON 객체를 찾을 수 없습니다.")
    return json.loads(text[start : end + 1])


def norm_type(t: str | None) -> str:
    t = (t or "unknown").lower().strip().replace(" ", "_").replace("-", "_")
    aliases = {
        "laptop": "desk",
        "laptop_desk": "desk",
        "coffee_table": "low_table",
        "shelf_unit": "shelf",
        "shelving": "shelf",
        "bookshelf": "shelf",
        "carpet": "rug",
        "table_lamp": "lamp",
    }
    t = aliases.get(t, t)
    return t if t in STD_SIZE else "unknown"


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def overlap(a: Rect, b: Rect, pad: float = 10) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + pad < bx or bx + bw + pad < ax or ay + ah + pad < by or by + bh + pad < ay)


def _is_percent_coords(obj: dict[str, Any]) -> bool:
    nums: list[float] = []
    for key in ("x", "y", "w", "h"):
        val = obj.get(key)
        if val is not None:
            try:
                nums.append(float(val))
            except (TypeError, ValueError):
                pass
    return bool(nums) and max(abs(n) for n in nums) > 1.5


def _infer_wall(cx: float, cy: float) -> str:
    if cx < 0.22:
        return "left"
    if cx > 0.78:
        return "right"
    if cy < 0.22:
        return "top"
    if cy > 0.78:
        return "bottom"
    return "none"


def _type_from_object(obj: dict[str, Any]) -> str:
    label = (obj.get("label") or "").lower()
    t = norm_type(str(obj.get("type") or ""))
    if "low table" in label:
        return "low_table"
    if "mirror" in label:
        return "mirror"
    if "floor chair" in label:
        return "floor_chair"
    if "laptop" in label or "desk" in label:
        return "desk"
    if t == "table" and "low" in label:
        return "low_table"
    if t in ("unknown", "other"):
        if "stool" in label:
            return "stool"
        if "mirror" in label:
            return "mirror"
        if "rug" in label:
            return "rug"
    return t


def _skip_redundant_object(obj: dict[str, Any]) -> bool:
    label = (obj.get("label") or "").lower()
    skip = ("laptop", "lamp on table", "plant on stool", "table lamp")
    return any(s in label for s in skip)


def coerce_layout_v3(layout: LayoutDict) -> LayoutDict:
    """layout_detail v2(0~100) 또는 혼합 스키마 → v3 렌더러용 0~1 center 좌표."""
    if layout.get("schema") == "rule_based_v3":
        return layout

    room_in = layout.get("room") or {}
    aspect = (
        room_in.get("aspect_ratio")
        or room_in.get("width_to_depth_ratio")
        or 1.45
    )

    out_objects: list[dict[str, Any]] = []
    chair_count = 0

    for obj in layout.get("objects", []):
        if _skip_redundant_object(obj):
            continue

        t = _type_from_object(obj)
        if t == "floor_chair":
            chair_count += 1
            if chair_count > 4:
                continue

        if _is_percent_coords(obj):
            x = float(obj.get("x", 0))
            y = float(obj.get("y", 0))
            w = float(obj.get("w", 10))
            h = float(obj.get("h", 10))
            # v2(0~100)는 x,y가 좌상단 → center 변환, w,h는 0~1 비율로 보존
            cx = clamp((x + w / 2) / 100.0, 0.04, 0.96)
            cy = clamp((y + h / 2) / 100.0, 0.04, 0.96)
            ow = clamp(w / 100.0, 0.0, 0.6)
            oh = clamp(h / 100.0, 0.0, 0.6)
        else:
            cx = clamp(float(obj.get("x", 0.5)), 0.04, 0.96)
            cy = clamp(float(obj.get("y", 0.5)), 0.04, 0.96)
            ow = clamp(float(obj.get("w", 0.0) or 0.0), 0.0, 0.6)
            oh = clamp(float(obj.get("h", 0.0) or 0.0), 0.0, 0.6)

        wall = obj.get("wall") or _infer_wall(cx, cy)
        if wall == "none":
            wall = _infer_wall(cx, cy)

        conf = float(obj.get("confidence", 0.72) or 0.72)
        out_objects.append(
            {
                "type": t,
                "label": obj.get("label") or t.replace("_", " ").title(),
                "x": cx,
                "y": cy,
                "w": ow,
                "h": oh,
                "wall": wall,
                "confidence": conf,
            }
        )

    has_window = any(o["type"] == "window" for o in out_objects)
    if not has_window:
        for wall in layout.get("walls") or []:
            side = str(wall.get("side", "")).lower()
            wins = wall.get("windows") or []
            if not wins:
                continue
            pos_map = {"west": "left", "east": "right", "north": "top", "south": "bottom"}
            wside = pos_map.get(side, side)
            if wside not in ("left", "right", "top", "bottom"):
                continue
            cx, cy = {"left": (0.05, 0.5), "right": (0.95, 0.5), "top": (0.5, 0.05), "bottom": (0.5, 0.95)}[wside]
            out_objects.append(
                {
                    "type": "window",
                    "label": "Window",
                    "x": cx,
                    "y": cy,
                    "w": 0.24,
                    "h": 0.03,
                    "wall": wside,
                    "confidence": 0.7,
                }
            )

    return {
        "schema": "rule_based_v3",
        "room": {
            "shape": room_in.get("shape", "rectangle"),
            "aspect_ratio": float(aspect),
            "description": room_in.get("description", ""),
        },
        "objects": out_objects,
    }


ABS_MIN_SIZE = 22  # 아무리 작아도 이 픽셀 미만으로는 안 그림(가독성)


def _gemini_size(o: dict[str, Any], std_w: int, std_h: int) -> tuple[float, float]:
    """Gemini w,h(0~1 비율)를 픽셀 크기로 변환해 모든 타입에 반영.
    없거나 비정상이면 표준 크기로 fallback. 아이콘이 깨지지 않게
    최소=표준의 60%(절대 하한 22px), 최대=방의 60%로만 클램프한다."""
    try:
        gw = float(o.get("w") or 0.0)
    except (TypeError, ValueError):
        gw = 0.0
    try:
        gh = float(o.get("h") or 0.0)
    except (TypeError, ValueError):
        gh = 0.0
    w = gw * ROOM_W if gw > 0.015 else std_w
    h = gh * ROOM_H if gh > 0.015 else std_h
    w = clamp(w, max(ABS_MIN_SIZE, std_w * 0.6), ROOM_W * 0.6)
    h = clamp(h, max(ABS_MIN_SIZE, std_h * 0.6), ROOM_H * 0.6)
    return w, h


_SURFACE_TYPES = {"desk", "table", "low_table"}


def _footprint_frac(o: dict[str, Any]) -> tuple[float, float, float, float]:
    x, y = float(o.get("x", 0.5)), float(o.get("y", 0.5))
    w, h = float(o.get("w", 0.1) or 0.1), float(o.get("h", 0.1) or 0.1)
    return x - w / 2, y - h / 2, x + w / 2, y + h / 2


def _contained_frac(a: dict[str, Any], b: dict[str, Any]) -> float:
    """a 면적 중 b와 겹치는 비율(0~1)."""
    ax0, ay0, ax1, ay1 = _footprint_frac(a)
    bx0, by0, bx1, by1 = _footprint_frac(b)
    ix = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0.0, min(ay1, by1) - max(ay0, by0))
    area = max(1e-6, (ax1 - ax0) * (ay1 - ay0))
    return ix * iy / area


def merge_subparts(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """책상 서랍 등 '부분품'을 모품(desk/table)에 흡수(제거).
    - 라벨에 drawer/drawers가 있고 surface에 걸치면 제거
    - cabinet/shelf/unknown이 surface에 60% 이상 포함되면 제거(책상 위/밑 부속)."""
    surfaces = [o for o in objects if norm_type(o.get("type")) in _SURFACE_TYPES]
    if not surfaces:
        return objects

    kept: list[dict[str, Any]] = []
    for o in objects:
        if o in surfaces:
            kept.append(o)
            continue
        t = norm_type(o.get("type"))
        label = (o.get("label") or "").lower()
        drop = False
        if "drawer" in label and t in ("cabinet", "unknown", "desk", "shelf"):
            drop = any(_contained_frac(o, s) > 0.35 for s in surfaces)
        if not drop and t in ("cabinet", "shelf", "unknown"):
            drop = any(_contained_frac(o, s) > 0.6 for s in surfaces)
        if not drop:
            kept.append(o)
    return kept


def postprocess_layout_objects(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """부분품 병합, 저신뢰 소품 제거, 벽당 창문 1개, low_table 주변 chair → floor_chair."""
    objects = merge_subparts(objects)
    filtered: list[dict[str, Any]] = []
    lamp_count = 0

    for obj in objects:
        t = norm_type(obj.get("type"))
        conf = float(obj.get("confidence", 0.5) or 0.5)
        label = (obj.get("label") or "").lower()

        if t in ("lamp", "plant") and conf < 0.65:
            continue
        if t == "lamp":
            lamp_count += 1
            if lamp_count > 2:
                continue
        if any(s in label for s in ("laptop", "table lamp", "plant on stool")):
            continue

        filtered.append(obj)

    windows_by_wall: dict[str, dict[str, Any]] = {}
    rest: list[dict[str, Any]] = []
    wall_center = {
        "left": (0.05, 0.5),
        "right": (0.95, 0.5),
        "top": (0.5, 0.05),
        "bottom": (0.5, 0.95),
    }

    for obj in filtered:
        t = norm_type(obj.get("type"))
        if t != "window":
            rest.append(obj)
            continue
        wall = str(obj.get("wall") or "bottom").lower()
        if wall not in wall_center:
            wall = _infer_wall(float(obj.get("x", 0.5)), float(obj.get("y", 0.5)))
        conf = float(obj.get("confidence", 0.5) or 0.5)
        prev = windows_by_wall.get(wall)
        if prev is None or conf > float(prev.get("confidence", 0) or 0):
            cx, cy = wall_center.get(wall, (0.5, 0.95))
            windows_by_wall[wall] = {
                **obj,
                "type": "window",
                "label": "Window",
                "wall": wall,
                "x": cx,
                "y": cy,
                "w": 0.35,
                "h": 0.03,
                "confidence": conf,
            }

    rest.extend(windows_by_wall.values())

    table = next((o for o in rest if norm_type(o.get("type")) == "low_table"), None)
    if table is not None:
        tx = float(table.get("x", 0.5))
        ty = float(table.get("y", 0.5))
        for obj in rest:
            if norm_type(obj.get("type")) != "chair":
                continue
            cx = float(obj.get("x", 0.5))
            cy = float(obj.get("y", 0.5))
            if (cx - tx) ** 2 + (cy - ty) ** 2 < 0.12:
                obj["type"] = "floor_chair"
                obj["label"] = "Floor Chair"

    return rest


def normalize_objects(layout: LayoutDict) -> list[PlacedObject]:
    objs: list[PlacedObject] = []
    for idx, o in enumerate(layout.get("objects", [])):
        t = norm_type(o.get("type"))
        label = o.get("label") or t.replace("_", " ").title()
        std_w, std_h = STD_SIZE.get(t, STD_SIZE["unknown"])
        zx, zy = ZONE_POS.get(t, ZONE_POS["unknown"])
        conf = float(o.get("confidence", 0.5) or 0.5)

        # 위치: Gemini center 좌표를 그대로 사용 (기본값 끌어당김 없음).
        # 좌표가 빠진 경우에만 ZONE_POS로 fallback.
        xv, yv = o.get("x"), o.get("y")
        xn = float(xv) if xv is not None else zx
        yn = float(yv) if yv is not None else zy
        cx = clamp(xn, 0.02, 0.98) * ROOM_W + MARGIN_X
        cy = clamp(yn, 0.02, 0.98) * ROOM_H + MARGIN_Y

        # 크기: 모든 타입에 Gemini w,h를 반영(가독성 클램프 포함).
        # window/door는 wall_attach에서 벽 규격으로 다시 덮어씀.
        w, h = _gemini_size(o, std_w, std_h)

        objs.append(
            {
                "type": t,
                "label": label,
                "cx": cx,
                "cy": cy,
                "w": w,
                "h": h,
                "wall": o.get("wall", "none") or "none",
                "confidence": conf,
                "idx": idx,
            }
        )
    return objs


CHAIR_SNAP_OFFSET = 92


def snap_chairs_to_table(objs: list[PlacedObject]) -> list[PlacedObject]:
    """low_table(또는 주변에 의자가 모인 table) 주변 floor_chair를 상하좌우로 정렬."""
    tables = [o for o in objs if o["type"] in ("low_table", "table")]
    if not tables:
        return objs

    chairs = [o for o in objs if o["type"] in ("chair", "floor_chair")]
    if len(chairs) < 2:
        return objs

    table = next((o for o in tables if o["type"] == "low_table"), None)
    if table is None:
        best: PlacedObject | None = None
        best_count = 0
        for cand in tables:
            near = sum(
                1
                for c in chairs
                if (c["cx"] - cand["cx"]) ** 2 + (c["cy"] - cand["cy"]) ** 2 < 120**2
            )
            if near > best_count:
                best, best_count = cand, near
        if best is None or best_count < 2:
            return objs
        table = best
        table["type"] = "low_table"
        table["label"] = "Low Table"

    tcx, tcy = table["cx"], table["cy"]
    offsets = [(0, 1), (0, -1), (1, 0), (-1, 0)]
    chairs.sort(key=lambda o: (o["cx"] - tcx) ** 2 + (o["cy"] - tcy) ** 2)

    for i, chair in enumerate(chairs[:4]):
        dx, dy = offsets[i]
        chair["cx"] = clamp(
            tcx + dx * CHAIR_SNAP_OFFSET,
            MARGIN_X + 36,
            MARGIN_X + ROOM_W - 36,
        )
        chair["cy"] = clamp(
            tcy + dy * CHAIR_SNAP_OFFSET,
            MARGIN_Y + 36,
            MARGIN_Y + ROOM_H - 36,
        )
        chair["type"] = "floor_chair"
        chair["label"] = "Floor Chair"
        cw, ch = STD_SIZE["floor_chair"]
        chair["w"], chair["h"] = cw, ch
        chair["wall"] = "none"

    return objs


def wall_attach(o: PlacedObject) -> PlacedObject:
    t = o["type"]
    x = o["cx"] - o["w"] / 2
    y = o["cy"] - o["h"] / 2
    wall = o.get("wall", "none")

    if t == "window":
        wall = wall if wall in ("top", "bottom", "left", "right") else "bottom"
        if wall in ("top", "bottom"):
            o["w"], o["h"] = STD_SIZE["window"]
            x = clamp(o["cx"] - o["w"] / 2, MARGIN_X + 80, MARGIN_X + ROOM_W - o["w"] - 80)
            y = MARGIN_Y - 7 if wall == "top" else MARGIN_Y + ROOM_H - 13
        else:
            o["w"], o["h"] = 20, 220
            x = MARGIN_X - 7 if wall == "left" else MARGIN_X + ROOM_W - 13
            y = clamp(o["cy"] - o["h"] / 2, MARGIN_Y + 80, MARGIN_Y + ROOM_H - o["h"] - 80)
    elif t == "door":
        wall = wall if wall in ("top", "bottom", "left", "right") else "right"
        if wall in ("left", "right"):
            o["w"], o["h"] = 25, 170
            x = MARGIN_X if wall == "left" else MARGIN_X + ROOM_W - o["w"]
            y = clamp(o["cy"] - o["h"] / 2, MARGIN_Y + 80, MARGIN_Y + ROOM_H - o["h"] - 80)
        else:
            o["w"], o["h"] = 170, 25
            x = clamp(o["cx"] - o["w"] / 2, MARGIN_X + 80, MARGIN_X + ROOM_W - o["w"] - 80)
            y = MARGIN_Y if wall == "top" else MARGIN_Y + ROOM_H - o["h"]
    elif wall in ("left", "right", "top", "bottom"):
        pad = 30
        if wall == "left":
            x = MARGIN_X + pad
        if wall == "right":
            x = MARGIN_X + ROOM_W - o["w"] - pad
        if wall == "top":
            y = MARGIN_Y + pad
        if wall == "bottom":
            y = MARGIN_Y + ROOM_H - o["h"] - pad

    o["x"] = clamp(x, MARGIN_X + 18, MARGIN_X + ROOM_W - o["w"] - 18)
    o["y"] = clamp(y, MARGIN_Y + 18, MARGIN_Y + ROOM_H - o["h"] - 18)
    return o


def auto_pack(objs: list[PlacedObject]) -> list[PlacedObject]:
    # 벽 부착만 적용하고 Gemini 위치는 유지 — 겹침 해소는 resolve_overlaps가 담당.
    # rug(우선순위 0)가 먼저 오도록 정렬 → 그리기 순서상 배경에 깔림.
    return [wall_attach(o) for o in sorted(objs, key=lambda x: TYPE_PRIORITY.get(x["type"], 9))]


# ── 틀(방 경계·벽·겹침) 안으로 밀어넣는 보정 ────────────────────────────────
INNER_L = MARGIN_X + 18
INNER_T = MARGIN_Y + 18
INNER_R = MARGIN_X + ROOM_W - 18
INNER_B = MARGIN_Y + ROOM_H - 18


# 소프트 벽 고정: 겹침 해소 때는 모든 축 이동 허용(벽이 꽉 차면 안쪽으로 밀려남).
# 대신 _wall_pull이 매 반복 벽 쪽으로 되당겨, 여유가 있으면 벽에 붙게 만든다.
def _can_move_x(o: PlacedObject) -> bool:
    return True


def _can_move_y(o: PlacedObject) -> bool:
    return True


# 벽에 되당길 구조 가구(소품 lamp/plant/chair는 제외 → 벽 앞 2열로 자유 배치)
WALL_PULL_TYPES = {"bed", "shelf", "cabinet", "desk", "table", "low_table", "mirror"}
WALL_PULL = 0.30


def _wall_pull(o: PlacedObject) -> None:
    if o["type"] not in WALL_PULL_TYPES:
        return
    w = o.get("wall")
    if w == "left":
        o["x"] += (MARGIN_X + 30 - o["x"]) * WALL_PULL
    elif w == "right":
        o["x"] += (MARGIN_X + ROOM_W - o["w"] - 30 - o["x"]) * WALL_PULL
    elif w == "top":
        o["y"] += (MARGIN_Y + 30 - o["y"]) * WALL_PULL
    elif w == "bottom":
        o["y"] += (MARGIN_Y + ROOM_H - o["h"] - 30 - o["y"]) * WALL_PULL


def _clamp_into_room(o: PlacedObject) -> None:
    o["x"] = clamp(o["x"], INNER_L, INNER_R - o["w"])
    o["y"] = clamp(o["y"], INNER_T, INNER_B - o["h"])


def _apply_push(a: PlacedObject, b: PlacedObject, pen: float, sign: float, axis: str) -> None:
    can_a = _can_move_x(a) if axis == "x" else _can_move_y(a)
    can_b = _can_move_x(b) if axis == "x" else _can_move_y(b)
    if can_a and can_b:
        a[axis] += sign * pen / 2
        b[axis] -= sign * pen / 2
    elif can_a:
        a[axis] += sign * pen
    elif can_b:
        b[axis] -= sign * pen


_GROUP_SEATING = {"chair", "floor_chair", "stool"}
_GROUP_TABLES = {"table", "low_table"}
_ACCESSORY = {"lamp", "plant"}
_ACC_SURFACES = {"desk", "table", "low_table", "shelf", "cabinet"}


def _grouped_pair(a: PlacedObject, b: PlacedObject) -> bool:
    # 인접/포개짐이 의도된 조합은 서로 밀어내지 않는다:
    #  - 테이블 주변의 의자
    #  - 책상/선반 위에 올려둔 조명·화분(그리기 순서상 위에 얹혀 보임)
    ta, tb = a["type"], b["type"]
    if (ta in _GROUP_TABLES and tb in _GROUP_SEATING) or (
        tb in _GROUP_TABLES and ta in _GROUP_SEATING
    ):
        return True
    if (ta in _ACCESSORY and tb in _ACC_SURFACES) or (
        tb in _ACCESSORY and ta in _ACC_SURFACES
    ):
        return True
    return False


def _separate_pair(a: PlacedObject, b: PlacedObject, pad: float) -> bool:
    if _grouped_pair(a, b):
        return False
    ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if ox <= -pad or oy <= -pad:  # 이미 pad 이상 떨어짐
        return False

    px, py = ox + pad, oy + pad  # 여유 패딩 포함 침투량
    x_ok = _can_move_x(a) or _can_move_x(b)
    y_ok = _can_move_y(a) or _can_move_y(b)
    if not x_ok and not y_ok:
        return False

    # 침투가 작은 축으로 분리하되, 그 축이 둘 다 고정이면 다른 축 사용
    use_x = px <= py
    if use_x and not x_ok:
        use_x = False
    elif not use_x and not y_ok:
        use_x = True

    # 같은 벽에 붙은 두 가구는 벽면을 따라 분리(좌우벽→상하, 상하벽→좌우)
    wa, wb = a.get("wall"), b.get("wall")
    if wa == wb:
        if wa in ("left", "right"):
            use_x = False
        elif wa in ("top", "bottom"):
            use_x = True

    if use_x:
        sign = -1.0 if (a["x"] + a["w"] / 2) <= (b["x"] + b["w"] / 2) else 1.0
        _apply_push(a, b, px, sign, "x")
    else:
        sign = -1.0 if (a["y"] + a["h"] / 2) <= (b["y"] + b["h"] / 2) else 1.0
        _apply_push(a, b, py, sign, "y")
    return True


def _push_out_of_rect(a: PlacedObject, r: Rect, pad: float) -> None:
    rx, ry, rw, rh = r
    px = min(a["x"] + a["w"], rx + rw) - max(a["x"], rx)
    py = min(a["y"] + a["h"], ry + rh) - max(a["y"], ry)
    if px <= 0 or py <= 0:
        return
    if px <= py and _can_move_x(a):
        sign = -1.0 if (a["x"] + a["w"] / 2) <= (rx + rw / 2) else 1.0
        a["x"] += sign * (px + pad)
    elif _can_move_y(a):
        sign = -1.0 if (a["y"] + a["h"] / 2) <= (ry + rh / 2) else 1.0
        a["y"] += sign * (py + pad)


def resolve_overlaps(
    objs: list[PlacedObject], iterations: int = 140, pad: float = 8.0
) -> list[PlacedObject]:
    """Gemini 배치는 유지하되 겹치는 가구를 최소 이동으로 떼어 놓고, 방 안에 가둔다.
    rug는 배경, window/door는 벽 고정이라 대상에서 제외(문/창은 회피 장애물로만 사용)."""
    movable = [o for o in objs if o["type"] not in ("rug", "window", "door")]
    obstacles: list[Rect] = [
        (o["x"], o["y"], o["w"], o["h"])
        for o in objs
        if o["type"] in ("window", "door")
    ]
    n = len(movable)
    for _ in range(iterations):
        moved = False
        for i in range(n):
            a = movable[i]
            for j in range(i + 1, n):
                if _separate_pair(a, movable[j], pad):
                    moved = True
            for rect in obstacles:
                _push_out_of_rect(a, rect, pad)
        for o in movable:
            _wall_pull(o)  # 여유 있으면 벽으로 되당김(소프트 고정)
            _clamp_into_room(o)
        if not moved:
            break
    return objs


def grid_align(objs: list[PlacedObject], grid: int = GRID_SNAP) -> list[PlacedObject]:
    """가구를 격자에 살짝 스냅해 정렬감(틀)을 준다. 벽 고정 축은 건드리지 않음.
    (스냅 후 미세 겹침이 생길 수 있어 render_svg에서 resolve_overlaps를 한 번 더 돌린다.)"""
    for o in objs:
        if o["type"] in ("rug", "window", "door"):
            continue
        wall = o.get("wall")
        # 벽에 붙은 축(수직축)은 스냅하지 않아 벽면 밀착을 유지
        if wall not in ("left", "right"):
            o["x"] = round((o["x"] - MARGIN_X) / grid) * grid + MARGIN_X
        if wall not in ("top", "bottom"):
            o["y"] = round((o["y"] - MARGIN_Y) / grid) * grid + MARGIN_Y
        _clamp_into_room(o)
    return objs


def _set_canvas(aspect_ratio: float | int | None) -> None:
    """room.aspect_ratio(width÷depth)에 맞춰 방·캔버스·내부경계 상수를 재계산."""
    global ROOM_W, ROOM_H, CANVAS_W, CANVAS_H, INNER_L, INNER_T, INNER_R, INNER_B
    try:
        a = float(aspect_ratio or 0) or 1.45
    except (TypeError, ValueError):
        a = 1.45
    a = clamp(a, 0.6, 2.0)  # width : depth
    if a >= 1.0:
        ROOM_W = BASE_LONG_SIDE
        ROOM_H = round(BASE_LONG_SIDE / a)
    else:
        ROOM_H = BASE_LONG_SIDE
        ROOM_W = round(BASE_LONG_SIDE * a)
    CANVAS_W = ROOM_W + MARGIN_X * 2
    CANVAS_H = ROOM_H + MARGIN_Y * 2 + 120
    INNER_L = MARGIN_X + 18
    INNER_T = MARGIN_Y + 18
    INNER_R = MARGIN_X + ROOM_W - 18
    INNER_B = MARGIN_Y + ROOM_H - 18


def label(x: float, y: float, s: str, size: int = 15, anchor: str = "middle") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-family="Arial, sans-serif" font-size="{size}" fill="{STYLE["text"]}">'
        f"{escape(str(s))}</text>"
    )


def grid() -> str:
    parts: list[str] = []
    for x in range(MARGIN_X, MARGIN_X + ROOM_W + 1, GRID):
        parts.append(
            f'<line x1="{x}" y1="{MARGIN_Y}" x2="{x}" y2="{MARGIN_Y + ROOM_H}" stroke="{STYLE["grid"]}"/>'
        )
    for y in range(MARGIN_Y, MARGIN_Y + ROOM_H + 1, GRID):
        parts.append(
            f'<line x1="{MARGIN_X}" y1="{y}" x2="{MARGIN_X + ROOM_W}" y2="{y}" stroke="{STYLE["grid"]}"/>'
        )
    return "\n".join(parts)


def room() -> str:
    return (
        f'<rect x="{MARGIN_X}" y="{MARGIN_Y}" width="{ROOM_W}" height="{ROOM_H}" '
        f'fill="{STYLE["floor"]}" stroke="{STYLE["wall"]}" stroke-width="10" rx="4"/>'
        f"{grid()}"
        f'<rect x="{MARGIN_X}" y="{MARGIN_Y}" width="{ROOM_W}" height="{ROOM_H}" '
        f'fill="none" stroke="{STYLE["wall"]}" stroke-width="10" rx="4"/>'
    )


def bed(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="#ead9c1" '
        f'stroke="{STYLE["line"]}" stroke-width="2"/>'
        f'<rect x="{x + 12}" y="{y + 12}" width="{w - 24}" height="{h - 24}" rx="10" '
        f'fill="{STYLE["bed"]}" stroke="{STYLE["line"]}" stroke-width="1.8"/>'
        f'<rect x="{x + 26}" y="{y + 26}" width="{(w - 70) / 2}" height="46" rx="8" '
        f'fill="#f1eadc" stroke="{STYLE["thin"]}"/>'
        f'<rect x="{x + 44 + (w - 70) / 2}" y="{y + 26}" width="{(w - 70) / 2}" height="46" '
        f'rx="8" fill="#f1eadc" stroke="{STYLE["thin"]}"/>'
        f'{label(x + w / 2, y + h / 2 + 18, o["label"], 17)}</g>'
    )


def rug(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    tass: list[str] = []
    for yy in range(int(y + 8), int(y + h - 5), 10):
        tass.append(f'<line x1="{x - 8}" y1="{yy}" x2="{x}" y2="{yy + 3}" stroke="#b08d61"/>')
        tass.append(f'<line x1="{x + w}" y1="{yy + 3}" x2="{x + w + 8}" y2="{yy}" stroke="#b08d61"/>')
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="{STYLE["rug"]}" '
        f'stroke="#9a6b44" stroke-dasharray="6 4"/>'
        f'<rect x="{x + 14}" y="{y + 14}" width="{w - 28}" height="{h - 28}" fill="none" '
        f'stroke="#c7a47a" stroke-dasharray="3 5"/>'
        f'{"".join(tass)}'
        f'{label(x + w / 2, y + h / 2 + 5, o["label"], 17)}</g>'
    )


def wood(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    lines = "".join(
        f'<line x1="{x + 8}" y1="{y + yy}" x2="{x + w - 8}" y2="{y + yy}" '
        f'stroke="#b89467" opacity="0.5"/>'
        for yy in range(18, int(h), 22)
    )
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{STYLE["wood"]}" '
        f'stroke="{STYLE["line"]}" stroke-width="2"/>'
        f"{lines}"
        f'<rect x="{x + 6}" y="{y + 6}" width="{w - 12}" height="{h - 12}" rx="4" '
        f'fill="none" stroke="#8b6f50" opacity="0.6"/>'
        f'{label(x + w / 2, y + h / 2 + 5, o["label"], 16)}</g>'
    )


def desk(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    return (
        f"<g>{wood(o)}"
        f'<rect x="{x + w * 0.34}" y="{y + 18}" width="{w * 0.32}" height="{h * 0.45}" '
        f'rx="3" fill="#475569" stroke="#1f2937"/>'
        f'<rect x="{x + w * 0.36}" y="{y + 22}" width="{w * 0.28}" height="{h * 0.32}" fill="#e5e7eb"/>'
        f'<rect x="{x + w * 0.32}" y="{y + h * 0.58}" width="{w * 0.36}" height="8" '
        f'rx="2" fill="#cbd5e1" stroke="#64748b"/></g>'
    )


def round_obj(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    cx = x + w / 2
    cy = y + h / 2
    return (
        f'<g><circle cx="{cx}" cy="{cy}" r="{min(w, h) / 2 - 3}" fill="#f8fafc" '
        f'stroke="{STYLE["line"]}" stroke-width="2"/>'
        f'<path d="M {cx - 16} {cy - 4} q 10 10 20 0" stroke="#9ca3af" fill="none"/>'
        f'<path d="M {cx - 12} {cy + 12} q 8 -8 18 0" stroke="#9ca3af" fill="none"/>'
        f'{label(cx, y + h + 22, o["label"], 14)}</g>'
    )


def mirror(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="#e7d1ad" '
        f'stroke="{STYLE["line"]}" stroke-width="2"/>'
        f'<rect x="{x + 7}" y="{y + 7}" width="{w - 14}" height="{h - 14}" '
        f'fill="{STYLE["glass"]}" stroke="#94a3b8"/>'
        f'<line x1="{x + 12}" y1="{y + h - 28}" x2="{x + w - 12}" y2="{y + 18}" '
        f'stroke="#fff" stroke-width="2"/>'
        f'{label(x + w + 26, y + h / 2, o["label"], 16, "start")}</g>'
    )


def lamp(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    cx = x + w / 2
    return (
        f"<g>{wood(o)}"
        f'<circle cx="{cx}" cy="{y + 34}" r="24" fill="#fff8e7" stroke="{STYLE["line"]}" stroke-width="2"/>'
        f'<circle cx="{cx}" cy="{y + 34}" r="17" fill="#fff" stroke="#d6c9a8"/>'
        f'<path d="M {cx - 38} {y + 44} h18 v26 h-18 z" fill="#d7b98d" stroke="{STYLE["line"]}"/></g>'
    )


def stool(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    return (
        f'<g><rect x="{x + 8}" y="{y + 8}" width="{w - 16}" height="{h - 16}" rx="18" '
        f'fill="#e5e1da" stroke="{STYLE["line"]}" stroke-width="2"/>'
        f'<rect x="{x + 14}" y="{y + 14}" width="{w - 28}" height="{h - 28}" rx="14" '
        f'fill="#d9d6cf" stroke="#9ca3af"/>'
        f'{label(x + w / 2, y + h / 2 + 5, o["label"], 15)}</g>'
    )


def window(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#e0f2fe" '
        f'stroke="{STYLE["line"]}" stroke-width="2"/>'
        f'<line x1="{x + w / 2}" y1="{y}" x2="{x + w / 2}" y2="{y + h}" stroke="{STYLE["line"]}"/>'
        f'<line x1="{x + 8}" y1="{y + h / 2}" x2="{x + w - 8}" y2="{y + h / 2}" '
        f'stroke="#60a5fa" stroke-width="1.5"/></g>'
    )


def door(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    hx = x + w
    hy = y + h
    r = min(145, h)
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#f8fafc" '
        f'stroke="{STYLE["line"]}" stroke-width="2"/>'
        f'<path d="M {hx} {hy} A {r} {r} 0 0 0 {hx - r} {hy - r}" fill="none" '
        f'stroke="#475569" stroke-dasharray="6 4"/>'
        f'<line x1="{hx}" y1="{hy}" x2="{hx - r}" y2="{hy}" stroke="{STYLE["line"]}" stroke-width="3"/></g>'
    )


def generic(o: PlacedObject) -> str:
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    return (
        f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#f8fafc" '
        f'stroke="{STYLE["line"]}" stroke-width="2"/>'
        f'{label(x + w / 2, y + h / 2 + 5, o["label"], 15)}</g>'
    )


DRAWERS: dict[str, Any] = {
    "bed": bed,
    "rug": rug,
    "shelf": wood,
    "cabinet": wood,
    "table": wood,
    "low_table": wood,
    "desk": desk,
    "mirror": mirror,
    "lamp": lamp,
    "stool": stool,
    "chair": round_obj,
    "floor_chair": round_obj,
    "window": window,
    "door": door,
}


def draw_obj(o: PlacedObject) -> str:
    return DRAWERS.get(o["type"], generic)(o)


def dimensions() -> str:
    x1, y1 = MARGIN_X, MARGIN_Y
    x2, y2 = MARGIN_X + ROOM_W, MARGIN_Y + ROOM_H
    ty = MARGIN_Y - 42
    lx = MARGIN_X - 56
    return (
        f'<line x1="{x1}" y1="{ty}" x2="{x2}" y2="{ty}" stroke="{STYLE["line"]}"/>'
        f'<circle cx="{x1}" cy="{ty}" r="4" fill="{STYLE["line"]}"/>'
        f'<circle cx="{x2}" cy="{ty}" r="4" fill="{STYLE["line"]}"/>'
        f'{label((x1 + x2) / 2, ty + 8, "Room width", 14)}'
        f'<line x1="{lx}" y1="{y1}" x2="{lx}" y2="{y2}" stroke="{STYLE["line"]}"/>'
        f'<circle cx="{lx}" cy="{y1}" r="4" fill="{STYLE["line"]}"/>'
        f'<circle cx="{lx}" cy="{y2}" r="4" fill="{STYLE["line"]}"/>'
        f'<text x="{lx}" y="{(y1 + y2) / 2}" text-anchor="middle" font-family="Arial" '
        f'font-size="14" fill="{STYLE["text"]}" transform="rotate(-90 {lx} {(y1 + y2) / 2})">'
        f"Room depth</text>"
    )


def fit_walls(objs: list[PlacedObject], edge: int = 40, pad: int = 12) -> list[PlacedObject]:
    """한 벽에 붙은 구조 가구의 폭 합이 벽 길이를 넘으면 그 줄 가구를 비율 축소.
    (병합으로도 안 들어가는 과다검출을 한 줄에 맞춰 겹침을 원천 차단.)"""
    sides = (
        ("top", "w", ROOM_W - 2 * edge),
        ("bottom", "w", ROOM_W - 2 * edge),
        ("left", "h", ROOM_H - 2 * edge),
        ("right", "h", ROOM_H - 2 * edge),
    )
    for side, dim, avail in sides:
        row = [o for o in objs if o.get("wall") == side and o["type"] in WALL_PULL_TYPES]
        if len(row) < 2:
            continue
        needed = sum(o[dim] for o in row) + pad * (len(row) - 1)
        if needed <= avail:
            continue
        factor = max(0.5, avail / needed)  # 최대 50%까지만 축소
        for o in row:
            o["w"] *= factor
            o["h"] *= factor
    return objs


def render_svg(layout: LayoutDict, title: str = "Rule-based Floor Plan v3") -> str:
    layout = coerce_layout_v3(layout)
    _set_canvas((layout.get("room") or {}).get("aspect_ratio"))
    layout["objects"] = postprocess_layout_objects(layout.get("objects", []))
    sized = fit_walls(snap_chairs_to_table(normalize_objects(layout)))
    packed = auto_pack(sized)
    # 겹침 제거 → 격자 정렬 → 정렬로 생긴 미세 겹침 재제거
    objs = resolve_overlaps(grid_align(resolve_overlaps(packed)))
    object_svg = "\n".join(draw_obj(o) for o in objs)

    legend_y = MARGIN_Y + ROOM_H + 70
    legend: list[str] = [
        f'<text x="{MARGIN_X}" y="{legend_y - 24}" font-family="Arial" font-size="17" '
        f'font-weight="700" fill="{STYLE["text"]}">Legend</text>'
    ]
    lx = MARGIN_X
    for o in [o for o in objs if o["type"] not in ("door", "window")][:9]:
        legend.append(
            f'<rect x="{lx}" y="{legend_y}" width="28" height="18" rx="3" '
            f'fill="#f8fafc" stroke="{STYLE["line"]}"/>'
        )
        legend.append(label(lx + 14, legend_y + 42, o["label"], 12))
        lx += 105

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_W}" height="{CANVAS_H}" '
        f'viewBox="0 0 {CANVAS_W} {CANVAS_H}">'
        f"<!-- renderer-version:{RENDERER_VERSION} -->"
        f'<rect width="100%" height="100%" fill="#f8fafc"/>'
        f'<text x="40" y="42" font-family="Arial" font-size="30" font-weight="700" '
        f'fill="{STYLE["text"]}">{escape(title)}</text>'
        f'<text x="40" y="70" font-family="Arial" font-size="16" fill="#334155">'
        f"Gemini extraction + Python icon renderer / improved packing</text>"
        f"{dimensions()}{room()}{object_svg}{''.join(legend)}</svg>"
    )


def save_svg(layout: LayoutDict, path: str | Path, title: str = "Rule-based Floor Plan v3") -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_svg(layout, title=title), encoding="utf-8")
    return out
