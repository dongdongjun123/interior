# 프롬프트 → 유사 이미지 검색 (CLIP 기반)
#
# 사용 흐름
#   1) build_image_index()  : images/final 전체를 CLIP으로 임베딩해 캐시 (오프라인 1회)
#   2) search_by_prompt(text): 프롬프트(한/영)를 CLIP 텍스트 임베딩으로 바꿔
#                              캐시된 이미지들과 코사인 유사도 top-K 반환 (런타임)
from __future__ import annotations

import json
import re

import numpy as np

from .config import (
    BATCH_SIZE,
    CLIP_IMAGE_EMBEDDINGS_PATH,
    CLIP_IMAGE_PATHS_PATH,
    CLIP_MODEL_ID,
    DATA_DIR,
    IMAGE_ROOT,
    PROMPT_TRANSLATION_CACHE_PATH,
)
from .preprocess import collect_image_paths

# CLIP 모델·프로세서는 무거우므로 최초 1회만 로드해 캐싱
_CLIP_MODEL = None
_CLIP_PROCESSOR = None


def _get_clip():
    # CLIP 모델·프로세서를 지연 로딩 (첫 호출 시 다운로드/로드, 이후 캐시 재사용)
    global _CLIP_MODEL, _CLIP_PROCESSOR
    if _CLIP_MODEL is None:
        import torch  # noqa: F401  (transformers가 내부적으로 사용)
        from transformers import CLIPModel, CLIPProcessor

        _CLIP_MODEL = CLIPModel.from_pretrained(CLIP_MODEL_ID)
        _CLIP_MODEL.eval()  # 추론 모드
        _CLIP_PROCESSOR = CLIPProcessor.from_pretrained(CLIP_MODEL_ID)
    return _CLIP_MODEL, _CLIP_PROCESSOR


def _to_numpy(feats) -> np.ndarray:
    # CLIP get_*_features 반환을 numpy 2D 배열로 정규화.
    # transformers 버전에 따라 텐서 또는 output 객체(pooler_output)를 반환하므로 모두 대응.
    if hasattr(feats, "cpu"):  # 텐서인 경우
        return feats.cpu().numpy()
    if hasattr(feats, "pooler_output"):  # output 객체(transformers 5.x)
        return feats.pooler_output.cpu().numpy()
    raise TypeError(f"예상치 못한 CLIP feature 타입: {type(feats)}")


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    # 코사인 유사도를 내적으로 계산하기 위해 각 행을 단위 벡터로 정규화
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # 0 division 방지
    return mat / norms


