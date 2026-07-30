# Gemini 저토큰 모델로 인테리어 특징 추출 + UMAP 2D 시각화
from __future__ import annotations

import argparse
import json

from mood_pipeline.gemini_extract import (
    plot_gemini_umap,
    run_gemini_extraction,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini 특징 추출 + 2D UMAP")
    parser.add_argument("--limit", type=int, default=0, help="처리 이미지 수 (0=전체)")
    parser.add_argument("--skip-existing", action="store_true", help="이미 추출된 건 건너뛰기")
    parser.add_argument("--max-side", type=int, default=512, help="업로드 전 리사이즈(px)")
    parser.add_argument("--no-plot", action="store_true", help="UMAP PNG 생성 생략")
    parser.add_argument("--show", action="store_true", help="matplotlib 창 표시")
    args = parser.parse_args()

    result = run_gemini_extraction(
        limit=args.limit,
        skip_existing=args.skip_existing,
        max_side=args.max_side,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not args.no_plot and result["count"] >= 2:
        out = plot_gemini_umap(show=args.show)
        print(f"UMAP 저장: {out}")


if __name__ == "__main__":
    main()
