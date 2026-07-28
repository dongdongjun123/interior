# 인테리어 프로젝트 — 레포 구조

`interior/`는 **단일 git 레포**로, 관심사별로 폴더를 분리했습니다.
프론트/백엔드/model1(사진 추천)/model2(평면도)가 한 프로세스에서 서로 import하므로 **가상환경·requirements는 루트 하나**로 통일합니다.

## 최종 구조

```
interior/
├── frontend/                  # 사용자 화면
│   ├── templates/             # Jinja2 템플릿 (index, upload, loading, floorplan, prompt, result …)
│   └── static/
│       ├── css/  js/          # 화면 스타일·스크립트
│       └── uploads/ generated/  # 런타임 산출물 (gitignore, .gitkeep만 커밋)
│
├── backend/                   # Flask 서버 (라우팅·API·DB)
│   ├── app.py                 # 진입점. model1·model2·shared import, 네이버쇼핑 API + YOLO 가구탐지
│   ├── ai_backend.py          # 이미지 생성 헬퍼
│   └── database.py            # 가구/평면도 mock 데이터
│                              # (yolov8n.pt: YOLO 가중치는 첫 실행 시 자동 다운로드)
│
├── model1/                    # ① 프롬프트 → 무드 사진 추천 (CLIP)
│   ├── __init__.py
│   ├── search.py              # 프롬프트 → 유사 이미지 top-K (CLIP 코사인 유사도)
│   ├── preprocess.py          # 이미지 수집·전처리
│   ├── gemini_extract.py      # Gemini 특징 추출 + UMAP 2D 시각화(분석용)
│   ├── run_gemini_features.py # gemini_extract 실행 래퍼(CLI)
│   └── notebooks/06_gemini_features.ipynb
│
├── model2/                    # ② 사진 → 2D 평면도 생성 (Gemini + 규칙 렌더러)
│   ├── __init__.py
│   ├── interior_to_floorplan.py  # 하위 호환 re-export 레이어 (기존 import 경로 유지)
│   ├── config.py              # model2 상수·.env 로드·프롬프트 로드(load_prompt)
│   ├── client.py              # Gemini 클라이언트 생성·API 재시도(429/503)
│   ├── io_utils.py            # 파일/이미지 IO·산출물 경로·캐시 판정·텍스트 파서
│   ├── gemini_steps.py        # Gemini 저수준 호출(분석/평면도/layout/SVG/교정)
│   ├── pipeline.py            # 고수준 단계(run_*_step)·generate_floorplan_for_web
│   ├── analysis_to_layout.py  # 분석 결과 → 렌더러용 layout 변환
│   ├── detection_evidence.py  # Florence 탐지 → Gemini 근거 텍스트
│   ├── rule_based_svg.py      # layout JSON → 아이소메트릭 SVG 렌더러(무료)
│   ├── render.py              # 노트북 시각화(matplotlib/HTML)
│   └── cli.py                 # CLI main() — 배치 처리 진입점
│
├── shared/                    # ⭐ model1·model2·backend 공용 설정
│   ├── __init__.py
│   └── config.py              # PROJECT_ROOT 및 경로·모델 상수, 무드 vocab
│
├── prompts/                   # ⭐ 모든 Gemini 프롬프트 (*.txt)
│   ├── analysis.txt  floorplan.txt  layout_detail.txt
│   ├── layout_refine.txt  svg_floorplan.txt   # ← model2/config.load_prompt
│   └── rule_based_layout.txt                  # ← model2/rule_based_svg
│
├── room-object-detection/     # Florence-2 가구 탐지 (별도 환경 — transformers 4.49 고정)
│   ├── detect.py              # 사진 → 가구 바운딩박스 JSON (--out 지정 가능)
│   ├── module/                # detector_florence.py, gpu_config.py
│   └── requirements.txt       # ⚠️ 메인 venv와 충돌 → 별도 conda 환경(roomdet)에서 실행
│
├── orchestration/             # 사진 → Florence 탐지 → Gemini 근거주입 → SVG 오케스트레이터
│   └── run_floorplan.py       # ROOMDET_PYTHON(별도 환경)으로 detect.py를 subprocess 호출
│
├── images/                    # 무드 원본 이미지 (images/final)
├── data/                      # 임베딩·클러스터·번역 캐시 (대부분 gitignore)
├── output/floorplans/         # 평면도 생성 결과 (gitignore, .gitkeep만)
│
├── requirements.txt           # 통합 의존성 (venv 한 번)
├── .env / .env.example        # 공통 환경변수
├── venv/                      # 가상환경 (gitignore)
└── .gitignore
```

## 경로 규칙 (왜 이렇게 배치했나)

- **폴더 번호 = 파이프라인 순서.** model1이 고른 사진이 model2의 입력이 된다.
  (프롬프트 → `model1/search.py`로 사진 추천 → 사진 업로드 → `model2/pipeline.py`로 평면도)
