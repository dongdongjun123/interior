# 무드 라이브러리 파이프라인 공통 설정
from pathlib import Path  # 파일·폴더 경로 처리

# 프로젝트 루트 (mood_pipeline/ 의 상위 폴더)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 클러스터링 대상 원본 이미지 폴더
IMAGE_ROOT = PROJECT_ROOT / "images" / "final"
# 임베딩·클러스터·메타데이터 저장 폴더
DATA_DIR = PROJECT_ROOT / "data"
# 최종 무드 라이브러리 출력 폴더
MOOD_LIBRARY_DIR = PROJECT_ROOT / "mood_library"
# UMAP·elbow 등 시각화 저장 폴더
PREVIEW_DIR = DATA_DIR / "previews"
# 클러스터별 몽타주 미리보기 저장 폴더
CLUSTER_PREVIEW_DIR = DATA_DIR / "cluster_previews"

# 프롬프트 무드 검색용 CLIP 텍스트·대표 이미지 임베딩 캐시
MOOD_TEXT_EMBEDDINGS_PATH = MOOD_LIBRARY_DIR / "mood_text_embeddings.npy"
MOOD_IDS_PATH = MOOD_LIBRARY_DIR / "mood_ids.json"
MOOD_REP_IMAGE_EMBEDDINGS_PATH = MOOD_LIBRARY_DIR / "mood_rep_image_embeddings.npy"
MOOD_REP_IMAGES_PATH = MOOD_LIBRARY_DIR / "mood_rep_images.json"
# gallery 전체 검색 인덱스 버전 (올리면 자동 재빌드)
MOOD_SEARCH_INDEX_VERSION_PATH = MOOD_LIBRARY_DIR / "search_index_version.txt"
SEARCH_INDEX_VERSION = 2

# Gemini API 특징 추출 산출물
GEMINI_FEATURE_MODEL = "gemini-2.5-flash-lite"
GEMINI_FEATURES_PATH = DATA_DIR / "gemini_features.json"
GEMINI_EMBEDDINGS_PATH = DATA_DIR / "gemini_embeddings.npy"
GEMINI_PATHS_PATH = DATA_DIR / "gemini_image_paths.json"
GEMINI_UMAP_PATH = PREVIEW_DIR / "umap_gemini.png"

# Hugging Face CLIP 모델 ID
CLIP_MODEL_ID = "openai/clip-vit-base-patch32"
# 허용 이미지 확장자
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
# 최소 이미지 한 변 길이 (px)
MIN_IMAGE_SIZE = 200
# 코사인 유사도가 이 값 이상이면 중복으로 간주
DEDUP_SIMILARITY = 0.95
# CLIP 배치 추론 크기
BATCH_SIZE = 16


def default_n_clusters(n_images: int) -> int:
    # 이미지 15장당 클러스터 1개, 최소 4·최대 15
    per_cluster = n_images // 15 or 4
    return max(4, min(15, per_cluster))


# CLIP zero-shot 분류용 영문 무드 후보 문장
MOOD_CANDIDATES = [
    "warm cozy studio apartment interior",
    "minimal white scandinavian room",
    "modern grey industrial studio",
    "natural wood tone small room",
    "soft beige feminine bedroom",
    "dark moody compact apartment",
    "bright airy open studio",
    "vintage retro small room",
    "monochrome minimalist interior",
    "plant-filled green interior",
    "luxury modern studio apartment",
    "cute pastel room decor",
]

# 영문 무드 → 한글 표시명 매핑
MOOD_KO = {
    "warm cozy studio apartment interior": "따뜻한 코지 원룸",
    "minimal white scandinavian room": "미니멀 화이트",
    "modern grey industrial studio": "모던 그레이",
    "natural wood tone small room": "내추럴 우드",
    "soft beige feminine bedroom": "소프트 베이지",
    "dark moody compact apartment": "다크 무디",
    "bright airy open studio": "밝은 에어리",
    "vintage retro small room": "빈티지 레트로",
    "monochrome minimalist interior": "모노톤 미니멀",
    "plant-filled green interior": "플랜트 그린",
    "luxury modern studio apartment": "럭셔리 모던",
    "cute pastel room decor": "파스텔 귀여운",
}

# 영문 무드 → 폴더명용 slug 매핑
SLUG_MAP = {
    "warm cozy studio apartment interior": "warm_cozy",
    "minimal white scandinavian room": "minimal_white",
    "modern grey industrial studio": "modern_grey",
    "natural wood tone small room": "natural_wood",
    "soft beige feminine bedroom": "soft_beige",
    "dark moody compact apartment": "dark_moody",
    "bright airy open studio": "bright_airy",
    "vintage retro small room": "vintage_retro",
    "monochrome minimalist interior": "monochrome_minimal",
    "plant-filled green interior": "plant_green",
    "luxury modern studio apartment": "luxury_modern",
    "cute pastel room decor": "cute_pastel",
}
