# CLIP 임베딩 추출 모듈
from __future__ import annotations  # 타입 힌트 forward reference 지원

import json  # image_paths·manifest JSON 저장
from pathlib import Path  # 이미지 파일 경로

import numpy as np  # 임베딩 벡터 저장 (N, 512)
import torch  # GPU/CPU 추론
from PIL import Image  # 이미지 로드
from tqdm import tqdm  # 배치별 진행률 표시
from transformers import CLIPModel, CLIPProcessor  # OpenAI CLIP 모델·전처리

from .config import BATCH_SIZE, CLIP_MODEL_ID, DATA_DIR, IMAGE_ROOT
from .preprocess import collect_image_paths, deduplicate_by_embedding, filter_valid_images


def get_device() -> torch.device:
    # NVIDIA GPU + CUDA 있으면 cuda, 없으면 cpu
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_clip(device: torch.device | None = None):
    device = device or get_device()  # 디바이스 미지정 시 자동 선택
    # 웹 요청마다 Hugging Face에 접속하면 네트워크가 제한된 환경에서
    # 이미 내려받은 모델이 있어도 검색이 실패할 수 있다. 캐시를 먼저
    # 사용하고, 최초 실행처럼 캐시가 없을 때만 원격 다운로드를 시도한다.
    try:
        model = CLIPModel.from_pretrained(
            CLIP_MODEL_ID,
            local_files_only=True,
        ).to(device)
        processor = CLIPProcessor.from_pretrained(
            CLIP_MODEL_ID,
            local_files_only=True,
        )
    except OSError:
        model = CLIPModel.from_pretrained(CLIP_MODEL_ID).to(device)
        processor = CLIPProcessor.from_pretrained(CLIP_MODEL_ID)
    model.eval()  # dropout 등 끄고 추론 전용 모드
    return model, processor, device


def _as_tensor(feat):
    # 이미 Tensor면 그대로
    if isinstance(feat, torch.Tensor):
        return feat
    # transformers 버전별 출력 객체 → image_embeds 필드
    if hasattr(feat, "image_embeds") and feat.image_embeds is not None:
        return feat.image_embeds
    # 텍스트 임베딩 출력
    if hasattr(feat, "text_embeds") and feat.text_embeds is not None:
        return feat.text_embeds
    # 일부 모델의 pooler_output
    if hasattr(feat, "pooler_output") and feat.pooler_output is not None:
        return feat.pooler_output
    raise TypeError(f"Unexpected feature type: {type(feat)}")


def encode_images(
    paths: list[Path],
    model: CLIPModel,
    processor: CLIPProcessor,
    device: torch.device,
    batch_size: int = BATCH_SIZE,
) -> np.ndarray:
    all_feats = []  # 배치별 임베딩을 모을 리스트

    # 0, 16, 32, ... 배치 단위로 순회
    for i in tqdm(range(0, len(paths), batch_size), desc="CLIP embed"):
        batch_paths = paths[i : i + batch_size]  # 이번 배치 파일
        images = [Image.open(p).convert("RGB") for p in batch_paths]  # PIL 이미지 리스트
        inputs = processor(images=images, return_tensors="pt", padding=True)  # 텐서 변환
        inputs = {k: v.to(device) for k, v in inputs.items()}  # GPU/CPU로 이동

        with torch.no_grad():  # 학습 아님 → gradient 계산 안 함
            feats = model.get_image_features(pixel_values=inputs["pixel_values"])
            feats = _as_tensor(feats)
            # 벡터 길이 1로 맞춤 → 코사인 유사도 = 내적
            feats = feats / feats.norm(dim=-1, keepdim=True)

        all_feats.append(feats.cpu().numpy())  # GPU → numpy

    # (N, 512) 하나의 배열로 합치기
    return np.vstack(all_feats)


def encode_texts(
    texts: list[str],
    model: CLIPModel,
    processor: CLIPProcessor,
    device: torch.device,
) -> np.ndarray:
    # 빈 입력이면 (0, 512) 배열
    if not texts:
        return np.empty((0, 512), dtype=np.float32)

    inputs = processor(text=texts, return_tensors="pt", padding=True, truncation=True)
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        feats = model.get_text_features(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
        )
        feats = _as_tensor(feats)
        feats = feats / feats.norm(dim=-1, keepdim=True)  # L2 정규화 → 코사인 유사도 = 내적

    return feats.cpu().numpy()


def run_embedding(
    deduplicate: bool = True,
    image_root: Path | None = None,
) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    root = image_root or IMAGE_ROOT

    paths = collect_image_paths(root)
    paths, rejected = filter_valid_images(paths)
    if not paths:
        raise FileNotFoundError(f"이미지가 없습니다: {root}")

    model, processor, device = load_clip()
    embeddings = encode_images(paths, model, processor, device)

    removed_dup = []
    # deduplicate=True이고 2장 이상이면 시각적 중복 제거
    if deduplicate and len(paths) > 1:
        paths, embeddings, removed_dup = deduplicate_by_embedding(paths, embeddings)

    records = []
    for p in paths:
        rel = p.relative_to(IMAGE_ROOT)
        records.append({
            "filename": p.name,
            "relative_path": str(rel).replace("\\", "/"),
            "color_tag": rel.parts[0] if len(rel.parts) > 1 else "unknown",
        })

    # (N, 512) float 배열 저장
    np.save(DATA_DIR / "embeddings.npy", embeddings)
    # 임베딩과 1:1 대응하는 경로 목록 (중복 제거 후 갱신)
    (DATA_DIR / "image_paths.json").write_text(
        json.dumps([r["relative_path"] for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = {
        "count": len(records),
        "embedding_dim": int(embeddings.shape[1]),  # 512
        "deduplicated": len(removed_dup),
        "images": records,
    }
    (DATA_DIR / "image_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "count": len(records),
        "shape": embeddings.shape,
        "deduplicated": len(removed_dup),
        "device": str(device),
    }
