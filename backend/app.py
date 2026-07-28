import json
import os
import re
import sys
import uuid

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from ultralytics import YOLO

import ai_backend
import database


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from model2 import interior_to_floorplan as floorplan_model
from model2 import rule_based_svg
from model1 import search as mood_search
from shared.config import IMAGE_ROOT as MOOD_IMAGE_ROOT


# 실행 위치와 관계없이 프로젝트 루트의 .env 파일을 읽는다.
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


app = Flask(
    __name__,
    template_folder=os.path.join(
        FRONTEND_DIR,
        "templates",
    ),
    static_folder=os.path.join(
        FRONTEND_DIR,
        "static",
    ),
)

app.secret_key = os.getenv(
    "FLASK_SECRET_KEY",
    "dev-secret-key-change-in-production",
)

app.json.ensure_ascii = False


UPLOAD_DIR = os.path.join(
    FRONTEND_DIR,
    "static",
    "uploads",
)

GENERATED_DIR = os.path.join(
    FRONTEND_DIR,
    "static",
    "generated",
)

PRODUCT_CACHE_DIR = os.path.join(
    GENERATED_DIR,
    "product_cache",
)

ALLOWED_EXT = {
    "jpg",
    "jpeg",
    "png",
}

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True,
)

os.makedirs(
    GENERATED_DIR,
    exist_ok=True,
)

os.makedirs(
    PRODUCT_CACHE_DIR,
    exist_ok=True,
)


# 새로 구매할 수 있는 가구 종류
PURCHASE_LABELS = {
    "chair": "의자",
    "desk": "책상",
    "table": "테이블",
    "shelf": "선반",
    "cabinet": "수납장",
    "lamp": "조명",
    "rug": "러그",
    "plant": "식물",
}


# 기존 AJAX 추천 API에서 사용하는 ID
PURCHASE_ITEM_IDS = {
    "chair": "chair-001",
    "desk": "desk-001",
    "table": "table-001",
    "shelf": "shelf-001",
    "cabinet": "cabinet-001",
    "lamp": "lamp-001",
    "rug": "rug-001",
    "plant": "plant-001",
}


# 네이버 쇼핑 검색에 사용할 기본 검색어
PRODUCT_SEARCH_QUERIES = {
    "chair": "인테리어 의자",
    "desk": "인테리어 책상",
    "table": "인테리어 테이블",
    "shelf": "인테리어 선반",
    "cabinet": "인테리어 수납장",
    "lamp": "인테리어 조명",
    "rug": "인테리어 러그",
    "plant": "인테리어 식물",
}


# 아직 Model2 자동 배치 기능이 없으므로
# 새 가구를 평면도에 표시할 때 사용할 임시 좌표
PURCHASE_POSITIONS = [
    (0.24, 0.24),
    (0.50, 0.24),
    (0.76, 0.24),
    (0.24, 0.52),
    (0.50, 0.52),
    (0.76, 0.52),
    (0.36, 0.78),
    (0.64, 0.78),
]


# ──────────────────────────────────────────────────────
# 상품 실측 크기 추출
#
# 네이버 쇼핑 API에는 크기 필드가 없다(title/lprice/mallName/category만
# 준다). 다만 가구 상품은 제목에 치수를 적는 관행이 있어 거기서 뽑는다.
#   "...테이블 4인용 D750XW1200XH720"  -> 1200 x 750 mm
#   "[두닷] 콰트로 책상 1800x800mm"      -> 1800 x  800 mm
#   "...러그 ... 180x220cm"            -> 1800 x 2200 mm
#   "...침대 프레임 SS(슈퍼싱글)"          -> 1100 x 2000 mm (규격표)
#
# 실측(상품 80개): 이 방식으로 31%에서 치수를 얻는다.
# 침대 100% / 책상 60% / 러그 50% / 선반 30%, 의자·테이블은 0%.
# 못 찾으면 None을 돌려주고 렌더러 표준 크기를 그대로 쓴다.
# ──────────────────────────────────────────────────────

# 침대·매트리스 규격명 -> (가로mm, 세로mm).
# 긴 이름이 짧은 이름을 포함하므로("슈퍼싱글" ⊃ "싱글") 검사 순서가 중요하다.
BED_SIZE_SPECS = {
    "라지킹": (1800, 2000),
    "슈퍼싱글": (1100, 2000),
    "패밀리": (2000, 2000),
    "싱글": (1000, 2000),
    "더블": (1400, 2000),
    "퀸": (1500, 2000),
    "킹": (1600, 2000),
    "ss": (1100, 2000),
    "sss": (1100, 2000),
}

# 방 한 변으로 볼 수 있는 현실적인 가구 치수 범위(mm)
MIN_FURNITURE_MM = 150
MAX_FURNITURE_MM = 4000


def _mm_pair_ok(a, b):
    return (
        MIN_FURNITURE_MM <= a <= MAX_FURNITURE_MM
        and MIN_FURNITURE_MM <= b <= MAX_FURNITURE_MM
    )


def parse_product_dimensions(title):
    """상품 제목에서 (가로mm, 세로mm)를 추출한다.

    세로를 못 구하면 d_mm은 None이다(가로만 반영).
    아무것도 못 찾으면 None.
    """
    if not title:
        return None

    text = clean_html(str(title))

    # 1) D750XW1200XH720 — 축 라벨이 붙은 표기
    match = re.search(
        r"[Dd]\s*(\d{2,4})\s*[xX*×]\s*[Ww]\s*(\d{2,4})",
        text,
    )
    if match:
        depth, width = (
            int(match.group(1)),
            int(match.group(2)),
        )
        if _mm_pair_ok(width, depth):
            return {
                "w_mm": width,
                "d_mm": depth,
                "raw": match.group(0),
            }

    match = re.search(
        r"[Ww]\s*(\d{2,4})\s*[xX*×]\s*[Dd]\s*(\d{2,4})",
        text,
    )
    if match:
        width, depth = (
            int(match.group(1)),
            int(match.group(2)),
        )
        if _mm_pair_ok(width, depth):
            return {
                "w_mm": width,
                "d_mm": depth,
                "raw": match.group(0),
            }

    # 2) 1800x800mm / 180x220cm — 라벨 없는 두 축
    match = re.search(
        r"(\d{2,4})\s*[xX*×]\s*(\d{2,4})\s*(cm|CM|㎝|mm|MM|㎜)?",
        text,
    )
    if match:
        first, second = (
            int(match.group(1)),
            int(match.group(2)),
        )
        unit = (match.group(3) or "").lower()

        # 단위가 없으면 값 크기로 판단한다. 가구 치수를 세 자리 미만으로
        # 적으면 cm 관행(180x220), 세 자리 이상이면 mm(1800x800).
        if unit in ("cm", "㎝") or (
            not unit and max(first, second) < 300
        ):
            first, second = first * 10, second * 10

        if _mm_pair_ok(first, second):
            return {
                "w_mm": first,
                "d_mm": second,
                "raw": match.group(0),
            }

    # 3) 침대 규격명 — 긴 이름부터 검사(부분 문자열 오인 방지)
    lowered = text.lower()
    for name in sorted(
        BED_SIZE_SPECS,
        key=len,
        reverse=True,
    ):
        if name in lowered:
            width, depth = BED_SIZE_SPECS[name]
            return {
                "w_mm": width,
                "d_mm": depth,
                "raw": name,
            }

    # 4) 1800mm — 한 축만 적힌 경우. 가로로 보고 세로는 표준 비율에 맡긴다.
    match = re.search(
        r"(\d{3,4})\s*(?:mm|MM|㎜)\b",
        text,
    )
    if match:
        width = int(match.group(1))
        if MIN_FURNITURE_MM <= width <= 3000:
            return {
                "w_mm": width,
                "d_mm": None,
                "raw": match.group(0),
            }

    # 5) 단위 없는 단독 숫자 — 가구 업계는 폭을 mm로 그냥 적는다.
    #    "유리쇼케이스 600", "벽선반 400", "마켓비 책상 1100"
    #    후보가 여러 개면 어느 축인지 알 수 없으므로 쓰지 않는다.
    solo = [
        int(v)
        for v in re.findall(
            r"(?<![0-9A-Za-z])"
            r"([3-9]\d{2}|1\d{3}|2[0-4]\d{2})"
            r"(?![0-9A-Za-z])",
            text,
        )
    ]
    solo = [
        v
        for v in solo
        if 300 <= v <= 2400
    ]
    if len(set(solo)) == 1:
        return {
            "w_mm": solo[0],
            "d_mm": None,
            "raw": f"{solo[0]}mm",
        }

    return None


