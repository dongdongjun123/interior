# 인테리어 프로젝트 — 단일 레포 정리 방안

> ✅ **재배치 완료** (아래 "0. 완료된 최종 구조" 참고). 이 아래 1~5번은 작업 배경/계획 기록용.

## 0. 완료된 최종 구조

`interior/` 루트에 새 폴더를 만들어 재배치를 마쳤습니다. **원본(`floorplan-svg/`, `mood-search/`)은
아직 지우지 않았습니다** — 검증 후 삭제하세요 (아래 "정리(cleanup)" 참고). model3(mood-search)는 요청대로 제외.

```
interior/
├── frontend/              # 화면 (static/css·js, templates)  — ai_interior 신버전 기준
│   └── static/{uploads,generated}/   # 런타임 산출물 (.gitkeep만 커밋)
├── backend/               # Flask 서버
│   ├── app.py             # ← ai_interior 신버전 (네이버쇼핑 API + YOLO 포함)
│   ├── ai_backend.py
│   └── database.py
├── model1/                # 사진 → 2D 평면도
│   └── interior_to_floorplan.py
├── model2/                # 무드 분석 실행 스크립트·노트북
│   ├── run_gemini_features.py
│   └── notebooks/
├── mood_pipeline/         # ⭐ model1·model2 공용 패키지 (config, gemini_extract 등)
├── images/                # 무드 원본 이미지 (images/final)
├── data/                  # 임베딩·클러스터 캐시 (대부분 gitignore)
├── output/floorplans/     # 평면도 생성 결과 (gitignore, .gitkeep만)
├── requirements.txt       # 통합 의존성 (venv 한 번)
├── .env / .env.example    # 공통 환경변수
└── .gitignore
```

### 왜 이렇게 배치했나 (경로 규칙)
- `mood_pipeline`을 **루트 공용 패키지**로 올림 → model1의 `from mood_pipeline.config import ...`가 그대로 동작.
- `mood_pipeline/config.py`의 `PROJECT_ROOT = 파일.parent.parent` = **interior 루트**.
  그래서 `images/`, `data/`, `output/`을 **루트 레벨**에 둬야 config 경로(`PROJECT_ROOT/images` 등)와 맞음.
- `backend/app.py`는 프론트가 분리됐으므로 `Flask(template_folder=../frontend/templates, static_folder=../frontend/static)`로 수정함.
- YOLO 경로는 없던 `../interior-mood-search/yolov8n.pt` 대신 `backend/yolov8n.pt`로 변경(없으면 자동 다운로드).

### 실행 방법
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

# 3) 모델 스크립트 (반드시 루트에서 — mood_pipeline import 때문)
cd interior
python model1/interior_to_floorplan.py --help
python model2/run_gemini_features.py --help
```

### 원본 정리 (검증 후 실행)
새 구조가 정상 동작하는 걸 확인한 뒤에만:
```bash
cd interior
rm -rf floorplan-svg mood-search   # 기존 두 레포 폴더 제거
git init && git add . && git commit -m "chore: 단일 레포로 통합 (frontend/backend/model1/model2/mood_pipeline)"
```

---

## 1. 현재 상태 (문제점)

`interior/` 아래에 **git 레포가 2개**로 쪼개져 있고, 그 안에서 프론트가 또 중복되어 있습니다.

```
interior/
├── floorplan-svg/            ← git 레포 #1 (.git 존재)
│   ├── app.py                ← Flask 웹앱 (구버전 프론트/백엔드)
│   ├── ai_backend.py         ← 이미지 생성 (mock)
│   ├── database.py           ← 가구/평면도 mock DB
│   ├── interior_to_floorplan.py   ← [모델] 사진→2D 평면도 (Gemini)
│   ├── mood_pipeline/        ← [모델] 무드 분석→레이아웃 (Gemini/CLIP)
│   ├── run_gemini_features.py
│   ├── data/ images/ output/ notebooks/
│   ├── venv/ .venv 등
│   └── frontend/
│       └── ai_interior/      ← Flask 웹앱 (신버전, YOLO·.env·requests 추가)
│           ├── app.py        ← 루트 app.py의 발전 버전 (기능 중복)
│           ├── ai_backend.py / database.py
│           ├── static/ templates/
│
└── mood-search/              ← git 레포 #2 (.git 존재, 사실상 비어있음)
    ├── .gitignore / .venv     ← 코드 없음. "프롬프트→유사 이미지 검색" 레포로 분리됨
