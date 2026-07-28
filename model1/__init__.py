# model1: 프롬프트 → 무드 사진 추천 패키지
#
# 사용자가 원하는 분위기를 문장으로 입력하면, CLIP 임베딩의 코사인
# 유사도로 무드 라이브러리(images/final)에서 닮은 사진을 골라준다.
#   - search.py          : 프롬프트 → 유사 이미지 top-K (CLIP)
#   - preprocess.py      : 이미지 수집·전처리
#   - gemini_extract.py  : Gemini 특징 추출 + UMAP 2D 시각화(분석용)
#
# 여기서 고른 사진이 model2(사진 → 평면도)의 입력이 된다.
#
# 무거운 외부 의존성(torch, transformers 등)을 패키지 import 시점에
# 강제로 불러오지 않도록, 하위 모듈을 미리 import 하지 않는다.
# 필요한 곳에서 `from model1.search import search_by_prompt` 처럼 직접 import.
