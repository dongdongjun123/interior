# model2: 사진 → 2D 평면도(SVG) 생성 패키지
#
# model1이 추천한(또는 사용자가 올린) 방 사진을 받아 평면도를 만든다.
#   - pipeline.py          : 고수준 단계 조합 + 웹 진입점
#                            (generate_floorplan_for_web)
#   - gemini_steps.py      : Gemini 저수준 호출(공간 분석·layout 추출·교정)
#   - analysis_to_layout.py: 분석 결과 → 렌더러용 layout으로 변환
#   - rule_based_svg.py    : layout JSON → 아이소메트릭 SVG 렌더러
#   - detection_evidence.py: Florence-2 탐지 결과를 Gemini 근거로 변환
#
# 무거운 외부 의존성(google-genai, matplotlib 등)을 패키지 import 시점에
# 강제로 불러오지 않도록, 하위 모듈을 미리 import 하지 않는다.
# 필요한 곳에서 `from model2.rule_based_svg import ...` 처럼 직접 import.