- **`shared`는 두 모델이 함께 쓰는 설정만** 둔다 → `from shared.config import ...`.
- **`shared/config.py`의 `PROJECT_ROOT = 파일.parent.parent` = interior 루트.**
  그래서 `images/`, `data/`, `output/`, `prompts/`를 **루트 레벨**에 둬야 config 경로와 맞음.
- **프롬프트는 코드에 하드코딩하지 않고 루트 `prompts/*.txt`에서 로드**한다.
  `model2/config.load_prompt`와 `model2/rule_based_svg.load_prompt`가 같은 폴더를 공유.
- **`.env`는 각 모듈 import 시점에 먼저 로드**한다(`model2/config.py`, `model1/gemini_extract.py`).
  CLI 직접 실행이든 backend 경유든 `os.getenv(...)`가 항상 `.env` 값을 읽도록 하기 위함.
- `backend/app.py`는 프론트가 분리됐으므로 `Flask(template_folder=../frontend/templates, static_folder=../frontend/static)`.
- YOLO 가중치는 `backend/yolov8n.pt` (없으면 ultralytics가 자동 다운로드).

## model2 모듈 관계

`backend/app.py`와 노트북은 `from model2 import interior_to_floorplan`으로 쓸 수 있습니다.
`interior_to_floorplan.py`가 아래 모듈들의 공개 이름을 전부 re-export하는 **호환 레이어**이기 때문입니다.

```
interior_to_floorplan.py (호환 레이어, re-export)
  ├─ config.py       # 상수·프롬프트·.env
  ├─ client.py       # _get_client, _call_gemini_with_retry
  ├─ io_utils.py     # 경로·캐시·파서
  ├─ gemini_steps.py # analyze_interior, extract_rule_based_layout, refine_layout …
  ├─ pipeline.py     # run_*_step, convert_image, generate_floorplan_for_web ← backend 진입점
  ├─ render.py       # plot_*_figure, maybe_plot
  └─ cli.py          # main()
```

## 환경변수 (.env)

`.env.example`을 복사해 값을 채웁니다. 모두 루트 `.env` 하나에서 관리:

| 키 | 용도 | 기본값 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini 인증 (필수) | — |
| `GEMINI_ANALYSIS_MODEL` | model2 공간 분석 모델 | `gemini-2.5-flash` |
| `GEMINI_IMAGE_MODEL` | model2 평면도 이미지 모델 | `gemini-2.5-flash-image` |
| `GEMINI_FEATURE_MODEL` | model1 특징 추출 모델 | `gemini-2.5-flash-lite` |
| `GEMINI_THINKING_BUDGET` | 공간추론 thinking 예산(토큰) | `4096` |
| `GEMINI_LAYOUT_REFINE` | layout 자기교정 패스(0=끄기) | `1` |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | backend 가구 추천(네이버 쇼핑) | — |
| `ROOMDET_PYTHON` | Florence 탐지용 별도 환경 python 경로(비우면 Florence 끄기) | — |
| `ROOMDET_REQUIRE_GPU` | 1이면 GPU 없을 때 Florence 자동 skip(CPU 저속 방지) | `1` |

## 실행 방법

```bash
# 1) 가상환경 한 번만 (루트에서)
cd interior
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env           # 그리고 GEMINI_API_KEY / NAVER_* 채우기

# 2) 웹 서버 (backend 폴더 안에서 실행 — import ai_backend/database가 상대경로라서)
cd backend
python app.py                  # http://127.0.0.1:5000

# 3) 모델 스크립트 (반드시 루트에서 — model1/model2/shared import 때문)
cd interior
python -m model2.cli --help                 # 평면도 생성 (구: model2/interior_to_floorplan.py도 동작)
python model1/run_gemini_features.py --help # 무드 특징 추출

# 4) Florence 근거주입 오케스트레이터 (루트에서). ROOMDET_PYTHON 비우면 Florence 없이 Gemini만.
python orchestration/run_floorplan.py <사진경로>
```

> **Florence는 별도 환경이 필요**합니다. `transformers==4.49.0`이 메인 venv(5.x)와 충돌하므로
> `room-object-detection/README.md`의 conda 환경(`roomdet`)을 따로 만들고, 그 python 경로를
> `.env`의 `ROOMDET_PYTHON`에 넣으면 오케스트레이터가 subprocess로 호출합니다.
> GPU(RTX 등) 권장 — CPU로도 되지만 이미지 1장에 수 분 걸립니다.

## 참고

- **`room-object-detection`은 메인 venv와 의존성이 충돌**한다(transformers 4.49 vs 5.x).
  그래서 한 프로세스로 합치지 않고, 오케스트레이터가 별도 환경의 python을 subprocess로 호출한다.
  두 환경의 접점은 `detection.json` 파일 하나뿐 → 의존성 충돌이 원천 차단된다.
- Florence 탐지(`room-object-detection`)와 무드 검색(`model1/search.py`)은 모두 CLIP/Florence를
  쓰지만 서로 다른 경로다. 무드 검색은 메인 venv에서, Florence는 별도 환경에서 돈다.
