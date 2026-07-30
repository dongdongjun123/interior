# CLIP zero-shot 라벨링 및 metadata 생성 모듈
from __future__ import annotations  # 타입 힌트 forward reference 지원

import json  # clusters·labels JSON 읽기/쓰기
import re  # slug fallback 정규식
from pathlib import Path  # 이미지 경로·파일명

import matplotlib.pyplot as plt  # 클러스터 몽타주 그리드
import numpy as np  # centroid·유사도 계산
import pandas as pd  # metadata.csv 생성
import torch  # CLIP 추론
from PIL import Image  # 몽타주용 이미지 로드
from transformers import CLIPModel, CLIPProcessor  # CLIP 텍스트·이미지 특징

from .cluster import load_embeddings_and_paths
from .config import (
    CLUSTER_PREVIEW_DIR,
    DATA_DIR,
    IMAGE_ROOT,
    MOOD_CANDIDATES,
    MOOD_KO,
    SLUG_MAP,
)
from .embed import _as_tensor, load_clip


def _slug_from_en(en: str) -> str:
    # SLUG_MAP에 있으면 그대로 (warm_cozy 등)
    if en in SLUG_MAP:
        return SLUG_MAP[en]
    # 없으면 영문 소문자 + 언더스코어로 변환
    return re.sub(r"[^a-z0-9]+", "_", en.lower()).strip("_")[:40]


def classify_cluster_centroids(
    emb: np.ndarray,
    cluster_labels: np.ndarray,
    model: CLIPModel,
    processor: CLIPProcessor,
    device: torch.device,
) -> dict[int, dict]:
    # 12개 무드 후보 문장을 CLIP 텍스트 입력으로 변환
    text_inputs = processor(text=MOOD_CANDIDATES, return_tensors="pt", padding=True)
    text_inputs = {k: v.to(device) for k, v in text_inputs.items()}

    with torch.no_grad():
        text_feat = model.get_text_features(
            input_ids=text_inputs["input_ids"],
            attention_mask=text_inputs["attention_mask"],
        )
        text_feat = _as_tensor(text_feat)
        text_feat = text_feat / text_feat.norm(dim=-1, keepdim=True)  # L2 정규화
    text_feat = text_feat.cpu().numpy()  # (12, 512)

    cluster_scores = {}
    for cid in sorted(set(cluster_labels)):
        mask = cluster_labels == cid              # 이 클러스터에 속한 이미지
        centroid = emb[mask].mean(axis=0)         # 평균 = 클러스터 중심
        centroid = centroid / np.linalg.norm(centroid)  # 정규화
        # centroid와 12개 무드 문장 각각의 유사도 (12,)
        cluster_scores[int(cid)] = centroid @ text_feat.T

    # 1위-2위 점수 차이(margin)가 큰 클러스터부터 라벨 선점
    order = []
    for cid, scores in cluster_scores.items():
        ranked = np.argsort(scores)[::-1]  # 점수 높은 순 인덱스
        if len(ranked) > 1:
            margin = float(scores[ranked[0]] - scores[ranked[1]])
        else:
            margin = float(scores[ranked[0]])
        order.append((cid, margin, ranked))
    order.sort(key=lambda x: -x[1])  # margin 큰 순

    used_labels = set()   # 이미 배정된 무드 문장
    cluster_info = {}

    for cid, _margin, ranked in order:
        best_idx = None
        # 점수 순으로 보면서 아직 안 쓴 무드 찾기
        for idx in ranked:
            if MOOD_CANDIDATES[idx] not in used_labels:
                best_idx = int(idx)
                break
        if best_idx is None:
            best_idx = int(ranked[0])  # 12개보다 클러스터가 많을 때 fallback

        en = MOOD_CANDIDATES[best_idx]
        used_labels.add(en)
        scores = cluster_scores[cid]

        cluster_info[cid] = {
            "mood_en": en,
            "mood_ko": MOOD_KO.get(en, en),
            "mood_id": _slug_from_en(en),
            "confidence": float(scores[best_idx]),
            "top3": [
                {"label": MOOD_CANDIDATES[i], "score": float(scores[i])}
                for i in np.argsort(scores)[-3:][::-1]  # 상위 3개 후보
            ],
        }

    return cluster_info