```

### 핵심 문제
1. **git 레포가 2개** (`floorplan-svg/.git`, `mood-search/.git`) → 하나로 합쳐야 함
2. **프론트 중복** — 루트 `app.py`(구) vs `frontend/ai_interior/app.py`(신). 신버전만 남기면 됨
3. **모델 코드가 웹앱 안에 섞여 있음** — `interior_to_floorplan.py`, `mood_pipeline/`가 Flask 앱과 같은 폴더에 있음
4. **폴더명이 역할과 안 맞음** — `floorplan-svg`가 사실상 전체 프로젝트 루트 역할

---

## 2. 목표 구조

`interior/`를 **단일 git 레포**로 만들고, 아래 4개 폴더로 관심사를 분리합니다.

```
interior/                     ← 여기서 git init (단일 레포)
├── .git/
├── .gitignore                ← 통합 gitignore (venv, .env, 산출물)
├── .env.example              ← 공통 환경변수 템플릿
├── requirements.txt          ← ⭐ 통합 의존성 (루트 1개, venv 한 번만)
├── README.md                 ← 전체 프로젝트 개요 + 실행법
│
├── frontend/                 ← 사용자 화면 (HTML/CSS/JS + 템플릿)
│   ├── static/  (css, js, uploads, generated)
│   └── templates/
│
├── backend/                  ← Flask 서버 (API·라우팅·DB)
│   ├── app.py                ← frontend/ai_interior/app.py (신버전) 기준
│   ├── ai_backend.py
│   └── database.py
│
├── model1/                   ← 사진 → 2D 평면도 생성
│   ├── interior_to_floorplan.py
│   └── output/floorplans/
│
├── model2/                   ← 무드 분석 → 레이아웃 파이프라인
│   ├── mood_pipeline/  (config, gemini_extract, preprocess, analysis_to_layout, rule_based_svg)
│   ├── run_gemini_features.py
│   ├── notebooks/  (06_gemini_features.ipynb)
│   └── images/  data/
│
└── model3-search/ (선택)     ← mood-search 레포 내용 (프롬프트→유사 이미지 검색)
    └── (현재 코드 없음 — 개발 시작하면 여기에)
```

> **의존성 관리:** `requirements.txt`는 **폴더별로 두지 않고 루트에 하나만** 둡니다.
> 프론트/백엔드/model1/model2가 한 프로세스에서 서로 import하므로, 가상환경을 한 번만
> 만들어 통합 requirements를 설치하면 전체가 동작합니다. (아래 3-D·4 참고)

> **참고:** 사용자가 말한 "model1, model2"는 지금 코드 기준으로
> - **model1** = `interior_to_floorplan.py` (평면도 생성)
> - **model2** = `mood_pipeline/` (무드 분석/레이아웃)
> 에 해당합니다. `mood-search`는 아직 코드가 없어 **model3(검색)** 자리로 남겨두거나 이번 정리에서 제외해도 됩니다. → 아래 3-B 결정 필요

---

## 3. 정리 순서 (실행 계획)

### 사전 백업
```bash
# 혹시 모를 상황 대비, interior 폴더 통째로 복사 백업
```

### STEP 1 — 프론트 중복 정리 (신버전 채택)
- `frontend/ai_interior/`(YOLO·.env·requests 붙은 신버전)를 기준으로 삼는다.
- 루트 `app.py`, `ai_backend.py`, `database.py`(구버전)는 **삭제**.
  (신버전과 diff 확인 후 신버전이 상위집합이면 안전하게 제거)

### STEP 2 — 폴더 재배치
`interior/` 바로 아래로 이동:
| 옮길 대상 | → 도착지 |
|---|---|
| `floorplan-svg/frontend/ai_interior/static`, `templates` | `frontend/` |
| `floorplan-svg/frontend/ai_interior/{app,ai_backend,database}.py` | `backend/` |
| `floorplan-svg/interior_to_floorplan.py` + `output/floorplans` | `model1/` |
| `floorplan-svg/mood_pipeline/`, `run_gemini_features.py`, `notebooks/`, `images/`, `data/` | `model2/` |
| `mood-search/` 내용 | `model3-search/` (또는 제외) |

> **주의:** `interior_to_floorplan.py`가 `from mood_pipeline.config import ...`로 model2에 의존함.
> → 분리 시 import 경로 수정 필요하거나, `mood_pipeline`을 공용 패키지로 둘지 결정 필요 (아래 3-A).

### STEP 3 — git 레포 통합
```bash
# 기존 하위 .git 제거 (히스토리 보존이 필요하면 subtree/submodule 검토 — 아래 3-C)
rm -rf floorplan-svg/.git
rm -rf mood-search/.git