# 네이버 category4는 꽤 구체적이다("사이드테이블", "일자형 책상",
# "인테리어의자"). 제목에 치수가 없을 때 이 분류로 현실적인 표준
# 크기를 준다. 특히 "사이드테이블"을 식탁 크기로 그리던 오류를 막는다.
# 값은 (가로mm, 세로mm).
CATEGORY_STD_SIZE_MM = {
    "사이드테이블": (450, 450),
    "좌식테이블": (800, 600),
    "접이식테이블": (800, 600),
    "식탁테이블": (1200, 800),
    "인테리어의자": (450, 500),
    "식탁의자": (450, 500),
    "사무용의자": (600, 600),
    "스툴": (400, 400),
    "일자형 책상": (1200, 600),
    "ㄱ자형 책상": (1400, 1400),
    "학생용 책상": (1000, 600),
    "컴퓨터 책상": (1200, 600),
    "장식장": (900, 400),
    "서랍장": (800, 450),
    "옷장": (1000, 600),
    "책장": (800, 300),
    "벽선반": (600, 200),
    "선반": (800, 300),
    "협탁": (450, 400),
    # category4가 비어 있고 category3만 오는 경우도 흔하다.
    "수납장": (800, 400),
    "러그": (1500, 2000),
    "카페트": (1500, 2000),
    "침대": (1400, 2000),
    "소파": (1800, 900),
    "테이블": (1000, 600),
    "의자": (450, 500),
    "책상": (1200, 600),
    # 조명은 바닥 면적이 작다. 스탠드/펜던트 구분 없이 보수적으로.
    "인테리어조명": (350, 350),
    "조명": (350, 350),
    "스탠드": (400, 400),
    "장스탠드": (400, 400),
    "거울": (500, 150),
    "화분": (300, 300),
    "관엽식물": (350, 350),
    "공기정화식물": (350, 350),
    "선인장": (200, 200),
    "다육식물": (200, 200),
}


def category_std_size_mm(product):
    """category3/4로 표준 크기를 추정한다. 모르면 None."""
    for key in ("category4", "category3"):
        name = str(
            product.get(key) or ""
        ).strip()
        if name in CATEGORY_STD_SIZE_MM:
            width, depth = (
                CATEGORY_STD_SIZE_MM[name]
            )
            return {
                "w_mm": width,
                "d_mm": depth,
                "raw": name,
            }
    return None


def product_size_fractions(
    title,
    room_width_m,
    room_depth_m,
    product=None,
):
    """상품 치수를 방 크기 대비 0~1 비율로 바꾼다.

    제목에서 치수를 못 찾으면 네이버 category로 표준 크기를 추정한다.
    방 실측(m)이 없으면 비율을 계산할 기준이 없으므로 None을 돌려준다.
    """
    if not room_width_m or not room_depth_m:
        return None

    try:
        room_w_mm = float(room_width_m) * 1000
        room_d_mm = float(room_depth_m) * 1000
    except (TypeError, ValueError):
        return None

    if room_w_mm <= 0 or room_d_mm <= 0:
        return None

    dims = parse_product_dimensions(title)

    # 제목에 없으면 카테고리로 추정한다(정확도는 낮지만 타입 표준보다 낫다).
    if not dims and product:
        dims = category_std_size_mm(product)

    if not dims:
        return None

    w_frac = dims["w_mm"] / room_w_mm
    d_frac = (
        dims["d_mm"] / room_d_mm
        if dims["d_mm"]
        else None
    )

    # 방을 넘어서는 값은 파싱 오류로 본다(예: 상품코드를 치수로 오인).
    if w_frac > 0.9 or (d_frac and d_frac > 0.9):
        return None

    return {
        "w": round(w_frac, 4),
        "h": round(d_frac, 4) if d_frac else 0.0,
        "raw": dims["raw"],
    }


# ──────────────────────────────────────────────────────
# 공통 유틸리티
# ──────────────────────────────────────────────────────
def allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in ALLOWED_EXT
    )


def clean_html(text):
    """
    네이버 쇼핑 상품명에 포함된
    HTML 태그를 제거한다.
    """

    if text is None:
        return ""

    return re.sub(
        r"<.*?>",
        "",
        str(text),
    )


def safe_int(
    value,
    default=0,
):
    try:
        if value is None or value == "":
            return default

        return int(value)

    except (
        ValueError,
        TypeError,
    ):
        return default


