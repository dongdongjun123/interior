# 이미지 수집·전처리 모듈
from __future__ import annotations  # 타입 힌트 forward reference 지원

import json  # manifest·경로 목록 JSON 저장
import shutil  # raw 폴더로 이미지 복사
from pathlib import Path  # 파일 경로 처리

import numpy as np  # 임베딩 배열 인덱싱·유사도 계산
from PIL import Image  # 이미지 열기·크기 검증
from tqdm import tqdm  # 진행률 표시 (현재 미사용, 확장용)

from .config import (
    DATA_DIR,
    DEDUP_SIMILARITY,
    IMAGE_EXTENSIONS,
    IMAGE_ROOT,
    MIN_IMAGE_SIZE,
)


def collect_image_paths(image_root: Path | None = None) -> list[Path]:
    # image_root가 없으면 config의 IMAGE_ROOT 사용
    root = image_root or IMAGE_ROOT
    # 하위 폴더까지 재귀 탐색, 허용 확장자만 수집
    paths = sorted(
        p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS and p.is_file()
    )
    # 파일명 기준 정렬된 Path 리스트 반환
    return paths


def validate_image(path: Path) -> tuple[bool, str]:
    try:
        # with로 열어서 파일 핸들 자동 닫기
        with Image.open(path) as img:
            # RGB 3채널로 통일 (RGBA·그레이 등 처리)
            img = img.convert("RGB")
            w, h = img.size  # 가로·세로 픽셀
            # 한 변이라도 MIN_IMAGE_SIZE(200px) 미만이면 제외
            if min(w, h) < MIN_IMAGE_SIZE:
                return False, f"too_small ({w}x{h})"
        # 정상적으로 열리고 크기도 OK
        return True, "ok"
    except Exception as exc:
        # 손상 파일·형식 오류 등
        return False, str(exc)


def filter_valid_images(paths: list[Path]) -> tuple[list[Path], list[dict]]:
    valid = []    # 통과한 이미지 경로
    rejected = []  # 실패한 이미지 기록
    for p in paths:
        ok, reason = validate_image(p)  # 한 장씩 검사
        if ok:
            valid.append(p)
        else:
            # 거부 사유와 함께 저장 (경로는 짧게 표시)
            rejected.append({"path": str(p.relative_to(p.parents[2]) if len(p.parents) > 2 else p.name), "reason": reason})
    return valid, rejected


def deduplicate_by_embedding(
    paths: list[Path],
    embeddings: np.ndarray,
    threshold: float = DEDUP_SIMILARITY,
) -> tuple[list[Path], np.ndarray, list[str]]:
    keep_indices = []  # 남길 이미지 인덱스
    removed = []       # 제거된 파일명

    for i in range(len(paths)):
        # 첫 번째 이미지는 비교 대상 없으므로 무조건 유지
        if not keep_indices:
            keep_indices.append(i)
            continue
        # 현재 이미지 vs 이미 유지하기로 한 이미지들 코사인 유사도
        sims = embeddings[i] @ embeddings[keep_indices].T
        # 가장 비슷한 기존 이미지가 threshold(0.95) 이상이면 중복
        if sims.max() >= threshold:
            removed.append(str(paths[i].name))
        else:
            keep_indices.append(i)

    idx = np.array(keep_indices)
    # 유지 인덱스만 남긴 경로·임베딩·제거 목록 반환
    return [paths[i] for i in idx], embeddings[idx], removed


def prepare_dataset(
    image_root: Path | None = None,
    copy_to_raw: bool = False,
) -> dict:
    # data/ 폴더 없으면 생성
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    all_paths = collect_image_paths(image_root)       # 전체 경로 수집
    valid_paths, rejected = filter_valid_images(all_paths)  # 유효한 것만 필터

    records = []
    for p in valid_paths:
        rel = p.relative_to(IMAGE_ROOT)  # IMAGE_ROOT 기준 상대 경로
        # 하위 폴더가 있으면 첫 폴더명을 color_tag로 (예: black, white)
        color_tag = rel.parts[0] if len(rel.parts) > 1 else "unknown"
        records.append({
            "filename": p.name,
            "relative_path": str(rel).replace("\\", "/"),  # Windows 경로 → 슬래시
            "color_tag": color_tag,
            "source": "ohou.se",
        })

    # 옵션: 원본 복사본을 data/raw/에 저장
    if copy_to_raw:
        raw_dir = DATA_DIR / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        for p in valid_paths:
            dest = raw_dir / p.name
            if not dest.exists():  # 이미 있으면 건너뜀
                shutil.copy2(p, dest)

    # manifest: 전체 요약 + 이미지 목록 + 거부 목록
    manifest = {
        "count": len(records),
        "rejected_count": len(rejected),
        "images": records,
        "rejected": rejected,
    }
    manifest_path = DATA_DIR / "image_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # 임베딩 단계에서 쓸 경로만 따로 저장 (문자열 리스트)
    paths_json = DATA_DIR / "image_paths.json"
    paths_json.write_text(
        json.dumps([r["relative_path"] for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