# ── 한글 → 영어 번역 (CLIP은 영어 모델이라 한글 프롬프트를 번역) ────────────
def _load_translation_cache() -> dict:
    # 이전에 번역한 결과 캐시 로드 (없으면 빈 dict)
    if PROMPT_TRANSLATION_CACHE_PATH.exists():
        try:
            return json.loads(PROMPT_TRANSLATION_CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_translation_cache(cache: dict) -> None:
    # 번역 캐시를 파일로 저장
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROMPT_TRANSLATION_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _has_korean(text: str) -> bool:
    # 문자열에 한글이 하나라도 있는지 검사
    return bool(re.search(r"[가-힣]", text))


def translate_to_english(text: str) -> str:
    # 한글이 포함된 프롬프트를 영어로 번역 (영어면 그대로 반환)
    text = text.strip()
    if not text or not _has_korean(text):
        return text  # 번역 불필요
    cache = _load_translation_cache()
    if text in cache:
        return cache[text]  # 캐시 히트
    try:
        from deep_translator import GoogleTranslator

        translated = GoogleTranslator(source="ko", target="en").translate(text)
    except Exception as exc:
        # 번역 실패(네트워크 등) 시 원문 그대로 사용 (검색은 계속 진행)
        print(f"[search] 번역 실패, 원문 사용: {exc}")
        return text
    cache[text] = translated
    _save_translation_cache(cache)
    return translated


# ── 이미지 인덱스 빌드 (오프라인 1회) ──────────────────────────────────────
def build_image_index(force: bool = False) -> dict:
    # images/final 전체를 CLIP 이미지 임베딩으로 변환해 캐시 저장
    if (
        not force
        and CLIP_IMAGE_EMBEDDINGS_PATH.exists()
        and CLIP_IMAGE_PATHS_PATH.exists()
    ):
        # 이미 인덱스가 있으면 재사용 (force=True면 재빌드)
        paths = json.loads(CLIP_IMAGE_PATHS_PATH.read_text(encoding="utf-8"))
        return {"count": len(paths), "skipped": True}

    import torch
    from PIL import Image

    model, processor = _get_clip()
    image_paths = collect_image_paths(IMAGE_ROOT)  # 검색 대상 이미지 전체
    if not image_paths:
        raise FileNotFoundError(f"검색 대상 이미지가 없습니다: {IMAGE_ROOT}")

    all_embeddings: list[np.ndarray] = []
    kept_paths: list[str] = []

    # 배치 단위로 임베딩 (메모리 절약)
    for start in range(0, len(image_paths), BATCH_SIZE):
        batch_paths = image_paths[start : start + BATCH_SIZE]
        images = []
        valid_paths = []
        for p in batch_paths:
            try:
                images.append(Image.open(p).convert("RGB"))  # 손상 이미지 방어
                valid_paths.append(p)
            except Exception as exc:
                print(f"[search] 이미지 로드 실패 건너뜀: {p.name} ({exc})")
        if not images:
            continue
        inputs = processor(images=images, return_tensors="pt")
        with torch.no_grad():
            feats = model.get_image_features(**inputs)  # CLIP 이미지 임베딩
        all_embeddings.append(_to_numpy(feats))
        # 저장 경로는 IMAGE_ROOT 기준 상대경로 (이식성)
        kept_paths.extend(str(p.relative_to(IMAGE_ROOT)) for p in valid_paths)
        print(f"[search] 임베딩 {len(kept_paths)}/{len(image_paths)} …")

    embeddings = _l2_normalize(np.vstack(all_embeddings).astype("float32"))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.save(CLIP_IMAGE_EMBEDDINGS_PATH, embeddings)  # 임베딩 캐시
    CLIP_IMAGE_PATHS_PATH.write_text(
        json.dumps(kept_paths, ensure_ascii=False), encoding="utf-8"
    )
    return {"count": len(kept_paths), "skipped": False}


# ── 런타임 검색 ────────────────────────────────────────────────────────────
# 인덱스는 프로세스 내에서 한 번만 메모리에 로드
_INDEX_EMB = None
_INDEX_PATHS = None


def _load_index():
    # 캐시된 이미지 임베딩·경로를 메모리로 로드 (최초 1회)
    global _INDEX_EMB, _INDEX_PATHS
    if _INDEX_EMB is None:
        if not CLIP_IMAGE_EMBEDDINGS_PATH.exists():
            raise FileNotFoundError(
                "이미지 인덱스가 없습니다. 먼저 build_image_index()를 실행하세요."
            )
        _INDEX_EMB = np.load(CLIP_IMAGE_EMBEDDINGS_PATH)
        _INDEX_PATHS = json.loads(CLIP_IMAGE_PATHS_PATH.read_text(encoding="utf-8"))
    return _INDEX_EMB, _INDEX_PATHS


def _embed_text(text: str) -> np.ndarray:
    # 프롬프트 텍스트를 CLIP 텍스트 임베딩(단위 벡터)으로 변환
    import torch

    model, processor = _get_clip()
    inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        feats = model.get_text_features(**inputs)
    return _l2_normalize(_to_numpy(feats).astype("float32"))[0]


def search_by_prompt(prompt: str, top_k: int = 3) -> list[dict]:
    """프롬프트 → 유사 이미지 top-K.

    반환: [{"path": IMAGE_ROOT 기준 상대경로, "score": 유사도 float}, ...]
    """
    emb, paths = _load_index()
    query_en = translate_to_english(prompt)  # 한글이면 영어로 번역
    if not query_en.strip():
        return []
    q = _embed_text(query_en)  # 텍스트 임베딩
    scores = emb @ q  # 코사인 유사도(정규화돼 있어 내적=코사인)
    top_idx = np.argsort(-scores)[:top_k]  # 점수 내림차순 top-K
    return [
        {"path": paths[i], "score": float(scores[i])}
        for i in top_idx
    ]


if __name__ == "__main__":
    # CLI: 인덱스 빌드 후 샘플 검색
    import sys

    print("이미지 인덱스 빌드 중…")
    info = build_image_index(force="--force" in sys.argv)
    print(f"인덱스: {info}")
    query = "cozy warm room with plants"
    print(f"\n샘플 검색: {query!r}")
    for r in search_by_prompt(query, top_k=5):
        print(f"  {r['score']:.3f}  {r['path']}")