def save_json_cache(
    prefix,
    data,
):
    """
    상품 검색 결과처럼 크기가 큰 데이터를
    Flask 세션 쿠키 대신 JSON 파일로 저장한다.
    """

    filename = (
        f"{prefix}_"
        f"{uuid.uuid4().hex[:12]}"
        ".json"
    )

    file_path = os.path.join(
        PRODUCT_CACHE_DIR,
        filename,
    )

    with open(
        file_path,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return filename


def load_json_cache(
    filename,
    default=None,
):
    """
    저장된 상품 JSON 캐시 파일을 읽는다.
    """

    if default is None:
        default = {}

    if not filename:
        return default

    safe_filename = os.path.basename(
        filename
    )

    file_path = os.path.join(
        PRODUCT_CACHE_DIR,
        safe_filename,
    )

    if not os.path.exists(
        file_path
    ):
        return default

    try:
        with open(
            file_path,
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(
                file
            )

    except (
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(
            "[product-cache] "
            f"캐시 읽기 실패: {exc}"
        )

        return default


def remove_cache_file(filename):
    """
    더 이상 사용하지 않는 상품 캐시를 삭제한다.
    """

    if not filename:
        return

    safe_filename = os.path.basename(
        filename
    )

    file_path = os.path.join(
        PRODUCT_CACHE_DIR,
        safe_filename,
    )

    try:
        if os.path.exists(
            file_path
        ):
            os.remove(
                file_path
            )

    except OSError as exc:
        print(
            "[product-cache] "
            f"캐시 삭제 실패: {exc}"
        )


def build_product_query(item_type):
    """
    사용자가 입력한 무드 문장에서
    스타일 키워드를 추출해
    네이버 쇼핑 검색어에 반영한다.
    """

    base_query = (
        PRODUCT_SEARCH_QUERIES.get(
            item_type,
            item_type,
        )
    )

    prompt_text = str(
        session.get(
            "mood_prompt",
            "",
        )
    )

    tags = session.get(
        "style_tags",
        [],
    )

    combined_text = (
        prompt_text
        + " "
        + " ".join(
            str(tag)
            for tag in tags
        )
    ).lower()

    keyword_map = [
        (
            (
                "원목",
                "우드",
                "wood",
                "wooden",
            ),
            "원목",
        ),
        (
            (
                "미니멀",
                "minimal",
            ),
            "미니멀",
        ),
        (
            (
                "모던",
                "modern",
            ),
            "모던",
        ),
        (
            (
                "빈티지",
                "vintage",
                "retro",
                "레트로",
            ),
            "빈티지",
        ),
        (
            (
                "북유럽",
                "nordic",
                "scandinavian",
            ),
            "북유럽",
        ),
        (
            (
                "베이지",
                "beige",
            ),
            "베이지",
        ),
        (
            (
                "화이트",
                "white",
            ),
            "화이트",
        ),
        (
            (
                "내추럴",
                "natural",
            ),
            "내추럴",
        ),
        (
            (
                "블랙",
                "black",
            ),
            "블랙",
        ),
    ]

    style_keywords = []

    for aliases, output_word in keyword_map:
        if any(
            alias in combined_text
            for alias in aliases
        ):
            if output_word not in style_keywords:
                style_keywords.append(
                    output_word
                )

    # 검색어가 너무 길어지지 않도록
    # 스타일 키워드는 최대 두 개만 넣는다.
    return " ".join(
        style_keywords[:2]
        + [base_query]
    )


def search_naver_shopping(
    query,
    display=5,
):
    """
    네이버 쇼핑 검색 API를 호출한다.
    """

    client_id = os.getenv(
        "NAVER_CLIENT_ID"
    )

    client_secret = os.getenv(
        "NAVER_CLIENT_SECRET"
    )

    if not client_id or not client_secret:
        raise ValueError(
            ".env에서 NAVER_CLIENT_ID 또는 "
            "NAVER_CLIENT_SECRET을 "
            "불러오지 못했습니다."
        )

    url = (
        "https://openapi.naver.com/"
        "v1/search/shop.json"
    )

    headers = {
        "X-Naver-Client-Id": (
            client_id
        ),
        "X-Naver-Client-Secret": (
            client_secret
        ),
    }

    params = {
        "query": query,
        "display": display,
        "start": 1,
        "sort": "sim",
        "exclude": (
            "used:rental:cbshop"
        ),
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )

    if response.status_code != 200:
        print(
            "네이버 API 요청 실패:",
            response.status_code,
            response.text,
        )

        response.raise_for_status()

    data = response.json()
    products = []

    for item in data.get(
        "items",
        [],
    ):
        products.append(
            {
                "title": clean_html(
                    item.get("title")
                ),
                "link": item.get(
                    "link"
                ),
                "image": item.get(
                    "image"
                ),
                "price": safe_int(
                    item.get("lprice")
                ),
                "shop": item.get(
                    "mallName"
                ),
                "brand": item.get(
                    "brand"
                ),
                "category1": item.get(
                    "category1"
                ),
                "category2": item.get(
                    "category2"
                ),
                "category3": item.get(
                    "category3"
                ),
                "category4": item.get(
                    "category4"
                ),
            }
        )

    return products


def translate_furniture_label(
    item_type,
    original_label,
    fallback_number,
):
    """
    Model1이 반환한 영어 가구 이름을
    화면에 표시할 한글 이름으로 변환한다.
    """

    type_names = {
        "bed": "침대",
        "single_bed": "싱글 침대",
        "desk": "책상",
        "chair": "의자",
        "floor_chair": "좌식 의자",
        "stool": "스툴",
        "table": "테이블",
        "low_table": "낮은 테이블",
        "nightstand": "협탁",
        "side_table": "협탁",
        "tv_stand": "TV장",
        "shelf": "선반",
        "cabinet": "수납장",
        "dresser": "서랍장",
        "wardrobe": "옷장",
        "rug": "러그",
        "mirror": "거울",
        "lamp": "조명",
        "table_lamp": "탁상 조명",
        "floor_lamp": "스탠드 조명",
        "plant": "식물",
        "sofa": "소파",
        "couch": "소파",
        "unknown": "기타 물건",
    }

    label_aliases = {
        "single bed": "싱글 침대",
        "double bed": "더블 침대",
        "queen bed": "퀸 침대",
        "king bed": "킹 침대",
        "bunk bed": "이층 침대",
        "bed": "침대",
        "nightstand": "협탁",
        "bedside table": "협탁",
        "side table": "협탁",
        "tv stand": "TV장",
        "table lamp": "탁상 조명",
        "desk lamp": "책상 조명",
        "bedside lamp": "침대 조명",
        "floor lamp": "스탠드 조명",
        "pendant lamp": "펜던트 조명",
        "pendant lamps": "펜던트 조명",
        "ceiling lamp": "천장 조명",
        "low table": "낮은 테이블",
        "coffee table": "커피 테이블",
        "dining table": "식탁",
        "round table": "원형 테이블",
        "study desk": "책상",
        "office desk": "책상",
        "desk": "책상",
        "office chair": "사무 의자",
        "armchair": "안락의자",
        "lounge chair": "라운지 의자",
        "chair": "의자",
        "sofa": "소파",
        "couch": "소파",
        "sectional sofa": "코너 소파",
        "corner sofa": "코너 소파",
        "rug": "러그",
        "carpet": "카펫",
        "area rug": "러그",
        "plant": "식물",
        "potted plant": "화분",
        "plant pot": "화분",
        "shelf": "선반",
        "bookshelf": "책장",
        "book shelf": "책장",
        "wall shelf": "벽 선반",
        "shelf unit": "선반",
        "cabinet": "수납장",
        "storage cabinet": "수납장",
        "storage unit": "수납장",
        "room divider": "파티션",
        "room divider cabinet": "파티션 수납장",
        "wardrobe": "옷장",
        "closet": "옷장",
        "dresser": "서랍장",
        "chest of drawers": "서랍장",
        "mirror": "거울",
        "stool": "스툴",
        "ottoman": "오토만",
        "bench": "벤치",
    }

    # 위 표에 없는 조합은 수식어를 떼고 핵심 명사로 판단한다.
    # 예: "white study desk" -> desk -> 책상, "wall grid shelf" -> shelf -> 선반
    noun_names = {
        "bed": "침대",
        "desk": "책상",
        "table": "테이블",
        "chair": "의자",
        "sofa": "소파",
        "couch": "소파",
        "stool": "스툴",
        "shelf": "선반",
        "shelves": "선반",
        "bookcase": "책장",
        "cabinet": "수납장",
        "wardrobe": "옷장",
        "closet": "옷장",
        "dresser": "서랍장",
        "drawers": "서랍장",
        "rug": "러그",
        "carpet": "카펫",
        "mirror": "거울",
        "lamp": "조명",
        "light": "조명",
        "lighting": "조명",
        "plant": "식물",
        "pot": "화분",
        "divider": "파티션",
        "partition": "파티션",
        "nightstand": "협탁",
        "bench": "벤치",
        "ottoman": "오토만",
    }

    label = str(
        original_label or ""
    ).strip()

    lower_label = (
        label
        .lower()
        .replace(
            "_",
            " ",
        )
    )

    if lower_label in label_aliases:
        return label_aliases[
            lower_label
        ]

    normalized_type = str(
        item_type or "unknown"
    ).lower()

    if (
        not label
        or lower_label
        == normalized_type.replace(
            "_",
            " ",
        )
    ):
        return type_names.get(
            normalized_type,
            f"가구 {fallback_number}",
        )

    # 이미 한글이면 그대로 쓴다.
    if re.search(r"[가-힣]", label):
        return label

    # 수식어가 붙은 영어 라벨은 핵심 명사로 판단한다.
    # ("white study desk" -> desk -> 책상). 뒤에서부터 찾는 이유는
    # 영어가 "수식어 + 명사" 순서라 마지막 명사가 본체이기 때문이다.
    #
    # 단, type이 unknown이면 추정하지 않는다. "desk basket"의 본체는
    # 바구니이고 책상이 아니므로, 명사만 보고 고르면 오역이 된다.
    if normalized_type != "unknown":
        words = re.findall(r"[a-z]+", lower_label)

        for word in reversed(words):
            if word in noun_names:
                return noun_names[word]

    # 끝까지 못 알아보면 타입 한글명으로 떨어진다.
    # 영어를 그대로 내보내지 않는 것이 이 함수의 계약이다.
    return type_names.get(
        normalized_type,
        f"가구 {fallback_number}",
    )


def _mood_results_to_urls(results):
    """
    무드 검색 결과의 파일 경로를
    브라우저에서 볼 수 있는 URL로 바꾼다.
    """

    return [
        {
            "url": url_for(
                "mood_image",
                filename=result["path"],
            ),
            "path": result["path"],
            "score": result["score"],
        }
        for result in results
    ]


# ──────────────────────────────────────────────────────
# HOME / 시작
# ──────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template(
        "index.html"
    )


@app.route("/gallery")
def gallery():
    # 무드 라이브러리(images/final) 사진을 그리드로 보여준다.
    from model1.preprocess import collect_image_paths

    try:
        paths = collect_image_paths(MOOD_IMAGE_ROOT)
    except Exception:
        paths = []
    # /mood-image/<filename> 라우트로 서빙되므로 IMAGE_ROOT 기준 상대경로만 넘긴다.
    images = [
        str(p.relative_to(MOOD_IMAGE_ROOT)).replace("\\", "/")
        for p in paths[:60]  # 첫 화면 과부하 방지로 60장까지만
    ]
    return render_template("gallery.html", images=images, total=len(paths))


@app.route("/my-designs")
def my_designs():
    # 로그인/저장 기능은 아직 없으므로 준비중 안내 페이지.
    return render_template("my_designs.html")


@app.route("/about")
def about():
    # 서비스 소개 정적 페이지.
    return render_template("about.html")


@app.route("/home")
def home():
    """
    로고 클릭용: 진행하던 세션을 지우고 초기 화면(홈)으로 돌아간다.
    (/start 는 세션을 지운 뒤 프롬프트로 가지만, 로고는 홈으로 보낸다.)
    """

    session.clear()

    return redirect(
        url_for("index")
    )


@app.route("/start")
def start():
    """
    이전 세션을 지우고
    새 디자인을 시작한다.
    """

    session.clear()

    return redirect(
        url_for("prompt")
    )


# ──────────────────────────────────────────────────────
# STEP 1: 프롬프트 입력 및 무드 이미지 선택
# ──────────────────────────────────────────────────────
@app.route("/prompt")
def prompt():
    return render_template(
        "prompt.html",
        previews=[],
    )


@app.route(
    "/save-style",
    methods=["POST"],
)
def save_style():
    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    prompt_text = (
        data.get("prompt")
        or ""
    ).strip()

    tags = (
        data.get("tags")
        or []
    )

    selected_image = (
        data.get(
            "selected_image"
        )
        or ""
    ).strip()

    if not prompt_text:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "원하는 인테리어 분위기를 "
                    "입력해 주세요."
                ),
            }
        ), 400

    if not selected_image:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "추천 이미지 중 하나를 "
                    "선택해 주세요."
                ),
            }
        ), 400

    if not isinstance(
        tags,
        list,
    ):
        tags = []

    session["mood_prompt"] = (
        prompt_text
    )

    session["style_tags"] = tags

    session[
        "selected_mood_image"
    ] = selected_image

    return jsonify(
        {
            "ok": True,
            "redirect": url_for(
                "upload"
            ),
        }
    )