def find_representatives(
    emb: np.ndarray,
    cluster_labels: np.ndarray,
    rel_paths: list[str],
    top_n: int = 3,
) -> dict[int, list[str]]:
    reps = {}
    for cid in sorted(set(cluster_labels)):
        mask = cluster_labels == cid
        idxs = np.where(mask)[0]           # 이 클러스터 이미지 인덱스
        centroid = emb[mask].mean(axis=0)  # 클러스터 중심
        sims = emb[idxs] @ centroid        # 각 이미지와 centroid 유사도
        top = idxs[np.argsort(sims)[-top_n:][::-1]]  # 유사도 top_n
        reps[int(cid)] = [Path(rel_paths[i]).name for i in top]
    return reps


def make_cluster_montages(
    clusters: dict,
    cluster_info: dict,
    cols: int = 4,
    max_per_cluster: int = 16,
):
    CLUSTER_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    by_cluster = {}
    # 파일명 → cluster_id 매핑을 cluster_id → 경로 리스트로 뒤집기
    for fname, info in clusters.items():
        by_cluster.setdefault(info["cluster_id"], []).append(info["relative_path"])

    saved = []
    for cid, rels in sorted(by_cluster.items()):
        info = cluster_info.get(cid, {})
        title = f"C{cid:02d} {info.get('mood_ko', info.get('mood_id', '?'))} ({len(rels)})"
        sample = rels[:max_per_cluster]  # 최대 16장만 미리보기
        n = len(sample)
        rows = (n + cols - 1) // cols  # 필요한 행 수

        fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.5, rows * 2.5))
        # subplot 1개일 때 axes 형태 맞추기
        if rows == 1 and cols == 1:
            axes = np.array([[axes]])
        elif rows == 1:
            axes = axes.reshape(1, -1)
        elif cols == 1:
            axes = axes.reshape(-1, 1)

        for ax in axes.flat:
            ax.axis("off")  # 빈 칸·축 숨김

        for i, rel in enumerate(sample):
            r, c = divmod(i, cols)  # 그리드 (행, 열)
            img = Image.open(IMAGE_ROOT / rel).convert("RGB")
            axes[r, c].imshow(img)
            axes[r, c].set_title(Path(rel).name[:12], fontsize=7)

        fig.suptitle(title, fontsize=12)
        plt.tight_layout()
        mood_id = info.get("mood_id", f"cluster_{cid:02d}")
        out = CLUSTER_PREVIEW_DIR / f"cluster_{cid:02d}_{mood_id}.png"
        fig.savefig(out, dpi=120)
        plt.close(fig)
        saved.append(str(out.name))

    return saved


def run_labeling() -> dict:
    emb, rel_paths = load_embeddings_and_paths()
    clusters = json.loads((DATA_DIR / "clusters.json").read_text(encoding="utf-8"))
    labels_arr = np.load(DATA_DIR / "cluster_labels.npy")

    model, processor, device = load_clip()
    cluster_info = classify_cluster_centroids(emb, labels_arr, model, processor, device)
    representatives = find_representatives(emb, labels_arr, rel_paths)

    labels_out = {}
    for cid, info in cluster_info.items():
        labels_out[str(cid)] = {
            **info,
            "representatives": representatives.get(cid, []),
            "image_count": int((labels_arr == cid).sum()),
        }

    (DATA_DIR / "labels.json").write_text(
        json.dumps(labels_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows = []
    for fname, cinfo in clusters.items():
        cid = cinfo["cluster_id"]
        li = cluster_info[cid]
        rel = cinfo["relative_path"]
        color_tag = Path(rel).parts[0] if len(Path(rel).parts) > 1 else ""
        rows.append({
            "filename": fname,
            "relative_path": rel,
            "cluster_id": cid,
            "mood_id": li["mood_id"],
            "mood_name_ko": li["mood_ko"],
            "mood_name_en": li["mood_en"],
            "tags": ",".join(li["mood_id"].split("_")[:3]),
            "color_tag": color_tag,
            "is_representative": fname in representatives.get(cid, []),
            "source": "ohou.se",
            "notes": "",
        })

    df = pd.DataFrame(rows)
    df.to_csv(DATA_DIR / "metadata.csv", index=False, encoding="utf-8-sig")

    montages = make_cluster_montages(clusters, cluster_info)

    return {
        "n_clusters": len(cluster_info),
        "montages": montages,
        "metadata_rows": len(df),
    }
