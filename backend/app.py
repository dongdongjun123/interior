import os
import sys
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

import ai_backend
import database
import re
import requests
from dotenv import load_dotenv
from ultralytics import YOLO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 프론트엔드는 별도 폴더(../frontend)로 분리됨
FRONTEND_DIR = os.path.join(BASE_DIR, "..", "frontend")
# 프로젝트 루트를 import 경로에 추가 (model1, mood_pipeline 사용)
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from model1 import interior_to_floorplan as floorplan_model
from mood_pipeline import search as mood_search
from mood_pipeline.config import IMAGE_ROOT as MOOD_IMAGE_ROOT

app = Flask(
    __name__,
    template_folder=os.path.join(FRONTEND_DIR, "templates"),
    static_folder=os.path.join(FRONTEND_DIR, "static"),
)
app.secret_key = "dev-secret-key-change-in-production"
app.json.ensure_ascii = False

# 실행 위치와 무관하게 항상 프로젝트 루트의 .env를 읽음
load_dotenv(os.path.join(BASE_DIR, "..", ".env"))

UPLOAD_DIR = os.path.join(FRONTEND_DIR, "static", "uploads")
GENERATED_DIR = os.path.join(FRONTEND_DIR, "static", "generated")
ALLOWED_EXT = {"jpg", "jpeg", "png"}

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ── HOME ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

# ── 새로운 디자인 시작 ─────────────────────────────────
@app.route("/start")
def start():
    """이전 작업 정보를 지우고 새 디자인을 시작한다."""
    session.clear()
    return redirect(url_for("prompt"))

# ── STEP 1: 사진 업로드 ────────────────────────────────
@app.route("/upload", methods=["GET", "POST"])
def upload():
    # 스타일 입력 없이 업로드 화면에 직접 접근한 경우
    if request.method == "GET" and "mood_prompt" not in session:
        return redirect(url_for("prompt"))

    if request.method == "POST":
        file = request.files.get("photo")
        if not file or file.filename == "":
            return jsonify({"ok": False, "error": "파일이 없습니다."}), 400
        if not allowed_file(file.filename):
            return jsonify({"ok": False, "error": "JPG/PNG 파일만 업로드 가능합니다."}), 400

        ext = file.filename.rsplit(".", 1)[1].lower()
        saved_name = f"upload_{uuid.uuid4().hex[:10]}.{ext}"
        file.save(os.path.join(UPLOAD_DIR, saved_name))

        session["uploaded_file"] = saved_name
        session["original_filename"] = file.filename
        return jsonify({"ok": True, "redirect": url_for("loading")})

    return render_template("upload.html")


# ── AI 분석 로딩 ───────────────────────────────────────
@app.route("/loading")
def loading():
    if "uploaded_file" not in session:
        return redirect(url_for("upload"))
    return render_template("loading.html")


# ── 평면도 확인 ────────────────────────────────────────
@app.route("/floorplan")
def floorplan():
    if "uploaded_file" not in session:
        return redirect(url_for("upload"))

    plan = database.get_floorplan_mock()  # 면적 등 공간 정보(현재 mock, 실측은 사진만으로 불가)
    svg_markup = None  # 실제 생성된 평면도 SVG

    upload_path = os.path.join(UPLOAD_DIR, session["uploaded_file"])
    try:
        # model1으로 실제 평면도 SVG 생성 (Gemini layout 1회 + 무료 렌더)
        result = floorplan_model.generate_floorplan_for_web(
            upload_path, GENERATED_DIR, skip_existing=True,
        )
        svg_markup = result["svg_markup"]
    except Exception as exc:
        # 실패(키 없음/쿼터 초과 등) 시 평면도 없이 진행 — 화면은 mock 정보로 표시
        print(f"[floorplan] 평면도 생성 실패, mock으로 진행: {exc}")

    return render_template("floorplan.html", plan=plan, svg_markup=svg_markup)


# ── 프롬프트 입력 ──────────────────────────────────────
DEFAULT_MOOD_QUERY = "cozy warm interior with natural wood and plants"  # 첫 진입 시 기본 무드


def _mood_results_to_urls(results):
    return [
        {
            "url": url_for("mood_image", filename=r["path"]),
            "path": r["path"],
            "score": r["score"],
        }
        for r in results
    ]


@app.route("/prompt")
def prompt():
    """처음에는 추천 이미지를 표시하지 않는다."""
    return render_template("prompt.html", previews=[])

