# 파일·이미지 IO 유틸, 산출물 경로, 캐시 유효성 판정, 텍스트→SVG/JSON 파서
from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path

from google.genai import types

from mood_pipeline.config import IMAGE_EXTENSIONS


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