# interior 루트에서 새로 시작
cd interior
git init
git add .
git commit -m "chore: 단일 레포로 통합 (frontend/backend/model1/model2)"
```

### STEP 4 — 설정 파일 통합
- 루트 `.gitignore` 작성 (venv, .venv, __pycache__, .env, output 산출물 등 — 기존 2개 gitignore 병합)
- 루트 `.env.example` 작성 (Gemini API 키 등 공통 항목)
- **`requirements.txt` 통합** — 기존 4개 파일을 루트 한 개로 병합 (아래 참고). 폴더별 requirements는 **삭제**.
- 기존 `venv/`, `.venv/`는 **삭제** 후 루트에서 새 가상환경 하나만 생성.

**통합 후 실행 (한 번만):**
```bash
cd interior
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python backend/app.py
```

**병합할 통합 `requirements.txt` (초안):**
기존 4개 파일(`requirements.txt` ×2, `requirements-gemini.txt`, `mood-search/requirements-ml.txt`)의 합집합.
```
# --- Web (backend/frontend) ---
Flask>=3.0
Pillow>=10.0
requests
python-dotenv

# --- model1/model2: Gemini 평면도·무드 ---
google-genai
ultralytics          # YOLO (backend app.py에서 사용)
numpy
matplotlib
scikit-learn
umap-learn
tqdm

# --- model3-search: 프롬프트→이미지 검색 (mood-search) ---
torch                # ⚠️ 무거움. 검색 기능 안 쓰면 아래 3-B에서 제외 가능
torchvision
transformers
pandas
deep-translator
```
> ⚠️ `torch`/`torchvision`/`transformers`는 용량이 크고 GPU/CUDA 이슈가 있을 수 있습니다.
> mood-search(검색)를 이번에 제외하면(3-B) 이 블록은 빼도 됩니다.

---

## 4. 결정이 필요한 항목 (❓ 확인 요청)

- **3-A. `mood_pipeline` 의존성:** `interior_to_floorplan.py`(model1)가 `mood_pipeline`(model2)을 import함.
  → (a) 그냥 model1이 model2를 참조하게 두기 / (b) `mood_pipeline.config`를 루트 `common/`으로 빼기 — 어느 쪽?
- **3-B. mood-search:** 코드가 없는데 `model3-search/`로 자리만 만들지 / 이번 정리에선 제외할지?
- **3-C. git 히스토리:** 기존 두 레포의 커밋 히스토리를 **버리고 새로 시작**해도 되는지, 아니면 보존(subtree merge)해야 하는지?
- **3-D. 가상환경/의존성:** ✅ **결정됨** — 폴더별 requirements/venv를 없애고 **루트 단일 `requirements.txt` + 단일 venv**로 통일. (가상환경 한 번만 켜면 전체 동작)

---

## 5. 최종 목표 트리 (요약)

```
interior/
├── frontend/      # 화면
├── backend/       # Flask 서버·API
├── model1/        # 사진 → 평면도
├── model2/        # 무드 분석 → 레이아웃
├── requirements.txt # 통합 의존성 (venv 한 번만)
├── README.md
├── .gitignore
└── .env.example
```