@app.route("/mood-search")
def mood_search_api():
    query = (
        request.args.get("q")
        or ""
    ).strip()

    if not query:
        return jsonify(
            {
                "ok": True,
                "results": [],
            }
        )

    try:
        results = (
            mood_search
            .search_by_prompt(
                query,
                top_k=5,
            )
        )

        return jsonify(
            {
                "ok": True,
                "results": (
                    _mood_results_to_urls(
                        results
                    )
                ),
            }
        )

    except Exception as exc:
        print(
            "[mood-search] "
            f"검색 실패: {exc}"
        )

        return jsonify(
            {
                "ok": False,
                "error": (
                    "무드 검색 중 오류가 "
                    "발생했습니다."
                ),
            }
        ), 500


@app.route(
    "/mood-image/<path:filename>"
)
def mood_image(filename):
    from flask import (
        send_from_directory,
    )

    return send_from_directory(
        str(MOOD_IMAGE_ROOT),
        filename,
    )


# ──────────────────────────────────────────────────────
# STEP 2: 사진 업로드 및 방 크기 입력
# ──────────────────────────────────────────────────────
@app.route(
    "/upload",
    methods=["GET", "POST"],
)
def upload():
    if (
        request.method == "GET"
        and "mood_prompt"
        not in session
    ):
        return redirect(
            url_for("prompt")
        )

    if request.method == "POST":
        room_width_raw = (
            request.form.get(
                "room_width"
            )
            or ""
        ).strip()

        room_depth_raw = (
            request.form.get(
                "room_depth"
            )
            or ""
        ).strip()

        ceiling_height_raw = (
            request.form.get(
                "ceiling_height"
            )
            or ""
        ).strip()

        dimension_values = [
            room_width_raw,
            room_depth_raw,
            ceiling_height_raw,
        ]

        all_dimensions_empty = all(
            value == ""
            for value
            in dimension_values
        )

        all_dimensions_filled = all(
            value != ""
            for value
            in dimension_values
        )

        room_width = None
        room_depth = None
        ceiling_height = None

        if not all_dimensions_empty:
            if not all_dimensions_filled:
                return jsonify(
                    {
                        "ok": False,
                        "error": (
                            "방 크기는 세 항목을 "
                            "모두 입력하거나 모두 "
                            "비워 주세요."
                        ),
                    }
                ), 400

            try:
                room_width = float(
                    room_width_raw
                )

                room_depth = float(
                    room_depth_raw
                )

                ceiling_height = float(
                    ceiling_height_raw
                )

            except ValueError:
                return jsonify(
                    {
                        "ok": False,
                        "error": (
                            "방 크기를 숫자로 "
                            "입력해 주세요."
                        ),
                    }
                ), 400

            if not (
                room_width >= 0.1
                and room_depth >= 0.1
                and ceiling_height >= 0.1
            ):
                return jsonify(
                    {
                        "ok": False,
                        "error": (
                            "방 크기는 0.1m "
                            "이상으로 입력해 주세요."
                        ),
                    }
                ), 400

        file = request.files.get(
            "photo"
        )

        if (
            not file
            or file.filename == ""
        ):
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "방 사진을 선택해 주세요."
                    ),
                }
            ), 400

        if not allowed_file(
            file.filename
        ):
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "JPG/PNG 파일만 "
                        "업로드 가능합니다."
                    ),
                }
            ), 400

        ext = (
            file.filename
            .rsplit(
                ".",
                1,
            )[1]
            .lower()
        )

        saved_name = (
            f"upload_"
            f"{uuid.uuid4().hex[:10]}"
            f".{ext}"
        )

        file.save(
            os.path.join(
                UPLOAD_DIR,
                saved_name,
            )
        )

        session[
            "uploaded_file"
        ] = saved_name

        session[
            "original_filename"
        ] = file.filename

        if room_width is not None:
            session[
                "room_width"
            ] = room_width

            session[
                "room_depth"
            ] = room_depth

            session[
                "ceiling_height"
            ] = ceiling_height

        else:
            session.pop(
                "room_width",
                None,
            )

            session.pop(
                "room_depth",
                None,
            )

            session.pop(
                "ceiling_height",
                None,
            )

        # 새 사진을 올리면 이전 분석 결과를 제거한다.
        for key in [
            "detected_furniture",
            "floorplan_layout_file",
            "original_floorplan_file",
            "modified_layout_file",
            "modified_floorplan_file",
            "furniture_choices",
            "purchase_items",
            "generated_file",
            "ai_description",
        ]:
            session.pop(
                key,
                None,
            )

        remove_cache_file(
            session.pop(
                "product_candidates_file",
                None,
            )
        )

        remove_cache_file(
            session.pop(
                "selected_products_file",
                None,
            )
        )

        return jsonify(
            {
                "ok": True,
                "redirect": url_for(
                    "loading"
                ),
            }
        )

    return render_template(
        "upload.html"
    )


