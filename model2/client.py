# Gemini 클라이언트 생성 및 API 재시도(429/503) 로직
from __future__ import annotations

import os
import re
import time

from google import genai
from google.genai.errors import ClientError, ServerError

from .config import MAX_API_RETRIES


def _get_client() -> genai.Client:
    # API 키를 확인하고 Gemini 클라이언트 생성
    api_key = os.getenv("GEMINI_API_KEY", "").strip()  # 환경변수에서 키 읽기(공백 제거)
    if not api_key:  # 키가 비어 있으면 실행 불가 → 안내 메시지와 함께 중단
        raise RuntimeError(
            "GEMINI_API_KEY가 없습니다. 프로젝트 루트의 .env 파일에 API 키를 넣어 주세요."
        )
    return genai.Client(api_key=api_key)  # 키로 인증된 클라이언트 반환


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
