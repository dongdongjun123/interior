# Florence-2 탐지 결과(detection.json) → Gemini layout 추출용 "근거 텍스트" 변환
#
# 역할 분담 (docs/3d-reconstruction-plan.md 및 설계 논의 기준):
#  - Florence = 사실 제공: 무슨 가구가 몇 개, 사진 내 대략 위치(좌/우·원경/근경), 박스 종횡비
#  - Gemini   = 추론: 이 사실을 근거로 원근을 풀어 top-down x,y·벽·실측 m 배정
# 따라서 여기서는 Florence의 픽셀 좌표를 그대로 넘기지 않고,
# "사진의 어느 구역에 있었다"는 정성적 위치로만 요약한다(2D 좌표 과신 방지).
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Florence 클래스 → 렌더러 타입 vocabulary 매핑.
# room-object-detection 의 TARGETS 클래스명을 rule_based_svg 의 LAYOUT_OBJECT_TYPES 로 잇는다.
_CLASS_TO_TYPE = {
    "bed": "bed",
    "chair": "chair",
    "nightstand": "low_table",  # 협탁 ≈ 낮은 사이드 테이블
    "lamp": "lamp",
    "plant": "plant",
    "shelf": "shelf",
    "table": "table",
    "picture": "mirror",  # 액자/그림 → 벽면 사각(거울과 동일 렌더)
    "rug": "rug",
}


def _zone(x_center: float, y_center: float) -> str:
    """사진 내 대략 구역을 한국어로. (정성적 위치 — 좌표 과신 방지용)
    x,y 는 0~1 (사진 프레임 기준, bbox_norm 중심)."""
    horiz = "왼쪽" if x_center < 0.38 else ("오른쪽" if x_center > 0.62 else "가운데")
    # 사진 세로: 위=원경(방 안쪽일 가능성), 아래=근경(카메라 앞). '가능성'까지만 표현.
    vert = "위쪽(원경)" if y_center < 0.38 else ("아래쪽(근경)" if y_center > 0.62 else "중앙 높이")
    return f"{horiz} {vert}"


def _size_hint(w: float, h: float) -> str:
    """박스가 사진에서 차지한 크기 힌트(원근 포함이므로 '사진 기준'임을 명시)."""
    area = w * h
    if area > 0.25:
        return "사진에서 크게 보임"
    if area < 0.05:
        return "사진에서 작게 보임"
    return "사진에서 중간 크기"


def summarize_detection(detection: dict[str, Any]) -> list[dict[str, Any]]:
    """detection.json → 간결한 근거 항목 리스트.
    각 항목: {type, source_class, zone, size_hint, aspect}."""
    items: list[dict[str, Any]] = []
    for obj in detection.get("objects", []):
        cls = str(obj.get("class", "")).lower()
        rtype = _CLASS_TO_TYPE.get(cls, "unknown")
        norm = obj.get("bbox_norm") or {}
        x = float(norm.get("x", 0)) + float(norm.get("w", 0)) / 2  # 좌상단→중심
        y = float(norm.get("y", 0)) + float(norm.get("h", 0)) / 2
        w = float(norm.get("w", 0)) or 0.0
        h = float(norm.get("h", 0)) or 0.0
        aspect = round(w / h, 2) if h > 0 else None
        items.append({
            "type": rtype,
            "source_class": cls,
            "zone": _zone(x, y),
            "size_hint": _size_hint(w, h),
            "aspect": aspect,
        })
    return items


def build_evidence_prompt(detection: dict[str, Any]) -> str:
    """근거 항목 리스트 → Gemini 프롬프트에 덧붙일 텍스트 블록.
    개수·클래스는 사실로 강제하고, 좌표 과신을 막는 제약 룰을 함께 명시한다."""
    items = summarize_detection(detection)
    if not items:
        return ""  # 탐지 결과 없으면 근거 주입 생략(기존 동작 유지)

    # 타입별 개수 집계 (Gemini가 개수를 지키게 하는 근거)
    counts: dict[str, int] = {}
    for it in items:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    count_line = ", ".join(f"{t}×{n}" for t, n in sorted(counts.items()))

    lines = [
        "",
        "── DETECTED FURNITURE (from an object detector, treat COUNTS and CLASSES as ground truth) ──",
        f"Detected inventory (must match): {count_line}",
        "Per-item observation (photo-frame view, NOT top-down):",
    ]
    for i, it in enumerate(items):
        asp = f", aspect≈{it['aspect']}" if it["aspect"] else ""
        lines.append(
            f"  {i+1}. {it['type']} (detector said '{it['source_class']}') "
            f"— {it['zone']}, {it['size_hint']}{asp}"
        )

    # 제약 룰: 개수는 강제, 좌표는 top-down 재판단(2D 과신 금지)
    lines += [
        "",
        "RULES for using the detection above:",
        "- The COUNT and CLASS of objects are facts: produce exactly these objects, no more, no fewer.",
        "  Do NOT invent furniture that was not detected, and do NOT drop detected furniture.",
        "- The positions above are from the PHOTO (with perspective), NOT a top-down plan.",
        "  You MUST re-derive top-down x,y yourself from the camera view — do not copy the photo's up/down as plan y.",
        "- Keep results physically plausible: objects must stay inside the room and must not overlap each other.",
        "- Use the aspect hint only as a weak prior for w/h; correct it if the top-down footprint differs.",
        "───────────────────────────────────────────────────────────────────────",
    ]
    return "\n".join(lines)


def load_detection(path: str | Path) -> dict[str, Any]:
    """detection.json 파일 로드. 없거나 깨지면 빈 dict(근거 없이 진행)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