# ──────────────────────────────────────────────────────
# STEP 3: AI 분석 로딩 / 평면도
# ──────────────────────────────────────────────────────
@app.route("/loading")
def loading():
    if "uploaded_file" not in session:
        return redirect(
            url_for("upload")
        )

    # loading.js에서 백그라운드로
    # /floorplan 주소를 요청한다.
    return render_template(
        "loading.html"
    )


@app.route("/floorplan")
def floorplan():
    if "uploaded_file" not in session:
        return redirect(
            url_for("upload")
        )

    room_width = session.get(
        "room_width"
    )

    room_depth = session.get(
        "room_depth"
    )

    ceiling_height = session.get(
        "ceiling_height"
    )

    dimensions_provided = (
        room_width is not None
        and room_depth is not None
        and ceiling_height is not None
    )

    plan = None

    if dimensions_provided:
        area_sqm = (
            room_width
            * room_depth
        )

        plan = {
            "area_sqm": round(
                area_sqm,
                1,
            ),
            "area_pyeong": round(
                area_sqm / 3.3058,
                1,
            ),
            "width_m": room_width,
            "depth_m": room_depth,
            "ceiling_m": (
                ceiling_height
            ),
        }

    svg_markup = None
    floorplan_error = None

    upload_path = os.path.join(
        UPLOAD_DIR,
        session["uploaded_file"],
    )

    try:
        result = (
            floorplan_model
            .generate_floorplan_for_web(
                upload_path,
                GENERATED_DIR,
                skip_existing=True,
                room_width=room_width,
                room_depth=room_depth,
            )
        )

        layout_file = result.get(
            "layout_file"
        )

        if layout_file:
            session[
                "floorplan_layout_file"
            ] = layout_file

        svg_path = result.get(
            "svg_path"
        )

        if svg_path:
            session[
                "original_floorplan_file"
            ] = os.path.basename(
                svg_path
            )

        detected_furniture = []

        for index, obj in enumerate(
            result.get(
                "objects",
                [],
            )
        ):
            item_type = str(
                obj.get("type")
                or "unknown"
            ).lower()

            if item_type in {
                "door",
                "window",
            }:
                continue

            label = (
                translate_furniture_label(
                    item_type,
                    obj.get("label"),
                    index + 1,
                )
            )

            source_index = obj.get(
                "source_index"
            )

            if source_index is None:
                source_index = index

            detected_furniture.append(
                {
                    "id": (
                        f"furniture_{index}"
                    ),
                    "label": label,
                    "type": item_type,
                    "source_index": (
                        source_index
                    ),
                }
            )

        session[
            "detected_furniture"
        ] = detected_furniture

        svg_markup = result.get(
            "svg_markup"
        )

    except Exception as exc:
        floorplan_error = str(exc)

        print(
            "[floorplan] "
            f"평면도 생성 실패: {exc}"
        )

        # Gemini 평면도 생성이 실패한 경우
        # YOLO로 기본 가구 목록만 탐지한다.
        try:
            yolo_items = (
                detect_furniture_from_image(
                    upload_path
                )
            )

            session[
                "detected_furniture"
            ] = [
                {
                    "id": (
                        f"yolo_{index}"
                    ),
                    "label": item_name,
                    "type": (
                        detected_item_to_type(
                            item_name
                        )
                    ),
                    "source_index": None,
                }
                for index, item_name
                in enumerate(yolo_items)
            ]

        except Exception as yolo_exc:
            print(
                "[floorplan] "
                "YOLO 대체 탐지 실패: "
                f"{yolo_exc}"
            )

            session[
                "detected_furniture"
            ] = []

    return render_template(
        "floorplan.html",
        plan=plan,
        dimensions_provided=(
            dimensions_provided
        ),
        svg_markup=svg_markup,
        floorplan_error=(
            floorplan_error
        ),
    )


# ──────────────────────────────────────────────────────
# STEP 4: 기존 가구 유지·제거 /
# 구매할 가구 종류 선택
# ──────────────────────────────────────────────────────
@app.route("/furniture-choice")
def furniture_choice():
    if "mood_prompt" not in session:
        return redirect(
            url_for("prompt")
        )

    if "uploaded_file" not in session:
        return redirect(
            url_for("upload")
        )

    furniture_items = session.get(
        "detected_furniture",
        [],
    )

    purchase_options = [
        {
            "value": item_type,
            "label": label,
        }
        for item_type, label
        in PURCHASE_LABELS.items()
    ]

    return render_template(
        "furniture_choice.html",
        furniture_items=(
            furniture_items
        ),
        purchase_options=(
            purchase_options
        ),
    )


# ──────────────────────────────────────────────────────
# STEP 5: 종류별 네이버 쇼핑 상품 추천 및 선택
# ──────────────────────────────────────────────────────
def default_furniture_choices():
    """감지된 가구를 모두 '유지'로 둔 기본 선택값.
    STEP 4(가구 유지/제거)를 건너뛰어도 결과가 나오게 하기 위한 기본값이며,
    유지/제거는 result 화면에서 바로 토글할 수 있다."""
    return [
        {
            "id": item.get("id"),
            "item": item.get("label"),
            "type": item.get("type"),
            "source_index": item.get(
                "source_index"
            ),
            "decision": "keep",
        }
        for item
        in session.get(
            "detected_furniture",
            [],
        )
    ]




