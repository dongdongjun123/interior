# Gemini(저토큰) → 인테리어 특징 JSON → 벡터 → UMAP 2D 시각화
from __future__ import annotations

import io
import json
import mimetypes
import os
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

from .config import (
    DATA_DIR,
    GEMINI_EMBEDDINGS_PATH,
    GEMINI_FEATURE_MODEL,
    GEMINI_FEATURES_PATH,
    GEMINI_PATHS_PATH,
    GEMINI_UMAP_PATH,
    IMAGE_EXTENSIONS,
    IMAGE_ROOT,
    PREVIEW_DIR,
    PROJECT_ROOT,
    SLUG_MAP,
)
from .preprocess import collect_image_paths, filter_valid_images

# 무드 slug 후보 (JSON mood_slug 검증용)
MOOD_SLUGS = sorted(set(SLUG_MAP.values()))

# tags → 벡터 차원용 키워드 (고정 vocab, 토큰 절약을 위해 모델 출력 tags만 사용)
TAG_VOCAB = [
    "wood", "white", "warm", "cozy", "minimal", "modern", "vintage",
    "pastel", "grey", "black", "green", "plant", "luxury", "bright",
    "dark", "scandinavian", "industrial", "beige", "monochrome", "cute",
]

# API 호출 간격(초) — rate limit 완화
API_SLEEP_SEC = 0.4

FEATURE_PROMPT = f"""
Look at this interior room photo. Return ONLY compact JSON (no markdown):
{{
  "mood_slug": "<one of: {', '.join(MOOD_SLUGS)}>",
  "tags": ["up to 5 short english keywords"],
  "bright": 1-5,
  "cozy": 1-5,
  "minimal": 1-5
}}
Pick the closest mood_slug. Use integers 1-5 for scores.
""".strip()


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY가 없습니다. .env 파일에 키를 넣어 주세요 (.env.example 참고)"
        )
    return genai.Client(api_key=api_key)


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    ext = path.suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(
        ext, "image/jpeg"
    )


def _resize_for_api(path: Path, max_side: int = 512) -> types.Part:
    # 업로드 토큰 절약: 긴 변 max_side px 로 리사이즈
    img = Image.open(path).convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")


def extract_features(
    client: genai.Client,
    image_path: Path,
    *,
    model: str = GEMINI_FEATURE_MODEL,
    max_side: int = 512,
) -> dict:
    response = client.models.generate_content(
        model=model,
        contents=[FEATURE_PROMPT, _resize_for_api(image_path, max_side=max_side)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=128,
            temperature=0.2,
        ),
    )
    raw = (response.text or "").strip()
    if not raw:
        raise RuntimeError(f"특징 JSON 비어 있음: {image_path.name}")

    data = json.loads(raw)
    slug = str(data.get("mood_slug", "")).strip()
    if slug not in MOOD_SLUGS:
        data["mood_slug"] = "warm_cozy"  # 파싱 실패 시 fallback

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    data["tags"] = [str(t).lower().strip() for t in tags[:5]]

    for key in ("bright", "cozy", "minimal"):
        try:
            data[key] = max(1, min(5, int(data.get(key, 3))))
        except (TypeError, ValueError):
            data[key] = 3

    data["source"] = image_path.name
    return data


def feature_to_vector(feature: dict) -> np.ndarray:
    # mood_slug one-hot + tags multi-hot + 점수 3개 → L2 정규화 벡터
    dim_slug = len(MOOD_SLUGS)
    dim_tags = len(TAG_VOCAB)
    vec = np.zeros(dim_slug + dim_tags + 3, dtype=np.float32)

    slug = feature.get("mood_slug", "")
    if slug in MOOD_SLUGS:
        vec[MOOD_SLUGS.index(slug)] = 1.0

    tag_offset = dim_slug
    for tag in feature.get("tags") or []:
        tag = str(tag).lower()
        for i, vocab in enumerate(TAG_VOCAB):
            if vocab in tag or tag in vocab:
                vec[tag_offset + i] = 1.0

    score_offset = dim_slug + dim_tags
    for i, key in enumerate(("bright", "cozy", "minimal")):
        vec[score_offset + i] = float(feature.get(key, 3)) / 5.0

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def vectorize_features(features: list[dict]) -> np.ndarray:
    if not features:
        return np.empty((0, len(MOOD_SLUGS) + len(TAG_VOCAB) + 3), dtype=np.float32)
    return np.vstack([feature_to_vector(f) for f in features])


