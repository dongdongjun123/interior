# Gemini 저수준 호출: 공간 분석 / 평면도 이미지 / 상세 layout / SVG / rule-based layout·교정
from __future__ import annotations

import json
import os
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image

from .client import _call_gemini_with_retry
from .config import (
    ANALYSIS_PROMPT,
    DEFAULT_THINKING_BUDGET,
    FLOORPLAN_PROMPT,
    LAYOUT_DETAIL_PROMPT,
    LAYOUT_REFINE_PROMPT,
    SVG_FLOORPLAN_PROMPT,
)
from .io_utils import (
    _load_image_part,
    extract_json_from_text,
    extract_svg_from_text,
)


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
    detection_evidence: str | None = None,
) -> dict:
    # 사진 → rule-based 렌더러용 layout JSON을 Gemini로 추출.
    # detection_evidence: Florence 탐지 근거 텍스트(선택). 있으면 프롬프트에 덧붙여
    #   개수·클래스를 사실로 강제하고 top-down 재판단 룰을 지시한다(없으면 기존 동작).
    from mood_pipeline.rule_based_svg import RULE_BASED_LAYOUT_PROMPT, extract_json_from_text  # 전용 프롬프트·파서

    prompt = RULE_BASED_LAYOUT_PROMPT
    if detection_evidence:  # 근거가 있으면 프롬프트 뒤에 근거 블록을 덧붙인다
        prompt = f"{RULE_BASED_LAYOUT_PROMPT}\n{detection_evidence}"

    config = _layout_config(thinking_budget)  # JSON 스키마가 적용된 설정 준비

    def _run():
        response = client.models.generate_content(
            model=model,
            contents=[prompt, _load_image_part(image_path)],  # (근거 포함) 프롬프트 + 사진
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
