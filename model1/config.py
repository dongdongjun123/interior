# model1 설정: 상수·.env 로드·프롬프트 로드
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from mood_pipeline.config import PROJECT_ROOT

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

# 프롬프트는 코드에 하드코딩하지 않고 프로젝트 루트 prompts/*.txt에서 읽어온다.
# (mood_pipeline과 동일한 위치를 공유 — rule_based_svg.py 참고)
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def load_prompt(name: str) -> str:
    """prompts/<name>.txt 파일을 읽어 프롬프트 문자열로 반환 (앞뒤 공백 제거)."""
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


# 각 단계 프롬프트를 파일에서 로드 (플레이스홀더는 {analysis}/{layout_json} 형태, replace로 치환)
ANALYSIS_PROMPT = load_prompt("analysis")
FLOORPLAN_PROMPT = load_prompt("floorplan")
LAYOUT_DETAIL_PROMPT = load_prompt("layout_detail")
SVG_FLOORPLAN_PROMPT = load_prompt("svg_floorplan")
LAYOUT_REFINE_PROMPT = load_prompt("layout_refine")


def _load_env() -> None:
    # 루트 .env에서 환경변수(API 키 등) 로드
    load_dotenv(PROJECT_ROOT / ".env")
