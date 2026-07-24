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

from model1 import interior_to_floorplan as floorplan_model
from mood_pipeline import rule_based_svg
from mood_pipeline import search as mood_search
from mood_pipeline.config import IMAGE_ROOT as MOOD_IMAGE_ROOT


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
    }

    label_aliases = {
        "single bed": "싱글 침대",
        "bed": "침대",
        "nightstand": "협탁",
        "side table": "협탁",
        "tv stand": "TV장",
        "table lamp": "탁상 조명",
        "floor lamp": "스탠드 조명",
        "low table": "낮은 테이블",
        "desk": "책상",
        "chair": "의자",
        "rug": "러그",
        "plant": "식물",
        "shelf": "선반",
        "cabinet": "수납장",
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

    return label


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
@app.route(
    "/product-selection",
    methods=["GET", "POST"],
)
def product_selection():
    if "mood_prompt" not in session:
        return redirect(
            url_for("prompt")
        )

    if "uploaded_file" not in session:
        return redirect(
            url_for("upload")
        )

    if request.method == "POST":
        furniture_choices = []

        for item in session.get(
            "detected_furniture",
            [],
        ):
            item_id = item.get(
                "id"
            )

            decision = request.form.get(
                f"decision_{item_id}",
                "keep",
            )

            if decision not in {
                "keep",
                "remove",
            }:
                decision = "keep"

            furniture_choices.append(
                {
                    "id": item_id,
                    "item": item.get(
                        "label"
                    ),
                    "type": item.get(
                        "type"
                    ),
                    "source_index": (
                        item.get(
                            "source_index"
                        )
                    ),
                    "decision": decision,
                }
            )

        purchase_items = [
            item
            for item
            in request.form.getlist(
                "purchase_items"
            )
            if item in PURCHASE_LABELS
        ]

        session[
            "furniture_choices"
        ] = furniture_choices

        session[
            "purchase_items"
        ] = purchase_items

        # 가구 선택을 다시 했기 때문에
        # 이전 추천 상품 정보는 삭제한다.
        old_candidates = session.pop(
            "product_candidates_file",
            None,
        )

        old_selected = session.pop(
            "selected_products_file",
            None,
        )

        remove_cache_file(
            old_candidates
        )

        remove_cache_file(
            old_selected
        )

    purchase_items = session.get(
        "purchase_items",
        [],
    )

    cached_data = load_json_cache(
        session.get(
            "product_candidates_file"
        ),
        default={},
    )

    cached_types = cached_data.get(
        "purchase_types",
        [],
    )

    product_groups = cached_data.get(
        "groups",
        [],
    )

    # 선택한 가구 종류가 이전 검색과 다르면
    # 네이버 쇼핑 API를 새로 호출한다.
    if cached_types != purchase_items:
        product_groups = []

        for item_type in purchase_items:
            label = (
                PURCHASE_LABELS.get(
                    item_type,
                    item_type,
                )
            )

            query = build_product_query(
                item_type
            )

            products = []
            error_message = None

            try:
                products = (
                    search_naver_shopping(
                        query=query,
                        display=4,
                    )
                )

            except Exception as exc:
                error_message = str(
                    exc
                )

                print(
                    "[product-selection] "
                    f"{label} 검색 실패: "
                    f"{exc}"
                )

            product_groups.append(
                {
                    "type": item_type,
                    "label": label,
                    "query": query,
                    "products": products,
                    "error": error_message,
                }
            )

        cache_data = {
            "purchase_types": (
                purchase_items
            ),
            "groups": product_groups,
        }

        cache_filename = (
            save_json_cache(
                "product_candidates",
                cache_data,
            )
        )

        session[
            "product_candidates_file"
        ] = cache_filename

    return render_template(
        "product_selection.html",
        product_groups=(
            product_groups
        ),
        purchase_items=(
            purchase_items
        ),
    )


# ──────────────────────────────────────────────────────
# 수정 평면도 생성
# ──────────────────────────────────────────────────────
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
                    "w": 0.0,
                    "h": 0.0,
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


# ──────────────────────────────────────────────────────
# STEP 6: 선택한 상품으로 결과 생성
# ──────────────────────────────────────────────────────
@app.route(
    "/generate-design",
    methods=["POST"],
)
def generate_design():
    if "mood_prompt" not in session:
        return redirect(
            url_for("prompt")
        )

    if "uploaded_file" not in session:
        return redirect(
            url_for("upload")
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

    # 구매할 가구 종류를 선택했지만
    # 상품을 하나라도 고르지 않은 경우
    # 상품 선택 화면으로 되돌아간다.
    if (
        purchase_items
        and len(selected_products)
        != len(purchase_items)
    ):
        return redirect(
            url_for(
                "product_selection"
            )
        )

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

    furniture_choices = session.get(
        "furniture_choices",
        [],
    )

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
        modified_floorplan_file=(
            session.get(
                "modified_floorplan_file"
            )
        ),
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
