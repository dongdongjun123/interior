"""사용자 문장에서 서로 반대되는 인테리어 감각 축을 찾는다."""

from __future__ import annotations

import re


# 각 축의 두 극은 의도적으로 시각 차이가 큰 영문 CLIP 앵커를 사용한다.
SEMANTIC_AXES = (
    {
        "id": "temperature",
        "name_ko": "온도감",
        "poles": (
            {
                "id": "warm",
                "name_ko": "따뜻한",
                "anchor": "a warm cozy interior with amber light and warm colors",
                "cues": ("따뜻", "포근", "온화", "아늑", "warm", "cozy", "amber"),
            },
            {
                "id": "cool",
                "name_ko": "시원한",
                "anchor": "a cool refreshing interior with blue tones and crisp daylight",
                "cues": ("시원", "청량", "서늘", "차가운", "쿨톤", "cool", "refreshing", "crisp", "icy"),
            },
        ),
    },
    {
        "id": "brightness",
        "name_ko": "밝기",
        "poles": (
            {
                "id": "bright",
                "name_ko": "밝은",
                "anchor": "a bright sunlit airy interior filled with daylight",
                "cues": ("밝", "화사", "햇살", "채광", "빛이 많은", "bright", "sunlit", "luminous"),
            },
            {
                "id": "dark",
                "name_ko": "어두운",
                "anchor": "a dark moody dramatic interior with deep shadows",
                "cues": ("어둡", "어두운", "무디", "딥한", "그림자", "dark", "moody", "dramatic", "shadowy"),
            },
        ),
    },
    {
        "id": "color",
        "name_ko": "색감",
        "poles": (
            {
                "id": "muted",
                "name_ko": "차분한",
                "anchor": "a calm muted neutral monochrome interior with low saturation",
                "cues": ("차분", "무채색", "저채도", "뉴트럴", "모노톤", "muted", "neutral", "monochrome"),
            },
            {
                "id": "colorful",
                "name_ko": "컬러풀한",
                "anchor": "a vivid colorful playful interior with bold saturated colors",
                "cues": ("컬러풀", "알록달록", "강렬한 색", "고채도", "비비드", "colorful", "vivid", "bold color"),
            },
        ),
    },
    {
        "id": "density",
        "name_ko": "공간 밀도",
        "poles": (
            {
                "id": "minimal",
                "name_ko": "미니멀한",
                "anchor": "a sparse minimalist uncluttered interior with plenty of empty space",
                "cues": ("미니멀", "단정", "깔끔", "여백", "절제", "minimal", "uncluttered", "sparse"),
            },
            {
                "id": "maximal",
                "name_ko": "맥시멀한",
                "anchor": "a richly decorated maximalist interior full of objects patterns and art",
                "cues": ("맥시멀", "화려", "장식적", "소품이 많은", "풍성", "maximal", "decorated", "ornate"),
            },
        ),
    },
    {
        "id": "material",
        "name_ko": "재질감",
        "poles": (
            {
                "id": "soft",
                "name_ko": "부드러운",
                "anchor": "a soft tactile interior with fabric cushions rugs and rounded textures",
                "cues": ("부드러운", "패브릭", "포근한 천", "쿠션", "러그", "soft", "fabric", "textile"),
            },
            {
                "id": "hard",
                "name_ko": "차가운 재질",
                "anchor": "a sleek hard interior with glass steel chrome concrete and metal",
                "cues": ("금속", "메탈", "유리", "스틸", "크롬", "콘크리트", "glass", "metal", "steel", "chrome"),
            },
        ),
    },
    {
        "id": "nature",
        "name_ko": "자연성",
        "poles": (
            {
                "id": "natural",
                "name_ko": "자연적인",
                "anchor": "an organic natural interior with wood plants stone and earthy materials",
                "cues": ("자연", "우드", "원목", "식물", "플랜트", "돌", "organic", "natural", "wood", "plant"),
            },
            {
                "id": "urban",
                "name_ko": "도시적인",
                "anchor": "a polished urban metropolitan interior with artificial modern materials",
                "cues": ("도시적", "어반", "세련된 도시", "메트로", "urban", "metropolitan", "city"),
            },
        ),
    },
    {
        "id": "era",
        "name_ko": "시대감",
        "poles": (
            {
                "id": "vintage",
                "name_ko": "빈티지한",
                "anchor": "a nostalgic vintage retro classic interior with antique furniture",
                "cues": ("빈티지", "레트로", "고전적", "앤티크", "클래식", "vintage", "retro", "antique", "classic"),
            },
            {
                "id": "futuristic",
                "name_ko": "미래적인",
                "anchor": "a futuristic high tech interior with innovative forms and LED lighting",
                "cues": ("미래적", "퓨처", "사이버", "하이테크", "첨단", "futuristic", "cyber", "high tech"),
            },
        ),
    },
    {
        "id": "formality",
        "name_ko": "격식",
        "poles": (
            {
                "id": "casual",
                "name_ko": "편안한",
                "anchor": "a relaxed casual lived-in everyday interior",
                "cues": ("편안", "캐주얼", "일상적", "소박", "relaxed", "casual", "lived-in"),
            },
            {
                "id": "luxury",
                "name_ko": "고급스러운",
                "anchor": "an elegant luxurious formal hotel-like interior with premium finishes",
                "cues": ("고급", "럭셔리", "호텔", "우아", "격식", "luxury", "elegant", "formal", "premium"),
            },
        ),
    },
    {
        "id": "shape",
        "name_ko": "형태",
        "poles": (
            {
                "id": "curved",
                "name_ko": "곡선적인",
                "anchor": "an interior with soft organic curves rounded furniture and arches",
                "cues": ("곡선", "둥근", "라운드", "아치", "curved", "rounded", "organic shape", "arch"),
            },
            {
                "id": "geometric",
                "name_ko": "직선적인",
                "anchor": "an angular geometric structured interior with sharp straight lines",
                "cues": ("직선", "각진", "기하학", "구조적", "angular", "geometric", "straight line"),
            },
        ),
    },
    {
        "id": "openness",
        "name_ko": "공간감",
        "poles": (
            {
                "id": "cozy",
                "name_ko": "아늑한",
                "anchor": "an intimate enclosed compact cozy interior",
                "cues": ("아늑", "감싸는", "작고 포근", "밀도감", "intimate", "enclosed", "compact"),
            },
            {
                "id": "open",
                "name_ko": "개방적인",
                "anchor": "a spacious open airy interior with a wide view and high ceiling",
                "cues": ("개방", "탁 트인", "넓은", "높은 천장", "공간감", "open", "airy", "spacious", "wide", "high ceiling"),
            },
        ),
    },
)