# ── 스타일 입력 저장 ────────────────────────────────────
@app.route("/save-style", methods=["POST"])
def save_style():
    """입력한 인테리어 문구와 태그를 저장하고 업로드 단계로 이동한다."""
    data = request.get_json(silent=True) or {}

    prompt_text = (data.get("prompt") or "").strip()
    tags = data.get("tags") or []
    selected_image = (data.get("selected_image") or "").strip()

    if not prompt_text:
        return jsonify({
            "ok": False,
            "error": "원하는 인테리어 분위기를 입력해 주세요.",
        }), 400

    if not selected_image:
        return jsonify({
            "ok": False,
            "error": "추천 이미지 중 하나를 선택해 주세요.",
        }), 400

    if not isinstance(tags, list):
        tags = []

    session["mood_prompt"] = prompt_text
    session["style_tags"] = tags
    session["selected_mood_image"] = selected_image

    return jsonify({
        "ok": True,
        "redirect": url_for("upload"),
    })

@app.route("/mood-search")
def mood_search_api():
    # 프롬프트 텍스트 → 유사 이미지 top-K (프론트에서 실시간 호출)
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"ok": True, "results": []})
    try:
        results = mood_search.search_by_prompt(query, top_k=5)
        return jsonify({"ok": True, "results": _mood_results_to_urls(results)})
    except Exception as exc:
        print(f"[mood-search] 검색 실패: {exc}")
        return jsonify({"ok": False, "error": "무드 검색 중 오류가 발생했습니다."}), 500


@app.route("/mood-image/<path:filename>")
def mood_image(filename):
    # images/final의 이미지를 안전하게 서빙 (static 밖이라 별도 라우트 필요)
    from flask import send_from_directory

    return send_from_directory(str(MOOD_IMAGE_ROOT), filename)


# ── AI 생성 (핵심 연동 지점) ────────────────────────────

# ── 임시 디자인 결과 생성 ───────────────────────────────
@app.route("/generate-design", methods=["POST"])
def generate_design():
    """평면도 확인 후 현재 mock 생성기를 실행한다."""

    if "mood_prompt" not in session:
        return redirect(url_for("prompt"))

    if "uploaded_file" not in session:
        return redirect(url_for("upload"))

    prompt_text = session["mood_prompt"]
    tags = session.get("style_tags", [])

    upload_path = os.path.join(UPLOAD_DIR, session["uploaded_file"])

    # TODO: 추후 공식 Model2의 keep/remove/buy 및 2D 배치 로직으로 교체
    generated_filename = ai_backend.generate_interior_image(
        upload_path=upload_path,
        output_dir=GENERATED_DIR,
        prompt_text=prompt_text,
        tags=tags,
    )

    description = ai_backend.generate_description(tags, prompt_text)

    session["generated_file"] = generated_filename
    session["ai_description"] = description

    return redirect(url_for("result"))

# ── 결과 ──────────────────────────────────────────────
@app.route("/result")
def result():
    generated_file = session.get("generated_file")
    description = session.get("ai_description")
    tags = session.get("style_tags", ["Cozy", "Plants", "Warm", "Vintage"])
    return render_template(
        "result.html",
        generated_file=generated_file,
        description=description,
        tags=tags,
    )


# ── 가구 추천 (AJAX API) ───────────────────────────────
def clean_html(text):
    if text is None:
        return ""
    return re.sub(r"<.*?>", "", text)


def safe_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (ValueError, TypeError):
        return default


def search_naver_shopping(query, display=5):
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(".env에서 NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET을 불러오지 못했습니다.")

    url = "https://openapi.naver.com/v1/search/shop.json"

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    params = {
        "query": query,
        "display": display,
        "start": 1,
        "sort": "sim",
        "exclude": "used:rental:cbshop",
    }

    response = requests.get(url, headers=headers, params=params, timeout=10)

    if response.status_code != 200:
        print("네이버 API 요청 실패:", response.status_code, response.text)
        response.raise_for_status()

    data = response.json()
    products = []

    for item in data.get("items", []):
        products.append({
            "title": clean_html(item.get("title")),
            "link": item.get("link"),
            "image": item.get("image"),
            "price": safe_int(item.get("lprice")),
            "shop": item.get("mallName"),
            "brand": item.get("brand"),
            "category1": item.get("category1"),
            "category2": item.get("category2"),
            "category3": item.get("category3"),
            "category4": item.get("category4"),
        })

    return products


def item_id_to_query(item_id):
    """
    프론트에서 넘어오는 가구 id를 네이버 검색어로 변환한다.
    result.html의 data-item-id 값에 맞춰 필요하면 계속 추가하면 된다.
    """
    query_map = {
        "chair-001": "원목 의자",
        "table-001": "원목 테이블",
        "sofa-001": "패브릭 소파",
        "bed-001": "원목 침대",
        "lamp-001": "무드등",
        "desk-001": "원목 책상",
        "curtain-001": "베이지 커튼",
        "side-table-001": "원목 협탁",
    }

    return query_map.get(item_id, item_id)

