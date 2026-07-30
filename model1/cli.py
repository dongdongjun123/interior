# CLI 진입점: 인테리어 사진(들)을 배치 처리해 2D 평면도 생성
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from mood_pipeline.config import IMAGE_ROOT

from .client import _get_client
from .config import (
    DEFAULT_ANALYSIS_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_OUTPUT_DIR,
    _load_env,
)
from .io_utils import list_images
from .pipeline import convert_image
from .render import maybe_plot


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
