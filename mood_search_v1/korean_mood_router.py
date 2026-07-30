"""한국어 표현을 현재 CLIP 검색이 이해하는 영문 무드 앵커로 연결한다."""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


# 단어 하나뿐 아니라 비유·상황 표현도 찾을 수 있도록 개념마다 예문을 둔다.
MOOD_CONCEPTS = (
    {
        "id": "cute_pastel",
        "name_ko": "파스텔",
        "anchor": "a cute soft pastel interior with low saturation pink blue and cream colors",
        "library_mood_ids": ("cute_pastel",),
        "aliases": ("파스텔", "연한 색", "솜사탕", "베이비핑크", "연분홍", "연보라", "pastel", "cute pastel"),
        "examples": (
            "솜사탕처럼 부드럽고 사랑스러운 색감의 방",
            "분홍색 하늘색 연보라색이 은은하게 섞인 공간",
            "채도가 낮은 연하고 귀여운 색상의 인테리어",
            "봄날처럼 화사하고 여린 색감",
        ),
    },
    {
        "id": "cool_airy",
        "name_ko": "시원하고 개방적인",
        "anchor": "a cool refreshing bright airy open interior with blue tones and crisp daylight",
        "aliases": ("시원", "청량", "상쾌", "탁 트인", "개방감", "쿨톤", "바닷바람", "cool airy"),
        "examples": (
            "바닷바람이 느껴지는 맑고 상쾌한 공간",
            "여름처럼 시원하고 탁 트인 블루톤 인테리어",
            "채광이 좋고 넓게 열린 깨끗한 방",
            "차갑고 투명한 공기가 느껴지는 공간",
        ),
        "axis_id": "temperature",
        "pole_id": "cool",
    },
    {
        "id": "warm_cozy",
        "name_ko": "따뜻하고 아늑한",
        "anchor": "a warm cozy intimate interior with amber light soft fabric and comforting colors",
        "library_mood_ids": ("warm_cozy",),
        "aliases": ("따뜻", "포근", "아늑", "온화", "감싸는", "난로", "warm cozy"),
        "examples": (
            "몸을 감싸는 것처럼 편안하고 포근한 방",
            "겨울 난로 옆처럼 따뜻한 분위기",
            "노란 조명과 패브릭이 있는 아늑한 공간",
            "편안하게 오래 머물고 싶은 온화한 인테리어",
        ),
        "axis_id": "temperature",
        "pole_id": "warm",
    },
    {
        "id": "bright_airy",
        "name_ko": "밝고 화사한",
        "anchor": "a bright luminous sunlit airy interior filled with natural daylight",
        "aliases": ("밝", "화사", "햇살", "채광", "빛이 많은", "bright airy"),
        "examples": (
            "아침 햇살이 가득 들어오는 밝은 방",
            "창이 크고 자연광이 풍부한 화사한 공간",
            "눈부시게 깨끗하고 환한 분위기",
        ),
        "axis_id": "brightness",
        "pole_id": "bright",
    },
    {
        "id": "dark_moody",
        "name_ko": "어둡고 무디한",
        "anchor": "a dark moody dramatic interior with deep colors and cinematic shadows",
        "aliases": ("어둡", "무디", "딥한", "그림자", "밤 같은", "dark moody"),
        "examples": (
            "깊은 밤처럼 어둡고 분위기 있는 공간",
            "그림자가 짙고 영화처럼 극적인 인테리어",
            "검정과 짙은 색상이 중심인 차분한 방",
        ),
        "axis_id": "brightness",
        "pole_id": "dark",
    },
    {
        "id": "minimal",
        "name_ko": "미니멀",
        "anchor": "a clean sparse minimalist uncluttered interior with plenty of empty space",
        "library_mood_ids": ("minimal_white", "monochrome_minimal"),
        "aliases": ("미니멀", "단정", "깔끔", "여백", "절제", "정돈", "minimal", "minimal white"),
        "examples": (
            "물건이 적고 정돈되어 여백이 많은 방",
            "군더더기 없이 단순하고 깔끔한 공간",
            "필요한 가구만 놓인 절제된 인테리어",
        ),
        "axis_id": "density",
        "pole_id": "minimal",
    },
    {
        "id": "maximal",
        "name_ko": "화려하고 풍성한",
        "anchor": "a colorful richly decorated maximalist interior full of patterns objects and art",
        "aliases": ("맥시멀", "화려", "장식적", "소품이 많은", "풍성", "패턴이 많은", "maximal"),
        "examples": (
            "소품과 그림이 가득한 풍성한 공간",
            "다양한 패턴과 장식이 어우러진 화려한 방",
            "볼거리와 개성이 넘치는 맥시멀 인테리어",
        ),
        "axis_id": "density",
        "pole_id": "maximal",
    },
    {
        "id": "natural_wood",
        "name_ko": "내추럴 우드",
        "anchor": "an organic natural interior with warm wood plants stone and earthy materials",
        "library_mood_ids": ("natural_wood",),
        "aliases": ("우드", "원목", "나무", "자연", "흙", "돌", "숲 같은", "natural wood"),
        "examples": (
            "숲속에 있는 것처럼 나무와 식물이 많은 방",
            "원목 가구와 자연 소재가 중심인 편안한 공간",
            "흙과 돌과 나무의 색을 사용한 인테리어",
        ),
        "axis_id": "nature",
        "pole_id": "natural",
    },
    {
        "id": "plant_green",
        "name_ko": "플랜트 그린",
        "anchor": "a lush plant-filled green biophilic interior with abundant indoor plants",
        "library_mood_ids": ("plant_green",),
        "aliases": ("식물", "플랜트", "초록", "그린", "정원 같은", "싱그러운", "plant green"),
        "examples": (
            "실내 정원처럼 초록 식물이 가득한 공간",
            "싱그러운 잎과 화분이 많은 자연 친화적인 방",
            "초록색 식물이 포인트가 되는 인테리어",
        ),
    },
    {
        "id": "urban_metal",
        "name_ko": "도시적인 메탈",
        "anchor": "a sleek urban interior with glass steel chrome concrete and polished metal",
        "aliases": ("도시적", "어반", "메탈", "금속", "유리", "스틸", "크롬", "콘크리트", "urban metal"),
        "examples": (
            "도시의 빌딩처럼 유리와 금속이 많은 공간",
            "차가운 스틸과 콘크리트가 중심인 세련된 방",
            "반짝이는 크롬과 직선이 강조된 인테리어",
        ),
        "axis_id": "material",
        "pole_id": "hard",
    },
    {
        "id": "vintage_retro",
        "name_ko": "빈티지 레트로",
        "anchor": "a nostalgic vintage retro interior with antique furniture and aged colors",
        "library_mood_ids": ("vintage_retro",),
        "aliases": ("빈티지", "레트로", "옛날", "복고", "앤티크", "고전적", "vintage", "retro", "vintage retro"),
        "examples": (
            "오래된 영화 속에 나오는 것 같은 방",
            "세월의 흔적이 있는 가구와 복고풍 색감",
            "과거 시대의 소품과 앤티크 가구가 있는 공간",
        ),
        "axis_id": "era",
        "pole_id": "vintage",
    },
    {
        "id": "futuristic",
        "name_ko": "미래적인",
        "anchor": "a futuristic high tech cyber interior with innovative forms and LED lighting",
        "aliases": ("미래적", "퓨처", "사이버", "하이테크", "첨단", "우주선", "futuristic"),
        "examples": (
            "우주선 내부처럼 미래적이고 첨단적인 공간",
            "간접 LED 조명과 새로운 형태가 강조된 방",
            "공상 과학 영화 같은 하이테크 인테리어",
        ),
        "axis_id": "era",
        "pole_id": "futuristic",
    },
    {
        "id": "luxury_modern",
        "name_ko": "럭셔리 모던",
        "anchor": "an elegant luxurious modern hotel-like interior with premium finishes",
        "library_mood_ids": ("luxury_modern",),
        "aliases": ("고급", "럭셔리", "호텔", "우아", "격식", "프리미엄", "luxury", "luxury modern"),
        "examples": (
            "고급 호텔 라운지처럼 우아하고 세련된 공간",
            "비싼 소재와 정교한 마감이 돋보이는 방",
            "격식 있고 품격 있는 현대적인 인테리어",
        ),
        "axis_id": "formality",
        "pole_id": "luxury",
    },
    {
        "id": "monochrome",
        "name_ko": "모노톤",
        "anchor": "a calm monochrome neutral interior with black white grey and low saturation",
        "library_mood_ids": ("monochrome_minimal",),
        "aliases": ("모노톤", "무채색", "흑백", "검정과 흰색", "회색조", "뉴트럴", "monochrome"),
        "examples": (
            "검정 흰색 회색만 사용한 차분한 방",
            "색을 절제한 무채색 중심의 인테리어",
            "흑백 사진처럼 정돈되고 중성적인 공간",
        ),
        "axis_id": "color",
        "pole_id": "muted",
    },
    {
        "id": "modern_grey",
        "name_ko": "모던 그레이",
        "anchor": "a modern grey contemporary interior with clean lines and sophisticated neutral tones",
        "library_mood_ids": ("modern_grey",),
        "aliases": ("모던 그레이", "회색 모던", "세련된 회색", "modern grey"),
        "examples": (
            "회색과 중성색을 사용한 현대적인 공간",
            "깔끔한 직선과 그레이 색감의 세련된 방",
            "도시적이고 차분한 현대식 인테리어",
        ),
    },
)


