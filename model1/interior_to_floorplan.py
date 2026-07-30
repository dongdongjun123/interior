# 인테리어 사진 → Gemini API → 2D 평면도 변환
#
# 이 파일은 하위 호환용 재-export 레이어다. 실제 구현은 아래 모듈로 분리됨:
#   - config.py       : 상수·.env 로드·프롬프트 로드
#   - client.py       : Gemini 클라이언트 생성·API 재시도
#   - io_utils.py     : 파일/이미지 IO·산출물 경로·캐시 판정·텍스트 파서
#   - gemini_steps.py : Gemini 저수준 호출(분석/평면도/layout/SVG/교정)
#   - pipeline.py     : 고수준 단계(run_*_step)·convert_image·웹 진입점
#   - render.py       : 노트북 시각화
#   - cli.py          : CLI main()
#
# 기존 `from model1 import interior_to_floorplan` 코드가 그대로 동작하도록
# 공개 이름을 모두 여기서 다시 노출한다.
from __future__ import annotations

from .cli import main
from .client import (
    _call_gemini_with_retry,
    _get_client,
    _is_retryable_gemini_error,
    _retry_seconds_from_error,
)
from .config import (
    ANALYSIS_PROMPT,
    DEFAULT_ANALYSIS_MODEL,
    DEFAULT_IMAGE_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_THINKING_BUDGET,
    FLOORPLAN_PROMPT,
    LAYOUT_DETAIL_PROMPT,
    LAYOUT_REFINE_PROMPT,
    MAX_API_RETRIES,
    PROMPTS_DIR,
    SVG_FLOORPLAN_PROMPT,
    _load_env,
    load_prompt,
)
from .gemini_steps import (
    _build_layout_schema,
    _layout_config,
    analyze_interior,
    analyze_layout_detail,
    extract_rule_based_layout,
    generate_floorplan,
    generate_floorplan_svg,
    refine_layout,
)
from .io_utils import (
    _analysis_cache_valid,
    _guess_mime,
    _layout_cache_valid,
    _load_image_part,
    _output_paths,
    _rule_layout_cache_valid,
    _rule_layout_needs_coerce,
    _rule_svg_cache_valid,
    _svg_cache_valid,
    extract_json_from_text,
    extract_svg_from_text,
    list_images,
)
from .pipeline import (
    convert_image,
    generate_floorplan_for_web,
    run_analysis_step,
    run_floorplan_step,
    run_layout_detail_step,
    run_rule_based_layout_step,
    run_rule_based_svg_step,
    run_svg_floorplan_step,
)
from .render import (
    maybe_plot,
    plot_floorplan_figure,
    plot_svg_floorplan_figure,
)

if __name__ == "__main__":
    main()
