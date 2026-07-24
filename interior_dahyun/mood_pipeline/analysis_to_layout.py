# room_analysis_result.json (가구 판단 + 관계형 zone_layout) → rule-based SVG용 layout(room + 0~1 center 좌표)
# 좌표가 없는 분석 결과를 zone_layout 의 relation/anchor 로 대략 배치해 renderer(save_svg)에 넘긴다.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 한글/영문 가구명 → renderer type (rule_based_svg.LAYOUT_OBJECT_TYPES 기준)
_TYPE_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("침대", "bed"), "bed"),
    (("책상", "desk", "데스크"), "desk"),
    (("좌탁", "low table", "커피 테이블", "coffee table"), "low_table"),
    (("식탁", "dining table", "테이블", "table"), "table"),
    (("책장", "책꽂이", "bookshelf", "선반", "shelf"), "shelf"),
    (("옷장", "장롱", "수납장", "서랍", "드레서", "wardrobe", "cabinet", "dresser"), "cabinet"),
    (("좌식", "floor chair", "방석"), "floor_chair"),
    (("스툴", "stool"), "stool"),
    (("의자", "체어", "chair"), "chair"),
    (("러그", "카펫", "rug", "carpet"), "rug"),
    (("거울", "mirror"), "mirror"),
    (("조명", "램프", "스탠드", "lamp", "light"), "lamp"),
    (("화분", "식물", "plant"), "plant"),
    (("창문", "창", "window"), "window"),
    (("문", "door"), "door"),
]

# 배치에서 제외할 결정 값(제거/폐기)
_DROP_DECISIONS = {"remove", "discard", "replace_out", "제거", "버리기", "폐기"}

# 타입별 기본 벽
_DEFAULT_WALL = {
    "bed": "right", "shelf": "left", "cabinet": "left", "mirror": "left",
    "desk": "top", "table": "top", "window": "top", "door": "bottom",
}
_WALL_XY = {
    "top": (0.5, 0.12), "bottom": (0.5, 0.88),
    "left": (0.12, 0.5), "right": (0.88, 0.5), "none": (0.5, 0.5),
}


def _clamp(v: float, lo: float = 0.06, hi: float = 0.94) -> float:
    return max(lo, min(hi, v))


def furniture_type(name: str) -> str:
    low = (name or "").lower()
    for keys, t in _TYPE_KEYWORDS:
        if any(k.lower() in low for k in keys):
            return t
    return "unknown"


def analysis_result_to_layout(
    analysis: dict[str, Any],
    *,
    aspect_ratio: float = 1.3,
    description: str | None = None,
) -> dict[str, Any]:
    """room_analysis_result.json 형식 → renderer용 layout dict."""
    # 1) 배치할 가구 이름 수집: keep 된 기존가구 + 렌더 가능한 추천구매(가구류만)
    names: list[str] = []
    for f in analysis.get("existing_furniture", []) or []:
        if str(f.get("decision", "keep")).lower() in _DROP_DECISIONS:
            continue
        n = str(f.get("item", "")).strip()
        if n:
            names.append(n)
    for p in analysis.get("recommended_purchases", []) or []:
        n = str(p.get("item", "")).strip()
        if n and furniture_type(n) != "unknown":  # 벽/포스터 등 비-가구는 제외
            names.append(n)

    # 2) 이름 → 오브젝트(이름 기준 중복 제거)
    objects: dict[str, dict[str, Any]] = {}
    for n in names:
        objects.setdefault(n, {"type": furniture_type(n), "label": n})

    # 3) zone_layout 관계 파싱 + 앵커가 창문/문이면 자동 추가
    relations: list[tuple[str, str, str]] = []
    for z in analysis.get("zone_layout", []) or []:
        item = str(z.get("item", "")).strip()
        anchor = str(z.get("anchor", "")).strip()
        rel = str(z.get("relation", "")).strip().lower()
        relations.append((item, rel, anchor))
        if anchor and anchor not in objects:
            at = furniture_type(anchor)
            if at in ("window", "door"):
                objects[anchor] = {"type": at, "label": anchor}

    # 4) 기본 벽 배치(같은 벽이면 살짝 분산)
    used: dict[str, int] = {}
    free = [(0.35, 0.42), (0.65, 0.42), (0.35, 0.66), (0.65, 0.66)]
    fi = 0
    for obj in objects.values():
        wall = _DEFAULT_WALL.get(obj["type"], "none")
        bx, by = _WALL_XY[wall]
        k = used.get(wall, 0)
        used[wall] = k + 1
        if wall in ("top", "bottom"):
            bx = 0.28 + 0.22 * k
        elif wall in ("left", "right"):
            by = 0.28 + 0.22 * k
        elif wall == "none":
            bx, by = free[fi % len(free)]
            fi += 1
        obj.update(x=_clamp(bx), y=_clamp(by), wall=wall)

    # 5) 관계 적용(앵커 기준 상대 배치) — 앵커는 위에서 이미 좌표를 가짐
    for item, rel, anchor in relations:
        o = objects.get(item)
        a = objects.get(anchor)
        if not o or not a:
            continue
        ax, ay = a["x"], a["y"]
        if rel in ("facing", "faces", "toward", "마주", "향함"):
            # 앵커(예: 창문)를 바라보게 → 앵커 벽 안쪽으로
            o.update(x=_clamp(ax), y=_clamp(ay + 0.22 if ay < 0.5 else ay - 0.22), wall="none")
        elif rel in ("near", "beside", "next_to", "옆", "인접", "근처"):
            o.update(x=_clamp(ax + 0.14), y=_clamp(ay + 0.14), wall="none")
        elif rel in ("center", "on", "above", "위", "중앙"):
            # 표면 위 소품(조명 등)은 renderer 가 표면에 스냅
            o.update(x=_clamp(ax), y=_clamp(ay), wall="none")

    return {
        "room": {
            "shape": "rectangle",
            "aspect_ratio": float(aspect_ratio),
            "description": description or "",
        },
        "objects": list(objects.values()),
    }


def load_analysis_layout(
    analysis_path: str | Path,
    *,
    aspect_ratio: float = 1.3,
    description: str | None = None,
) -> dict[str, Any]:
    """room_analysis_result.json 파일 경로 → layout dict."""
    data = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
    return analysis_result_to_layout(data, aspect_ratio=aspect_ratio, description=description)