# ──────────────────────────────────────────────────────
# STEP 6: 선택한 상품으로 결과 생성
# ──────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────
# 수정 평면도 생성 (result / toggle-furniture / add-product 공용)
# ──────────────────────────────────────────────────────
def read_generated_svg(filename):
    """generated 폴더의 SVG 파일 내용(markup)을 읽어 반환. 없으면 None.
    result 화면 인라인 삽입 및 AJAX 응답에 사용(가구 드래그를 위해 img 대신 인라인 SVG)."""
    if not filename:
        return None
    path = os.path.join(GENERATED_DIR, os.path.basename(filename))
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def create_modified_floorplan(
    furniture_choices,
    selected_products,
):
    """
    원본 평면도에서 제거할 가구를 삭제하고,
    선택한 추천 상품을 번호와 함께 추가한다.
    """

    layout_path = session.get(
        "floorplan_layout_file"
    )

    if not layout_path:
        print(
            "[generate-design] "
            "원본 layout 파일 경로가 "
            "없습니다."
        )

        return None

    # 저장된 경로가 상대 경로인 경우
    # 실제 파일 위치를 확인한다.
    if not os.path.isabs(
        layout_path
    ):
        candidates = [
            os.path.join(
                PROJECT_ROOT,
                layout_path,
            ),
            os.path.join(
                GENERATED_DIR,
                layout_path,
            ),
        ]

        layout_path = next(
            (
                candidate
                for candidate
                in candidates
                if os.path.exists(
                    candidate
                )
            ),
            layout_path,
        )

    if not os.path.exists(
        layout_path
    ):
        print(
            "[generate-design] "
            "원본 layout 파일을 "
            "찾을 수 없습니다: "
            f"{layout_path}"
        )

        return None

    try:
        with open(
            layout_path,
            "r",
            encoding="utf-8",
        ) as file:
            layout = json.load(
                file
            )

        remove_indices = set()

        for choice in furniture_choices:
            if (
                choice.get("decision")
                != "remove"
            ):
                continue

            source_index = choice.get(
                "source_index"
            )

            if source_index is None:
                continue

            try:
                remove_indices.add(
                    int(source_index)
                )

            except (
                TypeError,
                ValueError,
            ):
                continue

        original_objects = layout.get(
            "objects",
            [],
        )

        modified_objects = [
            obj
            for index, obj
            in enumerate(
                original_objects
            )
            if index not in remove_indices
        ]

        # 상품 치수를 방 대비 비율로 바꾸는 데 쓸 방 실측(m).
        room_data = layout.get("room") or {}
        room_width_m = room_data.get("width_m")
        room_depth_m = room_data.get("depth_m")

        for order, product in enumerate(
            selected_products
        ):
            item_type = product.get(
                "type"
            )

            if item_type not in (
                PURCHASE_LABELS
            ):
                continue

            x, y = PURCHASE_POSITIONS[
                order
                % len(
                    PURCHASE_POSITIONS
                )
            ]

            # 상품 제목에 치수가 적혀 있으면 실제 크기로 그린다.
            # (없거나 방 실측이 없으면 0.0 -> 렌더러 표준 크기)
            size = product_size_fractions(
                product.get("title"),
                room_width_m,
                room_depth_m,
                product=product,
            )

            marker = product.get(
                "marker",
                order + 1,
            )

            wall_map = {
                "desk": "top",
                "shelf": "left",
                "cabinet": "left",
            }

            modified_objects.append(
                {
                    "type": item_type,
                    "label": (
                        f"{marker}. 새 "
                        f"{PURCHASE_LABELS[item_type]}"
                    ),
                    "x": x,
                    "y": y,
                    "w": (
                        size["w"]
                        if size
                        else 0.0
                    ),
                    "h": (
                        size["h"]
                        if size
                        else 0.0
                    ),
                    "wall": wall_map.get(
                        item_type,
                        "none",
                    ),
                    "confidence": 1.0,
                    "source": (
                        "selected_product"
                    ),
                    "product_link": (
                        product.get(
                            "link"
                        )
                    ),
                    "product_title": (
                        product.get(
                            "title"
                        )
                    ),
                    "product_marker": (
                        marker
                    ),
                    # 제목에서 읽어낸 치수 원문(툴팁 표시용).
                    "size_note": (
                        size["raw"]
                        if size
                        else None
                    ),
                }
            )

        modified_layout = {
            **layout,
            "objects": modified_objects,
        }

        token = uuid.uuid4().hex[
            :10
        ]

        layout_filename = (
            f"modified_layout_"
            f"{token}.json"
        )

        svg_filename = (
            f"modified_floorplan_"
            f"{token}.svg"
        )

        modified_layout_path = (
            os.path.join(
                GENERATED_DIR,
                layout_filename,
            )
        )

        modified_svg_path = (
            os.path.join(
                GENERATED_DIR,
                svg_filename,
            )
        )

        with open(
            modified_layout_path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                modified_layout,
                file,
                ensure_ascii=False,
                indent=2,
            )

        rule_based_svg.save_svg(
            modified_layout,
            modified_svg_path,
            title=(
                "추천 가구가 반영된 평면도"
            ),
        )

        session[
            "modified_layout_file"
        ] = layout_filename

        return svg_filename

    except Exception as exc:
        print(
            "[generate-design] "
            "수정 평면도 생성 실패: "
            f"{exc}"
        )

        return None


