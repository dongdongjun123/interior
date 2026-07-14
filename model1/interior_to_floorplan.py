# 인테리어 사진 → Gemini API → 2D 평면도 변환
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from PIL import Image

from mood_pipeline.config import IMAGE_EXTENSIONS, IMAGE_ROOT, PROJECT_ROOT

# .env를 import 시점에 먼저 로드해야 아래 os.getenv(...)들이 .env 값을 읽는다.
# (CLI 직접 실행 등 backend를 안 거치는 경로에서도 .env가 반영되도록)
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "floorplans"
# 모델·설정 기본값은 .env로 덮어쓸 수 있다(없으면 아래 값 사용).
DEFAULT_ANALYSIS_MODEL = os.getenv("GEMINI_ANALYSIS_MODEL", "gemini-2.5-flash")
DEFAULT_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
MAX_API_RETRIES = 5
# thinking 예산(토큰): 공간추론 품질↑. 0=끄기, -1=동적. env GEMINI_THINKING_BUDGET로 조정.
DEFAULT_THINKING_BUDGET = int(os.getenv("GEMINI_THINKING_BUDGET", "4096"))

# 프롬프트는 코드에 하드코딩하지 않고 model1/prompts/*.txt에서 읽어온다.
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """prompts/<name>.txt 파일을 읽어 프롬프트 문자열로 반환 (앞뒤 공백 제거)."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


# 각 단계 프롬프트를 파일에서 로드 (플레이스홀더는 {analysis}/{layout_json} 형태, replace로 치환)
ANALYSIS_PROMPT = load_prompt("analysis")
FLOORPLAN_PROMPT = load_prompt("floorplan")
LAYOUT_DETAIL_PROMPT = load_prompt("layout_detail")
SVG_FLOORPLAN_PROMPT = load_prompt("svg_floorplan")


def _load_env() -> None:
    # 루트 .env에서 환경변수(API 키 등) 로드
    load_dotenv(PROJECT_ROOT / ".env")


def _get_client() -> genai.Client:
    # API 키를 확인하고 Gemini 클라이언트 생성
    api_key = os.getenv("GEMINI_API_KEY", "").strip()  # 환경변수에서 키 읽기(공백 제거)
    if not api_key:  # 키가 비어 있으면 실행 불가 → 안내 메시지와 함께 중단
        raise RuntimeError(
            "GEMINI_API_KEY가 없습니다. 프로젝트 루트의 .env 파일에 API 키를 넣어 주세요."
        )
    return genai.Client(api_key=api_key)  # 키로 인증된 클라이언트 반환


def _guess_mime(path: Path) -> str:
    # 파일 확장자로 MIME 타입 추정 (실패 시 기본값 사용)
    mime, _ = mimetypes.guess_type(str(path))  # 표준 라이브러리로 1차 추정
    if mime:  # 추정 성공하면 그대로 사용
        return mime
    ext = path.suffix.lower()  # 실패 시 확장자를 소문자로 추출
    fallback = {  # 확장자 → MIME 수동 매핑 테이블
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    return fallback.get(ext, "image/jpeg")  # 매핑에 없으면 jpeg로 폴백


def _load_image_part(path: Path) -> types.Part:
    # 이미지 파일을 Gemini 입력용 Part 객체로 변환
    return types.Part.from_bytes(
        data=path.read_bytes(),
        mime_type=_guess_mime(path),
    )


def list_images(folder: Path) -> list[Path]:
    # 폴더 안의 지원 이미지 파일을 정렬해 목록으로 반환
    if not folder.exists():  # 폴더 자체가 없으면 오류
        raise FileNotFoundError(f"이미지 폴더가 없습니다: {folder}")
    files = [
        p
        for p in sorted(folder.iterdir())  # 이름순 정렬로 처리 순서 고정
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS  # 지원 확장자 파일만
    ]
    if not files:  # 이미지가 하나도 없으면 오류
        raise FileNotFoundError(f"이미지 파일이 없습니다: {folder}")
    return files


def _output_paths(image_path: Path, output_dir: Path) -> dict[str, Path]:
    # 원본 파일명 기준으로 결과물(평면도/JSON/분석) 저장 경로 묶음 생성
    stem = image_path.stem  # 확장자 뺀 파일명 (모든 산출물의 공통 접두어)
    return {
        "plan": output_dir / f"{stem}_floorplan.png",  # Gemini 생성 평면도 이미지
        "plan_svg": output_dir / f"{stem}_floorplan.svg",  # Gemini 생성 SVG 평면도
        "rule_svg": output_dir / f"{stem}_rule_based_floorplan.svg",  # 규칙 기반 SVG
        "layout": output_dir / f"{stem}_layout.json",  # 가구 좌표 layout JSON
        "analysis": output_dir / f"{stem}_analysis.txt",  # 공간 분석 텍스트
        "meta": output_dir / f"{stem}_meta.json",  # 처리 결과 메타데이터
    }


def _retry_seconds_from_error(exc: Exception, attempt: int) -> float:
    # 429: "retry in XXs" 파싱 / 503: 지수 백오프
    msg = str(exc)  # 예외 메시지를 문자열로
    match = re.search(r"retry in ([0-9.]+)s", msg, re.I)  # 서버가 알려준 대기 시간 찾기
    if match:  # 명시적 대기 시간이 있으면
        return float(match.group(1)) + 1.0  # 그 값 + 여유 1초
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)  # 상태 코드 추출
    if status == 503 or "503" in msg or "UNAVAILABLE" in msg:  # 서버 과부하(503)면
        return min(10.0 * (2 ** (attempt - 1)), 60.0)  # 지수 백오프(최대 60초)
    return 35.0  # 그 외(429 등)는 기본 35초 대기


def _is_retryable_gemini_error(exc: Exception) -> bool:
    # 재시도해도 되는 오류인지 판별 (429/503 등 일시적 오류)
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)  # 상태 코드 추출
    if status in (429, 503, 502, 504):  # 할당량/과부하/게이트웨이 오류는 재시도 대상
        return True
    msg = str(exc)  # 코드가 없을 때 메시지 문자열로 판별
    if any(token in msg for token in ("429", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE")):  # 대표 키워드 포함 시
        return True
    return False  # 그 외에는 재시도하지 않음


def _call_gemini_with_retry(label: str, fn):
    # 429 할당량 / 503 일시 과부하 시 대기 후 재시도
    last_exc: Exception | None = None  # 마지막 예외 보관 (모두 실패 시 재발생용)
    for attempt in range(1, MAX_API_RETRIES + 1):  # 1회차부터 최대 재시도 횟수까지
        try:
            if attempt == 1:  # 첫 시도면 호출 시작 안내
                print(f"[{label}] API 호출 중… (429/503이면 자동 재시도, Stop 누르지 마세요)")
            else:  # 재시도면 몇 번째인지 표시
                print(f"[{label}] 재시도 {attempt}/{MAX_API_RETRIES}…")
            return fn()  # 실제 Gemini 호출 (성공하면 바로 반환)
        except (ClientError, ServerError) as exc:  # API 오류 발생 시
            last_exc = exc  # 예외 저장
            if _is_retryable_gemini_error(exc) and attempt < MAX_API_RETRIES:  # 재시도 가능하고 횟수 남았으면
                wait = _retry_seconds_from_error(exc, attempt)  # 대기 시간 계산
                reason = (  # 사용자에게 보여줄 원인 문구
                    "할당량 초과"
                    if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)
                    else "서버 과부하"
                )
                print(f"[{label}] API {reason} → {wait:.0f}초 후 재시도 ({attempt}/{MAX_API_RETRIES})")
                time.sleep(wait)  # 계산된 시간만큼 대기
                continue  # 다음 시도로
            status = getattr(exc, "status_code", None) or getattr(exc, "code", None)  # 최종 실패 원인 판별
            if status == 503 or "UNAVAILABLE" in str(exc):  # 503이면 일시 장애 안내
                raise RuntimeError(
                    f"Gemini API 일시 장애(503). 수요가 몰려 응답하지 못했습니다. "
                    f"1~2분 후 셀만 다시 실행해 보세요. ({exc})"
                ) from exc
            raise RuntimeError(  # 그 외(429 등)는 할당량 안내
                "Gemini API 할당량/요금 한도 초과(429). "
                "https://ai.dev/rate-limit 에서 사용량 확인 후 "
                "잠시 뒤 다시 시도하거나 유료 플랜/결제 설정을 확인하세요."
            ) from exc
    raise last_exc  # type: ignore[misc]  # 모든 재시도 실패 시 마지막 예외 재발생


def _analysis_cache_valid(path: Path) -> bool:
    # 저장된 분석 결과가 재사용 가능한지 검사 (필수 키워드 포함 여부)
    if not path.exists():  # 파일 없으면 캐시 무효
        return False
    text = path.read_text(encoding="utf-8")  # 저장된 분석 텍스트 읽기
    # 가구 목록과 top-down 관련 표현이 모두 있어야 정상 분석으로 간주
    return '"furniture"' in text and ("top-down" in text.lower() or "layout json" in text.lower())


def _layout_cache_valid(path: Path) -> bool:
    # 저장된 layout JSON이 유효한 스키마인지 검사
    if not path.exists():  # 파일 없으면 무효
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))  # JSON 파싱 시도
    except json.JSONDecodeError:  # 깨진 JSON이면 무효
        return False
    return data.get("version") == 2 and isinstance(data.get("objects"), list)  # 버전2 + objects 배열 확인


def _svg_cache_valid(layout_path: Path, svg_path: Path) -> bool:
    # SVG 캐시가 최신 layout보다 새것인지 검사
    if not svg_path.exists() or svg_path.stat().st_size <= 100:  # 파일 없거나 사실상 빈 파일이면 무효
        return False
    if not _layout_cache_valid(layout_path):  # 기반이 되는 layout이 무효면 SVG도 무효
        return False
    return svg_path.stat().st_mtime >= layout_path.stat().st_mtime  # SVG가 layout보다 최신이어야 유효


def analyze_interior(
    client: genai.Client,
    image_path: Path,
    *,
    model: str,
) -> str:
    # 사진을 Gemini에 보내 공간 구조를 텍스트 리포트로 분석
    def _run():  # 재시도 래퍼에 넘길 실제 호출 로직
        response = client.models.generate_content(  # 프롬프트 + 이미지를 함께 전송
            model=model,
            contents=[ANALYSIS_PROMPT, _load_image_part(image_path)],
        )
        text = (response.text or "").strip()  # 응답 텍스트 추출(없으면 빈 문자열)
        if not text:  # 빈 응답이면 오류 처리
            raise RuntimeError(f"공간 분석 결과가 비어 있습니다: {image_path.name}")
        return text  # 분석 텍스트 반환

    return _call_gemini_with_retry("공간 분석", _run)  # 재시도 로직으로 감싸 실행


def generate_floorplan(
    client: genai.Client,
    image_path: Path,
    analysis: str,
    *,
    model: str,
) -> Image.Image:
    # 분석 결과를 바탕으로 Gemini 이미지 모델로 평면도 그림 생성
    prompt = FLOORPLAN_PROMPT.replace("{analysis}", analysis)  # 분석 텍스트를 프롬프트에 삽입

    def _run():
        response = client.models.generate_content(
            model=model,
            contents=[prompt, _load_image_part(image_path)],  # 프롬프트 + 원본 사진
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],  # 텍스트가 아닌 이미지로 응답받기
                image_config=types.ImageConfig(aspect_ratio="1:1"),  # 정사각형 비율
            ),
        )
        for part in response.parts:  # 응답 조각들을 순회
            if part.inline_data:  # 이미지 데이터가 담긴 조각을 찾으면
                return part.as_image()  # PIL 이미지로 변환해 반환
        raise RuntimeError(f"평면도 이미지가 생성되지 않았습니다: {image_path.name}")  # 이미지가 없으면 오류

    return _call_gemini_with_retry("2D 평면도 생성", _run)  # 재시도 로직으로 감싸 실행


def extract_svg_from_text(raw: str) -> str:
    # 응답 텍스트에서 <svg>...</svg> 부분만 추출 (코드블록 마커 제거)
    text = raw.strip()  # 앞뒤 공백 제거
    if text.startswith("```"):  # 마크다운 코드블록으로 감싸져 있으면
        text = re.sub(r"^```(?:svg|xml)?\s*", "", text, flags=re.I)  # 시작 ``` 제거
        text = re.sub(r"\s*```$", "", text)  # 끝 ``` 제거
    match = re.search(r"(<svg[\s\S]*?</svg>)", text, re.I)  # <svg> 블록 검색
    if not match:  # SVG를 못 찾으면 오류
        raise RuntimeError("응답에서 SVG(<svg>...</svg>)를 찾을 수 없습니다.")
    return match.group(1).strip()  # 찾은 SVG 문자열 반환


def extract_json_from_text(raw: str) -> dict:
    # 응답 텍스트에서 JSON 객체({...}) 부분만 추출해 파싱
    text = raw.strip()  # 앞뒤 공백 제거
    if text.startswith("```"):  # 코드블록으로 감싸져 있으면
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)  # 시작 ``` 제거
        text = re.sub(r"\s*```$", "", text)  # 끝 ``` 제거
    start = text.find("{")  # 첫 중괄호 위치
    end = text.rfind("}")  # 마지막 중괄호 위치
    if start < 0 or end <= start:  # 유효한 JSON 범위가 아니면 오류
        raise RuntimeError("응답에서 JSON 객체를 찾을 수 없습니다.")
    return json.loads(text[start : end + 1])  # 중괄호 범위만 잘라 파싱


def analyze_layout_detail(
    client: genai.Client,
    image_path: Path,
    analysis: str,
    *,
    model: str,
) -> dict:
    # 사진+분석을 바탕으로 SVG 렌더링용 상세 좌표 JSON 생성
    prompt = LAYOUT_DETAIL_PROMPT.replace("{analysis}", analysis)  # 분석 텍스트를 프롬프트에 삽입

    def _run():
        response = client.models.generate_content(
            model=model,
            contents=[prompt, _load_image_part(image_path)],  # 프롬프트 + 원본 사진
        )
        raw = (response.text or "").strip()  # 응답 텍스트 추출
        if not raw:  # 빈 응답이면 오류
            raise RuntimeError("상세 layout JSON 결과가 비어 있습니다.")
        data = extract_json_from_text(raw)  # 텍스트에서 JSON 파싱
        data.setdefault("version", 2)  # version 키가 없으면 2로 기본 설정
        if not isinstance(data.get("objects"), list):  # objects 배열 유무 검증
            raise RuntimeError("layout JSON에 objects 배열이 없습니다.")
        return data  # 파싱된 layout 딕셔너리 반환

    return _call_gemini_with_retry("상세 layout 분석", _run)  # 재시도 로직으로 감싸 실행


def generate_floorplan_svg(
    client: genai.Client,
    layout_json: str,
    image_path: Path,
    *,
    model: str,
) -> str:
    # 좌표 JSON을 바탕으로 Gemini가 SVG 평면도(텍스트)를 직접 생성
    prompt = SVG_FLOORPLAN_PROMPT.replace("{layout_json}", layout_json)  # 좌표 JSON을 프롬프트에 삽입

    def _run():
        response = client.models.generate_content(
            model=model,
            contents=[prompt, _load_image_part(image_path)],  # 프롬프트 + 원본 사진
        )
        raw = (response.text or "").strip()  # 응답 텍스트 추출
        if not raw:  # 빈 응답이면 오류
            raise RuntimeError("SVG 평면도 결과가 비어 있습니다.")
        return extract_svg_from_text(raw)  # 응답에서 <svg> 부분만 뽑아 반환

    return _call_gemini_with_retry("SVG 평면도 생성", _run)  # 재시도 로직으로 감싸 실행


def run_analysis_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
) -> dict:
    # 1단계: 공간 특징 추출 → txt 저장 (API 1회)
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 없으면 생성
    paths = _output_paths(image_path, output_dir)  # 이 이미지의 산출물 경로 묶음

    # 캐시가 유효하면 API 호출 없이 기존 분석 재사용
    if skip_existing and paths["analysis"].exists() and _analysis_cache_valid(paths["analysis"]):
        print(f"[{image_path.name}] 분석 캐시 사용 → {paths['analysis'].name}")
        return {
            "source": str(image_path),
            "analysis_file": str(paths["analysis"]),
            "analysis_model": analysis_model,
            "skipped": True,  # 건너뛰었음을 표시
        }

    print(f"[{image_path.name}] 공간 분석 중...")
    analysis = analyze_interior(client, image_path, model=analysis_model)  # Gemini로 분석 실행
    paths["analysis"].write_text(analysis, encoding="utf-8")  # 결과를 txt로 저장
    print(f"[{image_path.name}] 분석 저장 → {paths['analysis'].name}")
    return {
        "source": str(image_path),
        "analysis_file": str(paths["analysis"]),
        "analysis_model": analysis_model,
        "skipped": False,
    }


def _rule_layout_cache_valid(path: Path) -> bool:
    # rule-based layout JSON에 objects가 하나 이상 있는지 검사
    if not path.exists():  # 파일 없으면 무효
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))  # JSON 파싱 시도
    except json.JSONDecodeError:  # 깨진 JSON이면 무효
        return False
    objects = data.get("objects")  # objects 배열 꺼내기
    return isinstance(objects, list) and len(objects) > 0  # 비어있지 않은 리스트여야 유효


def _rule_layout_needs_coerce(path: Path) -> bool:
    """구 layout_detail v2(0~100) 등 — render 시 coerce_layout_v3 필요."""
    from mood_pipeline.rule_based_svg import _is_percent_coords  # 퍼센트 좌표 판별 함수

    if not path.exists():  # 파일 없으면 변환 불필요
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))  # JSON 파싱 시도
    except json.JSONDecodeError:  # 깨진 JSON이면 변환 불필요
        return False
    if data.get("schema") == "rule_based_v3":  # 이미 최신 스키마면 변환 불필요
        return False
    if data.get("version") == 2:  # 구 v2 스키마면 변환 필요
        return True
    objects = data.get("objects") or []  # objects 배열(없으면 빈 리스트)
    return bool(objects) and _is_percent_coords(objects[0])  # 좌표가 퍼센트 형식이면 변환 필요


def _rule_svg_cache_valid(layout_path: Path, svg_path: Path) -> bool:
    # rule-based SVG 캐시가 최신 layout·렌더러 버전과 일치하는지 검사
    from mood_pipeline import rule_based_svg  # 렌더러 모듈(파일 경로 확인용)
    from mood_pipeline.rule_based_svg import RENDERER_VERSION  # 현재 렌더러 버전 문자열

    if not svg_path.exists() or svg_path.stat().st_size <= 100:  # 파일 없거나 빈 파일이면 무효
        return False
    if not _rule_layout_cache_valid(layout_path):  # 기반 layout이 무효면 무효
        return False
    if _rule_layout_needs_coerce(layout_path):  # 구 스키마라 변환이 필요하면 캐시 무효
        return False
    try:
        head = svg_path.read_text(encoding="utf-8")[:600]  # SVG 앞부분만 읽기(버전 태그 확인용)
        if f"renderer-version:{RENDERER_VERSION}" not in head:  # 렌더러 버전이 다르면 무효
            return False
    except OSError:  # 읽기 실패 시 무효
        return False
    # mood_pipeline은 프로젝트 루트의 공용 패키지 → 모듈 실제 위치를 직접 사용
    renderer_src = Path(rule_based_svg.__file__).resolve()  # 렌더러 소스 파일 경로
    if renderer_src.exists() and svg_path.stat().st_mtime < renderer_src.stat().st_mtime:  # 렌더러가 SVG보다 최신이면 무효
        return False
    return svg_path.stat().st_mtime >= layout_path.stat().st_mtime  # SVG가 layout보다 최신이어야 유효


LAYOUT_REFINE_PROMPT = load_prompt("layout_refine")


def _build_layout_schema() -> types.Schema:
    # Gemini 응답을 강제할 layout JSON 스키마 정의 (구조화 출력용)
    from mood_pipeline.rule_based_svg import LAYOUT_OBJECT_TYPES  # 허용 가구 타입 목록

    num = lambda: types.Schema(type=types.Type.NUMBER)  # noqa: E731  # 숫자 필드 축약 헬퍼
    # 가구 하나를 나타내는 객체 스키마 (타입·라벨·좌표·크기·벽·신뢰도)
    obj_item = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "type": types.Schema(type=types.Type.STRING, enum=LAYOUT_OBJECT_TYPES),
            "label": types.Schema(type=types.Type.STRING),
            "x": num(),
            "y": num(),
            "w": num(),
            "h": num(),
            "wall": types.Schema(
                type=types.Type.STRING,
                enum=["left", "right", "top", "bottom", "none"],
            ),
            "confidence": num(),
        },
        required=["type", "x", "y", "w", "h", "wall", "confidence"],  # 모든 필드 필수
    )
    # 최상위 스키마: 방 정보 + 카메라 시점 + 가구 배열
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "room": types.Schema(  # 방 형태·가로세로 비율 등
                type=types.Type.OBJECT,
                properties={
                    "shape": types.Schema(type=types.Type.STRING),
                    "aspect_ratio": num(),
                    "description": types.Schema(type=types.Type.STRING),
                },
                required=["aspect_ratio"],
            ),
            "camera_view": types.Schema(type=types.Type.STRING),  # 카메라가 바라보는 방향
            "objects": types.Schema(type=types.Type.ARRAY, items=obj_item),  # 가구 객체 배열
        },
        required=["room", "objects"],  # 방 정보와 가구 배열은 필수
    )


def _layout_config(thinking_budget: int | None) -> types.GenerateContentConfig:
    # layout 추출용 Gemini 설정 구성 (JSON 스키마 + thinking 예산)
    tb = (  # thinking 예산: 인자 우선, 없으면 환경변수, 그것도 없으면 기본값
        thinking_budget
        if thinking_budget is not None
        else int(os.getenv("GEMINI_THINKING_BUDGET", str(DEFAULT_THINKING_BUDGET)))
    )
    kwargs: dict = dict(
        temperature=0.1,  # 낮은 온도로 일관된(덜 창의적인) 출력 유도
        response_mime_type="application/json",  # 응답을 JSON으로 강제
        response_schema=_build_layout_schema(),  # 위에서 만든 스키마 적용
    )
    try:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=tb)  # thinking 예산 설정 시도
    except Exception:  # SDK/모델이 thinking 미지원이면 조용히 생략
        pass
    return types.GenerateContentConfig(**kwargs)  # 최종 설정 객체 반환


def extract_rule_based_layout(
    client: genai.Client,
    image_path: Path,
    *,
    model: str,
    thinking_budget: int | None = None,
) -> dict:
    # 사진 → rule-based 렌더러용 layout JSON을 Gemini로 추출
    from mood_pipeline.rule_based_svg import RULE_BASED_LAYOUT_PROMPT, extract_json_from_text  # 전용 프롬프트·파서

    config = _layout_config(thinking_budget)  # JSON 스키마가 적용된 설정 준비

    def _run():
        response = client.models.generate_content(
            model=model,
            contents=[RULE_BASED_LAYOUT_PROMPT, _load_image_part(image_path)],  # 전용 프롬프트 + 사진
            config=config,  # 구조화 출력 설정 적용
        )
        raw = (response.text or "").strip()  # 응답 텍스트 추출
        if not raw:  # 빈 응답이면 오류
            raise RuntimeError("rule-based layout JSON 결과가 비어 있습니다.")
        data = extract_json_from_text(raw)  # JSON 파싱
        if not isinstance(data.get("objects"), list):  # objects 배열 검증
            raise RuntimeError("layout JSON에 objects 배열이 없습니다.")
        return data  # 파싱된 layout 반환

    return _call_gemini_with_retry("rule-based layout 추출", _run)  # 재시도 로직으로 감싸 실행


def refine_layout(
    client: genai.Client,
    image_path: Path,
    layout: dict,
    *,
    model: str,
    thinking_budget: int | None = None,
) -> dict:
    """자기교정 패스(API 1회 추가): 1차 layout을 사진과 대조해 오류만 수정."""
    from mood_pipeline.rule_based_svg import extract_json_from_text  # JSON 파서

    payload = json.dumps(  # 교정 대상인 현재 layout을 JSON 문자열로 직렬화
        {
            "room": layout.get("room", {}),  # 방 정보
            "camera_view": layout.get("camera_view", ""),  # 카메라 시점
            "objects": layout.get("objects", []),  # 가구 목록
        },
        ensure_ascii=False,  # 한글 등 유니코드 그대로 유지
    )
    prompt = LAYOUT_REFINE_PROMPT.replace("{layout_json}", payload)  # 교정 프롬프트에 현재 layout 삽입
    config = _layout_config(thinking_budget)  # 동일한 구조화 출력 설정 사용

    def _run():
        response = client.models.generate_content(
            model=model,
            contents=[prompt, _load_image_part(image_path)],  # 교정 프롬프트 + 사진
            config=config,
        )
        raw = (response.text or "").strip()  # 응답 텍스트 추출
        if not raw:  # 빈 응답이면 오류
            raise RuntimeError("자기교정 결과가 비어 있습니다.")
        data = extract_json_from_text(raw)  # 교정된 JSON 파싱
        if not isinstance(data.get("objects"), list) or not data["objects"]:  # 가구 배열 유효성 검증
            raise RuntimeError("자기교정 JSON에 objects가 없습니다.")
        return data  # 교정된 layout 반환

    return _call_gemini_with_retry("layout 자기교정", _run)  # 재시도 로직으로 감싸 실행


def run_rule_based_layout_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
    refine: bool | None = None,
) -> dict:
    # Gemini 1회: 사진 → rule-based renderer용 layout JSON
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if skip_existing and _rule_layout_cache_valid(paths["layout"]):  # 유효한 layout 캐시가 있으면
        if _rule_layout_needs_coerce(paths["layout"]):  # 구 스키마면 변환 안내만
            print(
                f"[{image_path.name}] ⚠ 구 스키마 layout 캐시 — SVG 렌더 시 자동 변환됩니다. "
                "정확한 배치는 FORCE_LAYOUT=True 로 재추출하세요."
            )
        else:  # 최신 스키마면 캐시 사용 안내
            print(f"[{image_path.name}] layout JSON 캐시 사용 → {paths['layout'].name}")
        return {  # API 호출 없이 캐시 정보 반환
            "source": str(image_path),
            "layout_file": str(paths["layout"]),
            "analysis_model": analysis_model,
            "renderer": "rule_based_v3",
            "skipped": True,
        }

    if refine is None:  # 자기교정 여부가 지정 안 됐으면 환경변수로 결정
        refine = os.getenv("GEMINI_LAYOUT_REFINE", "1").strip().lower() not in (  # 0/false/no/빈값이면 끄기
            "0",
            "false",
            "no",
            "",
        )

    print(f"[{image_path.name}] Gemini layout 추출 중...")
    layout = extract_rule_based_layout(client, image_path, model=analysis_model)  # 1차 layout 추출
    refined = False  # 교정 적용 여부 플래그
    if refine:  # 자기교정이 켜져 있으면
        try:
            print(f"[{image_path.name}] 자기교정(refine) 중... (API 1회 추가)")
            corrected = refine_layout(client, image_path, layout, model=analysis_model)  # 교정 호출
            layout = corrected  # 교정 결과로 교체
            refined = True
        except Exception as exc:  # 교정 실패해도 1차 결과로 계속 진행
            print(f"[{image_path.name}] 자기교정 건너뜀(1차 결과 사용): {exc}")

    layout["schema"] = "rule_based_v3"  # 최신 스키마 태그 부여
    paths["layout"].write_text(  # layout을 보기 좋게(indent) JSON으로 저장
        json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[{image_path.name}] layout 저장 → {paths['layout'].name} "
        f"({len(layout.get('objects', []))} objects, refined={refined})"
    )
    return {
        "source": str(image_path),
        "layout_file": str(paths["layout"]),
        "analysis_model": analysis_model,
        "object_count": len(layout.get("objects", [])),
        "renderer": "rule_based_v3",
        "refined": refined,
        "skipped": False,
    }


def run_rule_based_svg_step(
    image_path: Path,
    output_dir: Path,
    *,
    skip_existing: bool = True,
    title: str | None = None,
) -> dict:
    # 파이썬 규칙 기반 렌더러로 SVG 생성 (Gemini API 호출 없음)
    import importlib  # 렌더러 모듈 리로드용

    import mood_pipeline.rule_based_svg as rbs  # 규칙 기반 렌더러

    importlib.reload(rbs)  # 렌더러를 다시 로드해 최신 코드 반영
    save_svg = rbs.save_svg  # SVG 저장 함수 참조

    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if not paths["layout"].exists():  # layout JSON이 없으면 렌더 불가
        raise FileNotFoundError(
            f"layout JSON 없음: {paths['layout']} — run_rule_based_layout_step() 먼저 실행"
        )

    if skip_existing and _rule_svg_cache_valid(paths["layout"], paths["rule_svg"]):  # 유효한 SVG 캐시가 있으면
        print(f"[{image_path.name}] rule-based SVG 캐시 사용 → {paths['rule_svg'].name}")
        return {  # 렌더링 없이 캐시 정보 반환
            "source": str(image_path),
            "floorplan_svg": str(paths["rule_svg"]),
            "layout_file": str(paths["layout"]),
            "format": "svg",
            "renderer": "python_rule_based_v3",
            "skipped": True,
        }

    layout = json.loads(paths["layout"].read_text(encoding="utf-8"))  # 저장된 layout 읽어오기
    svg_title = title or f"Floor plan — {image_path.stem}"  # SVG 제목(지정 없으면 파일명 기반)
    print(f"[{image_path.name}] rule-based SVG 렌더링 중... (renderer {rbs.RENDERER_VERSION})")
    save_svg(layout, paths["rule_svg"], title=svg_title)  # layout을 SVG로 렌더링해 저장
    print(f"[{image_path.name}] SVG 저장 → {paths['rule_svg'].name}")
    return {
        "source": str(image_path),
        "floorplan_svg": str(paths["rule_svg"]),
        "layout_file": str(paths["layout"]),
        "format": "svg",
        "renderer": "python_rule_based_v3",
        "skipped": False,
    }


def run_layout_detail_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
) -> dict:
    # 1.5단계: 사진+분석 → 상세 좌표 JSON (SVG용, API 1회)
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if not paths["analysis"].exists():  # 선행 분석 파일이 없으면 진행 불가
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — 먼저 run_analysis_step() 실행"
        )

    analysis_mtime = paths["analysis"].stat().st_mtime  # 분석 파일 수정 시각
    layout_ok = (  # layout 캐시를 재사용할 수 있는 조건
        skip_existing
        and _layout_cache_valid(paths["layout"])  # 유효한 스키마이고
        and paths["layout"].stat().st_mtime >= analysis_mtime  # 분석보다 최신일 때
    )
    if layout_ok:  # 조건 충족 시 캐시 사용
        print(f"[{image_path.name}] layout JSON 캐시 사용 → {paths['layout'].name}")
        return {
            "source": str(image_path),
            "layout_file": str(paths["layout"]),
            "analysis_file": str(paths["analysis"]),
            "analysis_model": analysis_model,
            "skipped": True,
        }

    analysis = paths["analysis"].read_text(encoding="utf-8")  # 저장된 분석 텍스트 로드
    print(f"[{image_path.name}] 상세 layout JSON 생성 중...")
    layout = analyze_layout_detail(client, image_path, analysis, model=analysis_model)  # 좌표 JSON 생성
    paths["layout"].write_text(  # 결과를 JSON으로 저장
        json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[{image_path.name}] layout 저장 → {paths['layout'].name} ({len(layout.get('objects', []))} objects)")
    return {
        "source": str(image_path),
        "layout_file": str(paths["layout"]),
        "analysis_file": str(paths["analysis"]),
        "analysis_model": analysis_model,
        "object_count": len(layout.get("objects", [])),
        "skipped": False,
    }


def run_floorplan_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    image_model: str,
    skip_existing: bool = True,
) -> dict:
    # 2단계: 저장된 분석 + 원본 → 2D 평면도 이미지 (API 1회)
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if not paths["analysis"].exists():  # 선행 분석 파일이 없으면 진행 불가
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — 먼저 run_analysis_step() 실행"
        )

    if skip_existing and paths["plan"].exists():  # 이미 평면도가 있으면 재사용
        print(f"[{image_path.name}] 평면도 캐시 사용 → {paths['plan'].name}")
        return {
            "source": str(image_path),
            "floorplan": str(paths["plan"]),
            "analysis_file": str(paths["analysis"]),
            "image_model": image_model,
            "skipped": True,
        }

    analysis = paths["analysis"].read_text(encoding="utf-8")  # 저장된 분석 텍스트 로드
    print(f"[{image_path.name}] 2D 평면도 생성 중...")
    floorplan = generate_floorplan(client, image_path, analysis, model=image_model)  # 평면도 이미지 생성
    floorplan.save(paths["plan"])  # PNG로 저장

    meta = {  # 처리 결과 메타데이터 구성
        "source": str(image_path),
        "floorplan": str(paths["plan"]),
        "analysis_file": str(paths["analysis"]),
        "image_model": image_model,
    }
    paths["meta"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")  # 메타 저장
    print(f"[{image_path.name}] 평면도 저장 → {paths['plan'].name}")
    return meta  # 메타데이터 반환


def run_svg_floorplan_step(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    skip_existing: bool = True,
) -> dict:
    # 2단계(무료): 저장된 분석 → SVG 평면도 (텍스트 API 1회)
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보
    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음

    if not paths["analysis"].exists():  # 선행 분석 파일이 없으면 진행 불가
        raise FileNotFoundError(
            f"분석 파일 없음: {paths['analysis']} — 먼저 run_analysis_step() 실행"
        )

    if skip_existing and _svg_cache_valid(paths["layout"], paths["plan_svg"]):  # 유효한 SVG 캐시가 있으면
        print(f"[{image_path.name}] SVG 평면도 캐시 사용 → {paths['plan_svg'].name}")
        return {  # 생성 없이 캐시 정보 반환
            "source": str(image_path),
            "floorplan_svg": str(paths["plan_svg"]),
            "layout_file": str(paths["layout"]),
            "analysis_file": str(paths["analysis"]),
            "analysis_model": analysis_model,
            "format": "svg",
            "skipped": True,
        }

    run_layout_detail_step(  # 먼저 상세 좌표 JSON을 확보(없으면 생성)
        client,
        image_path,
        output_dir,
        analysis_model=analysis_model,
        skip_existing=skip_existing,
    )
    layout_json = paths["layout"].read_text(encoding="utf-8")  # 좌표 JSON 로드
    print(f"[{image_path.name}] SVG 평면도 생성 중...")
    svg = generate_floorplan_svg(client, layout_json, image_path, model=analysis_model)  # SVG 생성
    paths["plan_svg"].write_text(svg, encoding="utf-8")  # SVG 파일로 저장

    meta = {  # 처리 결과 메타데이터 구성
        "source": str(image_path),
        "floorplan_svg": str(paths["plan_svg"]),
        "layout_file": str(paths["layout"]),
        "analysis_file": str(paths["analysis"]),
        "analysis_model": analysis_model,
        "format": "svg",
        "skipped": False,
    }
    print(f"[{image_path.name}] SVG 저장 → {paths['plan_svg'].name}")
    return meta


def convert_image(
    client: genai.Client,
    image_path: Path,
    output_dir: Path,
    *,
    analysis_model: str,
    image_model: str,
    skip_existing: bool = False,
) -> dict:
    # 1단계 분석 + 2단계 평면도 (한 번에)
    analysis_meta = run_analysis_step(  # 1단계: 공간 분석
        client,
        image_path,
        output_dir,
        analysis_model=analysis_model,
        skip_existing=skip_existing,
    )
    floorplan_meta = run_floorplan_step(  # 2단계: 평면도 이미지 생성
        client,
        image_path,
        output_dir,
        image_model=image_model,
        skip_existing=skip_existing,
    )
    return {  # 두 단계 결과를 합쳐 반환
        **floorplan_meta,
        "analysis_model": analysis_model,
        "analysis_skipped": analysis_meta.get("skipped", False),  # 분석이 캐시로 스킵됐는지
    }


def plot_floorplan_figure(
    source: Path,
    floorplan_path: Path,
    analysis_path: Path | None = None,
) -> None:
    # 원본 + 2D 평면도 figure (노트북 표시용)
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for font_name in ("Malgun Gothic", "AppleGothic", "NanumGothic"):  # 한글 폰트 후보 순회
        if font_name in {f.name for f in font_manager.fontManager.ttflist}:  # 설치돼 있으면
            plt.rcParams["font.family"] = font_name  # 그 폰트로 지정(한글 깨짐 방지)
            break

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))  # 가로로 2개 패널 생성
    axes[0].imshow(Image.open(source).convert("RGB"))  # 왼쪽: 원본 사진
    axes[0].set_title("원본 (검색 선택)")
    axes[0].axis("off")  # 축 눈금 숨김

    axes[1].imshow(Image.open(floorplan_path).convert("RGB"))  # 오른쪽: 생성된 평면도
    axes[1].set_title("Gemini 2D 평면도")
    axes[1].axis("off")

    if analysis_path and analysis_path.exists():  # 분석 파일이 있으면
        preview = analysis_path.read_text(encoding="utf-8")[:120].replace("\n", " ")  # 앞 120자 미리보기
        fig.suptitle(f"분석 요약: {preview}...", fontsize=10)  # 전체 제목으로 표시

    fig.tight_layout()  # 여백 자동 정리
    plt.show()  # 화면에 출력


def plot_svg_floorplan_figure(
    source: Path,
    svg_path: Path,
    analysis_path: Path | None = None,
    *,
    max_side: int = 520,
) -> None:
    # 원본 사진 + SVG 평면도 (같은 표시 크기, 노트북 HTML)
    import base64  # 이미지를 data URI로 인라인하기 위한 인코딩
    from io import BytesIO  # 메모리 버퍼

    from IPython.display import HTML, display  # 노트북 HTML 출력

    img = Image.open(source).convert("RGB")  # 원본 사진 로드
    iw, ih = img.size  # 원본 가로·세로 크기
    scale = min(1.0, max_side / max(iw, ih))  # 최대 변이 max_side를 넘지 않도록 축소 비율 계산
    display_w, display_h = int(iw * scale), int(ih * scale)  # 표시용 크기

    buf = BytesIO()  # 메모리 버퍼 생성
    img.save(buf, format="PNG")  # 이미지를 PNG로 버퍼에 저장
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")  # base64 문자열로 인코딩(HTML 인라인용)
    svg = svg_path.read_text(encoding="utf-8")  # SVG 텍스트 로드

    panel_style = (
        f"width:{display_w}px;height:{display_h}px;"
        "border:1px solid #ddd;background:#fff;"
        "box-sizing:border-box;overflow:hidden;"
        "display:flex;align-items:center;justify-content:center;"
    )
    img_style = f"width:{display_w}px;height:{display_h}px;object-fit:contain;display:block;"

    title = ""
    if analysis_path and analysis_path.exists():
        preview = analysis_path.read_text(encoding="utf-8")[:120].replace("\n", " ")
        title = f"<p style='font-size:12px;color:#555;margin:0 0 8px 0'>{preview}...</p>"

    html = f"""
    {title}
    <style>
      .fp-pair svg {{ width:100%; height:100%; display:block; }}
    </style>
    <div style="display:flex; gap:16px; align-items:flex-start; flex-wrap:wrap;">
      <div>
        <div style="font-weight:600; margin-bottom:6px;">원본 (검색 선택)</div>
        <div style="{panel_style}">
          <img src="data:image/png;base64,{b64}" style="{img_style}" alt="original" />
        </div>
      </div>
      <div>
        <div style="font-weight:600; margin-bottom:6px;">SVG 2D 평면도 (무료)</div>
        <div class="fp-pair" style="{panel_style}">{svg}</div>
      </div>
    </div>
    """
    display(HTML(html))


def generate_floorplan_for_web(
    image_path: str | Path,
    output_dir: str | Path,
    *,
    analysis_model: str | None = None,
    skip_existing: bool = True,
) -> dict:
    """웹(backend)용 고수준 헬퍼: 사진 한 장 → 평면도 SVG + 방 정보.

    내부에서 layout 추출(Gemini 1회) → 규칙 기반 SVG 렌더(무료)를 수행하고,
    backend가 바로 화면에 쓸 수 있도록 SVG 마크업과 방 정보를 함께 반환한다.

    반환: {
        "svg_path": SVG 파일 경로(str),
        "svg_markup": <svg>...</svg> 문자열(HTML 삽입용),
        "aspect_ratio": 가로÷세로 비율(float 또는 None),
        "object_count": 배치된 가구 수(int),
    }
    """
    _load_env()  # .env 로드(API 키)
    client = _get_client()  # Gemini 클라이언트
    image_path = Path(image_path)
    output_dir = Path(output_dir)
    model = analysis_model or os.getenv("GEMINI_ANALYSIS_MODEL", DEFAULT_ANALYSIS_MODEL)  # 분석 모델 결정

    # 1) 사진 → layout JSON (Gemini 호출, 캐시 있으면 재사용)
    run_rule_based_layout_step(
        client, image_path, output_dir,
        analysis_model=model, skip_existing=skip_existing,
    )
    # 2) layout JSON → SVG 파일 (Gemini 호출 없음)
    svg_meta = run_rule_based_svg_step(
        image_path, output_dir, skip_existing=skip_existing,
    )

    paths = _output_paths(image_path, output_dir)  # 산출물 경로 묶음
    svg_markup = paths["rule_svg"].read_text(encoding="utf-8")  # 생성된 SVG 원문
    layout = json.loads(paths["layout"].read_text(encoding="utf-8"))  # 방 정보 추출용

    return {
        "svg_path": svg_meta["floorplan_svg"],
        "svg_markup": svg_markup,
        "aspect_ratio": (layout.get("room") or {}).get("aspect_ratio"),
        "object_count": len(layout.get("objects", [])),
    }


def maybe_plot(source: Path, floorplan_path: Path) -> None:
    # 원본+평면도 시각화 헬퍼 (CLI --plot 옵션에서 호출)
    plot_floorplan_figure(source, floorplan_path)


def main() -> None:
    # CLI 진입점: 인자 파싱 → 이미지 목록 처리 → 결과 요약 저장
    parser = argparse.ArgumentParser(
        description="인테리어 사진을 Gemini API로 2D 평면도로 변환"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=str(IMAGE_ROOT),
        help=f"이미지 파일 또는 폴더 경로 (기본: {IMAGE_ROOT})",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"결과 저장 폴더 (기본: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--analysis-model",
        default=os.getenv("GEMINI_ANALYSIS_MODEL", DEFAULT_ANALYSIS_MODEL),
        help="공간 분석에 쓸 Gemini 모델",
    )
    parser.add_argument(
        "--image-model",
        default=os.getenv("GEMINI_IMAGE_MODEL", DEFAULT_IMAGE_MODEL),
        help="평면도 이미지 생성에 쓸 Gemini 모델",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="처리할 이미지 개수 제한 (0이면 전체)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="이미 결과가 있으면 건너뛰기",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="마지막 결과를 matplotlib으로 원본/평면도 나란히 표시",
    )
    args = parser.parse_args()  # 커맨드라인 인자 파싱

    _load_env()  # .env 로드
    client = _get_client()  # Gemini 클라이언트 준비

    input_path = Path(args.input)  # 입력 경로(파일 또는 폴더)
    output_dir = Path(args.output)  # 출력 폴더
    output_dir.mkdir(parents=True, exist_ok=True)  # 출력 폴더 확보

    if input_path.is_file():  # 단일 파일이면
        image_paths = [input_path]  # 그 파일 하나만 처리
    else:  # 폴더면
        image_paths = list_images(input_path)  # 폴더 내 이미지 전체 수집

    if args.limit > 0:  # 개수 제한이 있으면
        image_paths = image_paths[: args.limit]  # 앞에서 그만큼만 자르기

    print(f"입력: {input_path}")
    print(f"출력: {output_dir}")
    print(f"분석 모델: {args.analysis_model}")
    print(f"이미지 모델: {args.image_model}")
    print(f"처리 대상: {len(image_paths)}장")

    results: list[dict] = []  # 이미지별 처리 결과 누적
    for image_path in image_paths:  # 이미지 하나씩 처리
        try:
            result = convert_image(  # 분석 + 평면도 생성 한 번에
                client,
                image_path,
                output_dir,
                analysis_model=args.analysis_model,
                image_model=args.image_model,
                skip_existing=args.skip_existing,
            )
            results.append(result)  # 성공 결과 저장
        except Exception as exc:  # 한 장이 실패해도 전체는 계속
            print(f"[{image_path.name}] 오류: {exc}", file=sys.stderr)  # 오류를 stderr로
            results.append({"source": str(image_path), "error": str(exc)})  # 오류 정보 기록

    summary_path = output_dir / "batch_summary.json"  # 전체 요약 파일 경로
    summary_path.write_text(  # 모든 결과를 JSON으로 저장
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n요약 저장: {summary_path}")

    if args.plot:  # --plot 옵션이 있으면
        ok = [r for r in results if "floorplan" in r and not r.get("skipped")]  # 새로 생성된 성공 결과만
        if ok:  # 하나라도 있으면
            last = ok[-1]  # 마지막 것을
            maybe_plot(Path(last["source"]), Path(last["floorplan"]))  # 원본+평면도로 표시
        else:  # 없으면 안내
            print("표시할 성공 결과가 없습니다.", file=sys.stderr)


if __name__ == "__main__":
    main()