def run_gemini_extraction(
    image_root: Path | None = None,
    *,
    limit: int = 0,
    skip_existing: bool = False,
    max_side: int = 512,
    model: str | None = None,
) -> dict:
    _load_env()
    client = _get_client()
    model = model or os.getenv("GEMINI_FEATURE_MODEL", GEMINI_FEATURE_MODEL)

    root = image_root or IMAGE_ROOT
    paths, _ = filter_valid_images(collect_image_paths(root))
    if not paths:
        raise FileNotFoundError(f"이미지 없음: {root}")
    if limit > 0:
        paths = paths[:limit]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict] = {}
    if skip_existing and GEMINI_FEATURES_PATH.exists():
        for rec in json.loads(GEMINI_FEATURES_PATH.read_text(encoding="utf-8")):
            existing[rec.get("source", "")] = rec

    records: list[dict] = []
    rel_paths: list[str] = []

    for i, path in enumerate(paths, 1):
        rel = str(path.relative_to(IMAGE_ROOT)).replace("\\", "/")
        if skip_existing and path.name in existing:
            rec = existing[path.name]
            records.append(rec)
            rel_paths.append(rel)
            print(f"[{i}/{len(paths)}] skip {path.name}")
            continue

        print(f"[{i}/{len(paths)}] extract {path.name} ...")
        try:
            feat = extract_features(client, path, model=model, max_side=max_side)
            feat["relative_path"] = rel
            records.append(feat)
            rel_paths.append(rel)
        except Exception as exc:
            print(f"  오류: {exc}")
            continue

        time.sleep(API_SLEEP_SEC)

    embeddings = vectorize_features(records)
    np.save(GEMINI_EMBEDDINGS_PATH, embeddings)
    GEMINI_FEATURES_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    GEMINI_PATHS_PATH.write_text(
        json.dumps(rel_paths, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "count": len(records),
        "embedding_shape": tuple(embeddings.shape),
        "model": model,
        "features_path": str(GEMINI_FEATURES_PATH),
        "embeddings_path": str(GEMINI_EMBEDDINGS_PATH),
    }


def plot_gemini_umap(
    embeddings: np.ndarray | None = None,
    features: list[dict] | None = None,
    save_path: Path | None = None,
    show: bool = False,
) -> Path:
    # Gemini 특징 벡터 → UMAP 2D scatter
    if embeddings is None:
        embeddings = np.load(GEMINI_EMBEDDINGS_PATH)
    if features is None:
        features = json.loads(GEMINI_FEATURES_PATH.read_text(encoding="utf-8"))

    if len(embeddings) < 2:
        raise ValueError("UMAP에는 최소 2개 샘플이 필요합니다.")

    import umap

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    n_neighbors = min(15, len(embeddings) - 1)
    coords = umap.UMAP(n_components=2, random_state=42, n_neighbors=max(2, n_neighbors)).fit_transform(
        embeddings
    )

    slugs = [f.get("mood_slug", "?") for f in features]
    unique_slugs = sorted(set(slugs))
    slug_to_id = {s: i for i, s in enumerate(unique_slugs)}
    colors = [slug_to_id.get(s, 0) for s in slugs]

    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(coords[:, 0], coords[:, 1], c=colors, cmap="tab20", s=40, alpha=0.75)
    ax.set_title(f"UMAP — Gemini 특징 ({GEMINI_FEATURE_MODEL})")
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")

    for slug, idx in slug_to_id.items():
        mask = np.array([s == slug for s in slugs])
        if mask.any():
            cx, cy = coords[mask].mean(axis=0)
            ax.annotate(slug, (cx, cy), fontsize=8, ha="center", alpha=0.8)

    plt.colorbar(scatter, ax=ax, label="mood_slug")
    plt.tight_layout()

    out = save_path or GEMINI_UMAP_PATH
    fig.savefig(out, dpi=150)
    if show:
        plt.show()
    else:
        plt.close(fig)
    return out