@app.route(
    "/generate-design",
    methods=["GET", "POST"],
)
def generate_design():
    """평면도 -> 결과 화면. 상품 선택 없이도 바로 진행한다.

    구매할 가구와 상품 선택은 result 화면에서 직접 검색·추가할 수 있으므로
    (search-products / add-product) 별도 선택 단계를 두지 않는다.
    GET으로 들어오면 상품 선택 없이 기존 가구만 반영해 결과를 만든다.
    """
    if "mood_prompt" not in session:
        return redirect(
            url_for("prompt")
        )

    if "uploaded_file" not in session:
        return redirect(
            url_for("upload")
        )

    # STEP 4(가구 유지/제거) 폼에서 POST로 들어온 경우 그 선택을 반영한다.
    # 이 화면을 거치지 않았다면 감지된 가구를 전부 '유지'로 둔다.
    if request.method == "POST" and request.form.get(
        "from_furniture_choice"
    ):
        choices = []

        for item in session.get(
            "detected_furniture",
            [],
        ):
            item_id = item.get("id")

            decision = request.form.get(
                f"decision_{item_id}",
                "keep",
            )

            if decision not in {"keep", "remove"}:
                decision = "keep"

            choices.append(
                {
                    "id": item_id,
                    "item": item.get("label"),
                    "type": item.get("type"),
                    "source_index": item.get(
                        "source_index"
                    ),
                    "decision": decision,
                }
            )

        session["furniture_choices"] = choices

        # 이 화면에서 고른 '새로 구매할 가구' 종류도 함께 받는다.
        session["purchase_items"] = [
            item
            for item in request.form.getlist(
                "purchase_items"
            )
            if item in PURCHASE_LABELS
        ]

    elif "furniture_choices" not in session:
        session["furniture_choices"] = (
            default_furniture_choices()
        )

    furniture_choices = session.get(
        "furniture_choices",
        [],
    )

    purchase_items = session.get(
        "purchase_items",
        [],
    )

    candidates_data = load_json_cache(
        session.get(
            "product_candidates_file"
        ),
        default={},
    )

    product_groups = candidates_data.get(
        "groups",
        [],
    )

    selected_products = []

    for group in product_groups:
        item_type = group.get(
            "type"
        )

        if item_type not in purchase_items:
            continue

        products = group.get(
            "products",
            [],
        )

        selected_index_raw = (
            request.form.get(
                f"selected_product_"
                f"{item_type}"
            )
        )

        if selected_index_raw is None:
            continue

        try:
            selected_index = int(
                selected_index_raw
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        if not (
            0
            <= selected_index
            < len(products)
        ):
            continue

        selected_product = dict(
            products[
                selected_index
            ]
        )

        selected_product[
            "type"
        ] = item_type

        selected_product[
            "label"
        ] = PURCHASE_LABELS.get(
            item_type,
            item_type,
        )

        selected_product[
            "marker"
        ] = (
            len(selected_products)
            + 1
        )

        selected_products.append(
            selected_product
        )

    # 상품을 고르지 않아도 그대로 진행한다. 추천 상품은 result 화면에서
    # 직접 검색해 추가할 수 있으므로(search-products / add-product)
    # 여기서 되돌릴 화면이 없다.

    old_selected_file = session.pop(
        "selected_products_file",
        None,
    )

    remove_cache_file(
        old_selected_file
    )

    selected_filename = (
        save_json_cache(
            "selected_products",
            selected_products,
        )
    )

    session[
        "selected_products_file"
    ] = selected_filename

    modified_floorplan_file = (
        create_modified_floorplan(
            furniture_choices,
            selected_products,
        )
    )

    if modified_floorplan_file:
        session[
            "modified_floorplan_file"
        ] = modified_floorplan_file

    else:
        session.pop(
            "modified_floorplan_file",
            None,
        )

    prompt_text = session[
        "mood_prompt"
    ]

    tags = session.get(
        "style_tags",
        [],
    )

    upload_path = os.path.join(
        UPLOAD_DIR,
        session["uploaded_file"],
    )

    # 실제 Model2는 아직 없으므로
    # 기존 임시 이미지 생성 기능을 유지한다.
    generated_filename = (
        ai_backend
        .generate_interior_image(
            upload_path=upload_path,
            output_dir=GENERATED_DIR,
            prompt_text=prompt_text,
            tags=tags,
        )
    )

    description = (
        ai_backend
        .generate_description(
            tags,
            prompt_text,
        )
    )

    kept_count = sum(
        choice.get("decision")
        == "keep"
        for choice
        in furniture_choices
    )

    removed_count = sum(
        choice.get("decision")
        == "remove"
        for choice
        in furniture_choices
    )

    description += (
        f" 기존 가구 {kept_count}개를 "
        f"유지하고 {removed_count}개를 "
        "제거하도록 선택했습니다."
    )

    if selected_products:
        product_names = ", ".join(
            product.get(
                "label",
                product.get(
                    "type",
                    "가구",
                ),
            )
            for product
            in selected_products
        )

        description += (
            " 선택한 추천 가구는 "
            f"{product_names}입니다."
        )

    session[
        "generated_file"
    ] = generated_filename

    session[
        "ai_description"
    ] = description

    return redirect(
        url_for("result")
    )


# ──────────────────────────────────────────────────────
@app.route("/toggle-furniture", methods=["POST"])
def toggle_furniture():
    """result 화면에서 가구 유지/제거를 즉시 토글하고 수정 평면도를 다시 만든다.
    요청(JSON): {"source_index": int, "decision": "keep"|"remove"}
    응답(JSON): {"ok": bool, "svg_url": 새 SVG URL, "decision": 반영된 값}
    """
    data = request.get_json(silent=True) or {}
    try:
        target_si = int(data.get("source_index"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "잘못된 가구 식별자"}), 400
    decision = data.get("decision")
    if decision not in ("keep", "remove"):
        return jsonify({"ok": False, "error": "잘못된 선택값"}), 400

    # 세션 furniture_choices에서 해당 가구의 decision을 갱신
    furniture_choices = session.get("furniture_choices", [])
    found = False
    for choice in furniture_choices:
        if choice.get("source_index") == target_si:
            choice["decision"] = decision
            found = True
            break
    if not found:
        return jsonify({"ok": False, "error": "가구를 찾을 수 없습니다"}), 404
    session["furniture_choices"] = furniture_choices

    # 선택 상품(있으면)과 함께 수정 평면도 재생성
    selected_products = load_json_cache(
        session.get("selected_products_file"), default=[]
    )
    svg_filename = create_modified_floorplan(
        furniture_choices, selected_products
    )
    if not svg_filename:
        return jsonify({"ok": False, "error": "수정 평면도 생성 실패"}), 500
    session["modified_floorplan_file"] = svg_filename

    return jsonify({
        "ok": True,
        "svg_markup": read_generated_svg(svg_filename),
        "decision": decision,
    })


@app.route("/search-products", methods=["GET"])
def search_products():
    """result 화면에서 직접 상품을 검색한다.
    쿼리: ?q=검색어  응답: {ok, products:[{title,link,image,price,shop}]}"""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"ok": False, "error": "검색어를 입력해 주세요."}), 400
    try:
        products = search_naver_shopping(query, display=6)
    except ValueError as exc:  # 네이버 키 미설정 등
        return jsonify({"ok": False, "error": str(exc)}), 503
    except Exception as exc:
        print(f"[search-products] 검색 실패: {exc}")
        return jsonify({"ok": False, "error": "상품 검색에 실패했습니다."}), 502
    return jsonify({"ok": True, "products": products})


@app.route("/add-product", methods=["POST"])
def add_product():
    """검색한 상품을 선택해 평면도에 새 가구로 추가한다.
    요청(JSON): {type, title, link, image}
    type은 PURCHASE_LABELS의 가구 종류여야 평면도에 반영된다.
    응답(JSON): {ok, svg_url, product}
    """
    data = request.get_json(silent=True) or {}
    item_type = data.get("type")
    if item_type not in PURCHASE_LABELS:
        return jsonify({
            "ok": False,
            "error": "가구 종류를 선택해 주세요(의자/책상/테이블/선반/수납장/조명/러그/식물).",
        }), 400
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"ok": False, "error": "상품 정보가 없습니다."}), 400

    # 기존 selected_products에 새 상품을 append (marker는 순번)
    selected_products = load_json_cache(
        session.get("selected_products_file"), default=[]
    )
    marker = len(selected_products) + 1
    selected_products.append({
        "type": item_type,
        "title": title,
        "link": data.get("link"),
        "image": data.get("image"),
        "marker": marker,
        # 제목에 치수가 없을 때 크기 추정에 쓴다.
        "category3": data.get("category3"),
        "category4": data.get("category4"),
    })
    selected_filename = save_json_cache("selected_products", selected_products)
    session["selected_products_file"] = selected_filename

    # 평면도 재생성 (유지/제거 선택 + 새 상품 반영)
    furniture_choices = session.get("furniture_choices", [])
    svg_filename = create_modified_floorplan(
        furniture_choices, selected_products
    )
    if not svg_filename:
        return jsonify({"ok": False, "error": "수정 평면도 생성 실패"}), 500
    session["modified_floorplan_file"] = svg_filename

    return jsonify({
        "ok": True,
        "svg_markup": read_generated_svg(svg_filename),
        "product": {"type": item_type, "title": title, "marker": marker},
    })