def _documents() -> tuple[list[str], list[int]]:
    docs: list[str] = []
    owners: list[int] = []
    for idx, concept in enumerate(MOOD_CONCEPTS):
        for text in (*concept["aliases"], *concept["examples"]):
            docs.append(text)
            owners.append(idx)
    return docs, owners


@lru_cache(maxsize=1)
def _router_index():
    docs, owners = _documents()
    # 한국어 어미가 달라져도 일부 형태가 겹치도록 문자 n-gram을 사용한다.
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 5), sublinear_tf=True)
    matrix = vectorizer.fit_transform(docs)
    return vectorizer, matrix, owners


def route_korean_mood(text: str, threshold: float = 0.18, top_k: int = 3) -> list[dict]:
    normalized = " ".join(text.strip().casefold().split())
    if not normalized:
        return []

    vectorizer, matrix, owners = _router_index()
    query = vectorizer.transform([normalized])
    example_scores = (matrix @ query.T).toarray().ravel()
    concept_scores = np.zeros(len(MOOD_CONCEPTS), dtype=np.float32)

    for score, owner in zip(example_scores, owners):
        concept_scores[owner] = max(concept_scores[owner], float(score))

    exact_matches: set[int] = set()
    for idx, concept in enumerate(MOOD_CONCEPTS):
        if any(alias.casefold() in normalized for alias in concept["aliases"]):
            concept_scores[idx] = max(concept_scores[idx], 1.0)
            exact_matches.add(idx)

    ranked = np.argsort(concept_scores)[::-1]
    selected: list[dict] = []
    used_axes: set[str] = set()
    best_score = float(concept_scores[ranked[0]]) if len(ranked) else 0.0

    for idx_raw in ranked:
        idx = int(idx_raw)
        score = float(concept_scores[idx])
        if score < threshold:
            break
        # 약한 후보를 억지로 섞지 않고 최상위 의미와 가까운 개념만 사용한다.
        if idx not in exact_matches and score < best_score * 0.72:
            continue
        concept = MOOD_CONCEPTS[idx]
        axis_id = concept.get("axis_id")
        if axis_id and axis_id in used_axes:
            continue
        if axis_id:
            used_axes.add(axis_id)
        selected.append(
            {
                "id": concept["id"],
                "name_ko": concept["name_ko"],
                "anchor": concept["anchor"],
                "score": score,
                "match_type": "exact" if idx in exact_matches else "semantic",
                "axis_id": axis_id,
                "pole_id": concept.get("pole_id"),
                "library_mood_ids": list(concept.get("library_mood_ids", ())),
            }
        )
        if len(selected) >= top_k:
            break

    return selected
