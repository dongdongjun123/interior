# 인테리어 사진 → 2D 평면도(SVG/PNG) 변환 파이프라인 패키지
#
# 검색(CLIP) 계열 모듈은 별도 레포(mood-search)로 분리되었습니다.
# 이 레포는 Gemini 공간 분석 + 규칙 기반 SVG 렌더링만 담당합니다.
#
# 무거운 외부 의존성(google-genai, matplotlib 등)을 패키지 import 시점에
# 강제로 불러오지 않도록, 여기서는 하위 모듈을 미리 import 하지 않습니다.
# 필요한 곳에서 `from mood_pipeline.rule_based_svg import ...` 처럼 직접 import 하세요.