# 결과 화면
# ──────────────────────────────────────────────────────
@app.route("/result")
def result():
    generated_file = session.get(
        "generated_file"
    )

    description = session.get(
        "ai_description"
    )

    tags = session.get(
        "style_tags",
        [
            "Cozy",
            "Plants",
            "Warm",
            "Vintage",
        ],
    )

    # 이름은 저장된 값을 그대로 쓰지 않고 표시 시점에 한글로 바꾼다.
    # 번역 규칙이 바뀌거나 예전 세션에 영어 라벨이 남아 있어도
    # 화면에는 항상 한글이 나오게 하기 위함.
    furniture_choices = [
        {
            **choice,
            "item": translate_furniture_label(
                choice.get("type"),
                choice.get("item"),
                index + 1,
            ),
        }
        for index, choice in enumerate(
            session.get(
                "furniture_choices",
                [],
            )
        )
    ]

    purchase_types = session.get(
        "purchase_items",
        [],
    )

    purchase_items = [
        {
            "type": item_type,
            "label": PURCHASE_LABELS.get(
                item_type,
                item_type,
            ),
            "item_id": PURCHASE_ITEM_IDS.get(
                item_type,
                item_type,
            ),
        }
        for item_type
        in purchase_types
    ]

    selected_products = (
        load_json_cache(
            session.get(
                "selected_products_file"
            ),
            default=[],
        )
    )

    modified_file = session.get("modified_floorplan_file")
    # 가구 드래그를 위해 수정 평면도는 img 대신 인라인 SVG로 넣는다.
    modified_svg_markup = read_generated_svg(modified_file)

    return render_template(
        "result.html",
        generated_file=(
            generated_file
        ),
        description=description,
        tags=tags,
        original_floorplan_file=(
            session.get(
                "original_floorplan_file"
            )
        ),
        modified_floorplan_file=modified_file,
        modified_svg_markup=modified_svg_markup,
        furniture_choices=(
            furniture_choices
        ),
        purchase_items=(
            purchase_items
        ),
        selected_products=(
            selected_products
        ),
    )


# ──────────────────────────────────────────────────────
# 기존 AJAX 상품 추천 API
# ──────────────────────────────────────────────────────
def item_id_to_query(item_id):
    query_map = {
        "chair-001": "원목 의자",
        "table-001": "원목 테이블",
        "sofa-001": "패브릭 소파",
        "bed-001": "원목 침대",
        "lamp-001": "무드등",
        "desk-001": "원목 책상",
        "curtain-001": "베이지 커튼",
        "side-table-001": "원목 협탁",
        "shelf-001": "원목 선반",
        "cabinet-001": "원목 수납장",
        "rug-001": (
            "베이지 인테리어 러그"
        ),
        "plant-001": (
            "인테리어 식물"
        ),
    }

    return query_map.get(
        item_id,
        item_id,
    )


YOLO_MODEL = None


def get_yolo_model():
    global YOLO_MODEL

    if YOLO_MODEL is None:
        model_path = os.path.join(
            BASE_DIR,
            "yolov8n.pt",
        )

        YOLO_MODEL = YOLO(
            model_path
        )

    return YOLO_MODEL


def detect_furniture_from_image(
    image_path,
):
    model = get_yolo_model()

    results = model.predict(
        source=image_path,
        save=False,
        verbose=False,
    )

    label_map = {
        "bed": "침대",
        "chair": "의자",
        "couch": "소파",
        "dining table": "테이블",
        "tv": "TV",
        "potted plant": "식물",
    }

    allowed_labels = set(
        label_map
    )

    detected_items = []

    for result in results:
        for box in result.boxes:
            class_id = int(
                box.cls[0]
            )

            confidence = float(
                box.conf[0]
            )

            label_en = result.names[
                class_id
            ]

            if (
                label_en
                not in allowed_labels
            ):
                continue

            if confidence < 0.3:
                continue

            label_ko = label_map.get(
                label_en,
                label_en,
            )

            if (
                label_ko
                not in detected_items
            ):
                detected_items.append(
                    label_ko
                )

    return detected_items


def detected_item_to_query(
    item_name,
):
    query_map = {
        "침대": "원목 침대",
        "소파": "패브릭 소파",
        "TV": "TV 거치대",
        "의자": "원목 의자",
        "테이블": "원목 테이블",
        "식물": "인테리어 식물",
    }

    return query_map.get(
        item_name,
        item_name,
    )


def detected_item_to_type(
    item_name,
):
    type_map = {
        "침대": "bed",
        "소파": "unknown",
        "TV": "unknown",
        "의자": "chair",
        "테이블": "table",
        "식물": "plant",
    }

    return type_map.get(
        item_name,
        "unknown",
    )


@app.route("/recommend")
def recommend():
    item_id = request.args.get(
        "item",
        "chair-001",
    )

    try:
        query = item_id_to_query(
            item_id
        )

        products = (
            search_naver_shopping(
                query=query,
                display=5,
            )
        )

        if not products:
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "네이버 쇼핑 검색 "
                        "결과가 없습니다."
                    ),
                }
            ), 404

        main_product = products[0]

        similar_products = products[
            1:4
        ]

        item = {
            "id": item_id,
            "name": query,
            "price": (
                main_product[
                    "price"
                ]
            ),
            "rating": 4,
            "image": (
                main_product[
                    "image"
                ]
            ),
            "link": (
                main_product[
                    "link"
                ]
            ),
            "shop": (
                main_product[
                    "shop"
                ]
            ),
            "similar": [
                {
                    "name": (
                        product[
                            "title"
                        ]
                    ),
                    "price": (
                        product[
                            "price"
                        ]
                    ),
                    "shop": (
                        product[
                            "shop"
                        ]
                    ),
                    "image": (
                        product[
                            "image"
                        ]
                    ),
                    "link": (
                        product[
                            "link"
                        ]
                    ),
                }
                for product
                in similar_products
            ],
        }

        return jsonify(
            {
                "ok": True,
                "query": query,
                "item": item,
            }
        )

    except Exception as exc:
        print(
            "추천 API 오류:",
            exc,
        )

        return jsonify(
            {
                "ok": False,
                "error": (
                    "상품 추천 API 호출 중 "
                    "오류가 발생했습니다."
                ),
            }
        ), 500


@app.route(
    "/recommend-from-upload"
)
def recommend_from_upload():
    uploaded_file = session.get(
        "uploaded_file"
    )

    if not uploaded_file:
        return jsonify(
            {
                "ok": False,
                "error": (
                    "업로드된 이미지가 없습니다. "
                    "먼저 사진을 업로드해 주세요."
                ),
            }
        ), 400

    image_path = os.path.join(
        UPLOAD_DIR,
        uploaded_file,
    )

    if not os.path.exists(
        image_path
    ):
        return jsonify(
            {
                "ok": False,
                "error": (
                    "업로드된 이미지 파일을 "
                    "찾을 수 없습니다."
                ),
            }
        ), 404

    try:
        detected_items = (
            detect_furniture_from_image(
                image_path
            )
        )

        if not detected_items:
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "이미지에서 가구를 "
                        "탐지하지 못했습니다."
                    ),
                }
            ), 404

        recommendations = {}

        for item_name in detected_items:
            query = (
                detected_item_to_query(
                    item_name
                )
            )

            products = (
                search_naver_shopping(
                    query=query,
                    display=3,
                )
            )

            recommendations[
                item_name
            ] = {
                "search_query": query,
                "products": products,
            }

        return jsonify(
            {
                "ok": True,
                "uploaded_file": (
                    uploaded_file
                ),
                "detected_items": (
                    detected_items
                ),
                "recommendations": (
                    recommendations
                ),
            }
        )

    except Exception as exc:
        print(
            "업로드 이미지 기반 "
            "추천 API 오류:",
            exc,
        )

        return jsonify(
            {
                "ok": False,
                "error": (
                    "업로드 이미지 기반 추천 중 "
                    "오류가 발생했습니다."
                ),
            }
        ), 500


if __name__ == "__main__":
    app.run(
        debug=True
    )