YOLO_MODEL = None


def get_yolo_model():
    global YOLO_MODEL

    if YOLO_MODEL is None:
        # 가중치를 backend/ 아래에 두고 로드. 파일이 없으면 ultralytics가
        # 최초 실행 시 yolov8n.pt를 자동 다운로드한다.
        model_path = os.path.join(BASE_DIR, "yolov8n.pt")
        YOLO_MODEL = YOLO(model_path)

    return YOLO_MODEL


def detect_furniture_from_image(image_path):
    """
    업로드된 방 사진을 YOLO로 분석해서 이미지 안의 가구 목록을 추출한다.
    """
    model = get_yolo_model()

    results = model.predict(
        source=image_path,
        save=False,
        verbose=False
    )

    label_map = {
        "bed": "침대",
        "chair": "의자",
        "couch": "소파",
        "dining table": "테이블",
        "tv": "TV",
        "potted plant": "식물"
    }

    allowed_labels = {
        "bed", "chair", "couch", "dining table", "tv", "potted plant"
    }

    detected_items = []

    for result in results:
        for box in result.boxes:
            class_id = int(box.cls[0])
            confidence = float(box.conf[0])
            label_en = result.names[class_id]

            if label_en not in allowed_labels:
                continue

            if confidence < 0.3:
                continue

            label_ko = label_map.get(label_en, label_en)

            if label_ko not in detected_items:
                detected_items.append(label_ko)

    return detected_items


def detected_item_to_query(item_name):
    """
    YOLO가 탐지한 가구명을 네이버 쇼핑 검색어로 변환한다.
    """
    query_map = {
        "침대": "원목 침대",
        "소파": "패브릭 소파",
        "TV": "TV 거치대",
        "의자": "원목 의자",
        "테이블": "원목 테이블",
        "식물": "인테리어 식물"
    }

    return query_map.get(item_name, item_name)

# 가구 추천 (AJAX API)
@app.route("/recommend")
def recommend():
    item_id = request.args.get("item", "chair-001")

    try:
        query = item_id_to_query(item_id)
        products = search_naver_shopping(query=query, display=5)

        if not products:
            return jsonify({
                "ok": False,
                "error": "네이버 쇼핑 검색 결과가 없습니다."
            }), 404

        main_product = products[0]
        similar_products = products[1:4]

        # recommend.js가 기대하는 형식에 맞춰 반환
        item = {
            "id": item_id,
            "name": query,
            "price": main_product["price"],
            "rating": 4,
            "image": main_product["image"],
            "link": main_product["link"],
            "shop": main_product["shop"],
            "similar": [
                {
                    "name": p["title"],
                    "price": p["price"],
                    "shop": p["shop"],
                    "image": p["image"],
                    "link": p["link"],
                }
                for p in similar_products
            ]
        }

        return jsonify({
            "ok": True,
            "query": query,
            "item": item
        })

    except Exception as e:
        print("추천 API 오류:", e)
        return jsonify({
            "ok": False,
            "error": "상품 추천 API 호출 중 오류가 발생했습니다."
        }), 500

@app.route("/recommend-from-upload")
def recommend_from_upload():
    """
    업로드된 방 사진 기반 추천:
    업로드 이미지 → YOLO 가구 탐지 → 네이버 쇼핑 API 추천
    """
    uploaded_file = session.get("uploaded_file")

    if not uploaded_file:
        return jsonify({
            "ok": False,
            "error": "업로드된 이미지가 없습니다. 먼저 사진을 업로드해 주세요."
        }), 400

    image_path = os.path.join(UPLOAD_DIR, uploaded_file)

    if not os.path.exists(image_path):
        return jsonify({
            "ok": False,
            "error": "업로드된 이미지 파일을 찾을 수 없습니다."
        }), 404

    try:
        detected_items = detect_furniture_from_image(image_path)

        if not detected_items:
            return jsonify({
                "ok": False,
                "error": "이미지에서 가구를 탐지하지 못했습니다."
            }), 404

        recommendations = {}

        for item_name in detected_items:
            query = detected_item_to_query(item_name)
            products = search_naver_shopping(query=query, display=3)

            recommendations[item_name] = {
                "search_query": query,
                "products": products
            }

        return jsonify({
            "ok": True,
            "uploaded_file": uploaded_file,
            "detected_items": detected_items,
            "recommendations": recommendations
        })

    except Exception as e:
        print("업로드 이미지 기반 추천 API 오류:", e)
        return jsonify({
            "ok": False,
            "error": "업로드 이미지 기반 추천 중 오류가 발생했습니다."
        }), 500


if __name__ == "__main__":
    app.run(debug=True)