def _cue_positions(text: str, cue: str) -> list[int]:
    cue_l = cue.casefold()
    if cue_l.isascii() and cue_l.replace(" ", "").isalpha():
        return [m.start() for m in re.finditer(rf"\b{re.escape(cue_l)}\b", text)]
    positions: list[int] = []
    start = 0
    while True:
        pos = text.find(cue_l, start)
        if pos < 0:
            break
        positions.append(pos)
        start = pos + max(1, len(cue_l))
    return positions


def detect_semantic_axes(text: str) -> list[dict]:
    """문장에서 감각 축별로 가장 강하게 드러난 한쪽 극을 반환한다."""
    normalized = text.casefold()
    detected: list[dict] = []

    for axis in SEMANTIC_AXES:
        pole_matches = []
        for pole in axis["poles"]:
            matches = []
            for cue in pole["cues"]:
                for pos in _cue_positions(normalized, cue):
                    # 긴 복합 표현을 단일 단어보다 조금 더 강한 단서로 본다.
                    strength = 1.0 + min(len(cue) / 20.0, 0.5)
                    matches.append({"cue": cue, "position": pos, "strength": strength})
            pole_matches.append(matches)

        if not any(pole_matches):
            continue

        scores = [sum(m["strength"] for m in matches) for matches in pole_matches]
        if scores[0] == scores[1]:
            # "따뜻하기보다는 시원한"처럼 양쪽 표현이 있으면 뒤의 표현을 우선한다.
            latest = [max((m["position"] for m in matches), default=-1) for matches in pole_matches]
            selected_idx = int(latest[1] > latest[0])
        else:
            selected_idx = int(scores[1] > scores[0])

        opposite_idx = 1 - selected_idx
        selected = axis["poles"][selected_idx]
        opposite = axis["poles"][opposite_idx]
        detected.append(
            {
                "axis_id": axis["id"],
                "axis_name_ko": axis["name_ko"],
                "pole_id": selected["id"],
                "pole_name_ko": selected["name_ko"],
                "anchor": selected["anchor"],
                "opposite_anchor": opposite["anchor"],
                "matched_cues": [m["cue"] for m in pole_matches[selected_idx]],
                "strength": min(1.0, 0.55 + 0.15 * scores[selected_idx]),
            }
        )

    return detected
