# 인테리어 프로젝트

사진 → 평면도/무드 분석(Gemini) → 인테리어 추천을 제공하는 Flask 풀스택 웹앱.

```
interior/
├── frontend/      # 화면 (Jinja2 템플릿 + static css/js) — Flask가 렌더링
├── backend/       # Flask 서버 (app.py = API + 화면 + 세션 한 곳에)
├── model1/        # 사진 → 2D 평면도 (Gemini) — 역할별 모듈로 분리
├── model2/        # 무드 분석 → 특징 추출 (Gemini, CLI)
├── mood_pipeline/ # model1·model2 공용 패키지 (config, gemini_extract, search, rule_based_svg …)
├── prompts/       # 모든 Gemini 프롬프트(*.txt) — model1·mood_pipeline 공유
├── images/ data/ output/   # 데이터·산출물
├── requirements.txt        # 통합 의존성 (가상환경 하나)
└── .env                    # API 키 (.env.example 복사해서 작성)
```

> **구조는 Flask 하나로 프론트+백엔드를 다 처리하는 풀스택 모놀리식**입니다.
> `app.py`를 실행하면 API와 화면이 함께 뜨며, 프론트를 따로 실행하지 않습니다.
> (React처럼 별도 프론트 서버 없음 → Docker도 불필요)

---

## 1. 준비 (공통)

`.env` 파일에 API 키를 넣습니다.
```bash
cp .env.example .env
# .env 를 열어 GEMINI_API_KEY / NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 채우기
```
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey (model1/model2 필수)
- `NAVER_CLIENT_ID/SECRET` — https://developers.naver.com/apps (가구 추천용, 없으면 그 기능만 비활성)
- 모델명·옵션(`GEMINI_ANALYSIS_MODEL`, `GEMINI_THINKING_BUDGET`, `GEMINI_LAYOUT_REFINE` 등)은 선택 —
  `.env`에 넣으면 코드 수정 없이 덮어쓸 수 있습니다. 자세한 목록은 [REPO_STRUCTURE.md](REPO_STRUCTURE.md#환경변수-env).

> **가상환경(venv)은 OS마다 다르므로 git에 포함하지 않습니다.**
> 아래 자기 환경에 맞는 방법으로 각자 생성하세요. Windows용/리눅스용을 이름을 나눠 공존시킵니다.

---

## 2-A. Windows (PowerShell / CMD)

```powershell
cd interior
python -m venv venv                 # 최초 1회
venv\Scripts\activate
pip install -r requirements.txt     # 최초 1회 (torch 등, 수 분)

# 웹 서버 실행
cd backend
python app.py
```
> `activate`에서 실행 차단 오류 시 1회: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## 2-B. WSL / Linux / macOS (bash)

```bash
cd /mnt/c/Users/jundo/Desktop/7min/interior   # WSL 경로 예시
python3 -m venv venv-linux          # 최초 1회 (Windows venv와 이름 분리)
source venv-linux/bin/activate
pip install -r requirements.txt     # 최초 1회

# 웹 서버 실행
cd backend
python app.py
```

> ⚠️ **환경을 섞지 마세요.** Windows에서 만든 `venv/`는 WSL에서 동작하지 않고
> (그 반대도 마찬가지), `ModuleNotFoundError: No module named 'flask'`가 납니다.
> WSL에서는 반드시 `venv-linux/`(리눅스용)를 만들어 `source venv-linux/bin/activate` 하세요.

---

## 3. 접속 / 종료

- 브라우저: **http://127.0.0.1:5000**
- 종료: 터미널에서 `Ctrl + C`

---

## 4. 모델 스크립트 (CLI)

웹앱과 별개로 모델을 직접 돌릴 때. **반드시 루트에서** 실행 (mood_pipeline import 때문).
가상환경은 위에서 만든 것을 activate한 상태로.

```bash
# 사진 → 평면도 (구 경로 python model1/interior_to_floorplan.py 도 그대로 동작)
python -m model1.cli --help

# 무드 특징 추출 + UMAP
python model2/run_gemini_features.py --help
```

---

## 참고

- 무드 검색(`mood_pipeline/search.py`, 프롬프트→유사 이미지 CLIP 검색)은 구현되어 backend `/mood-search`에서 사용 중.
- `model2/notebooks/06_gemini_features.ipynb` 는 실험용. 일부 셀은 미구현 모듈(`prompt_floorplan.py`)에 의존해 동작하지 않음.
- 실행 규칙 요약: **웹 서버는 `backend/`에서, 모델 스크립트는 루트에서.**
- 자세한 재구조화 기록은 [REPO_STRUCTURE.md](REPO_STRUCTURE.md) 참고.
