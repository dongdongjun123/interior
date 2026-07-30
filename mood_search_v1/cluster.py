# 클러스터링 및 시각화 모듈
from __future__ import annotations  # 타입 힌트 forward reference 지원

import json  # clusters.json·경로 목록 읽기/쓰기
from collections import Counter  # 클러스터별 이미지 수 집계
from pathlib import Path  # 저장 경로 처리

import matplotlib.pyplot as plt  # UMAP·elbow 차트 그리기
import numpy as np  # 임베딩·라벨 배열
from sklearn.cluster import KMeans  # KMeans 클러스터링
from sklearn.metrics import davies_bouldin_score, silhouette_score  # k 자동 선택 지표

from .config import DATA_DIR, PREVIEW_DIR, default_n_clusters


def load_embeddings_and_paths() -> tuple[np.ndarray, list[str]]:
    emb = np.load(DATA_DIR / "embeddings.npy")  # (N, 512) 배열
    paths = json.loads((DATA_DIR / "image_paths.json").read_text(encoding="utf-8"))
    # 임베딩 행 수와 경로 개수가 같아야 함
    if len(paths) != len(emb):
        raise ValueError(f"경로({len(paths)})와 임베딩({len(emb)}) 개수 불일치")
    return emb, paths


def find_best_k(emb: np.ndarray, k_range: range | None = None) -> dict:
    n = len(emb)  # 이미지 수
    if n < 4:
        # 너무 적으면 k 자동 탐색 생략
        return {"best_k": max(2, n), "scores": {}}

    if k_range is None:
        lo = max(4, min(8, n // 20))           # k 하한
        hi = min(15, max(lo + 1, n // 10))     # k 상한
        k_range = range(lo, hi + 1)

    scores = {}  # k별 품질 점수
    for k in k_range:
        if k >= n:  # 클러스터 수가 샘플 수 이상이면 skip
            continue
        labels = KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(emb)
        if len(set(labels)) < 2:  # 클러스터가 1개뿐이면 skip
            continue
        sil = silhouette_score(emb, labels)       # 높을수록 잘 갈라짐
        db = davies_bouldin_score(emb, labels)    # 낮을수록 좋음 (참고용)
        scores[k] = {"silhouette": float(sil), "davies_bouldin": float(db)}

    if not scores:
        return {"best_k": default_n_clusters(n), "scores": {}}

    # silhouette 최대인 k 선택
    best_k = max(scores, key=lambda k: scores[k]["silhouette"])
    return {"best_k": best_k, "scores": scores}


def run_clustering(n_clusters: int | None = None) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    emb, rel_paths = load_embeddings_and_paths()
    n = len(emb)

    if n_clusters is None:
        suggestion = find_best_k(emb)  # k 자동 선택
        n_clusters = suggestion["best_k"]
    else:
        suggestion = {"best_k": n_clusters, "scores": {}}

    n_clusters = min(n_clusters, n)  # k는 샘플 수를 넘을 수 없음
    labels = KMeans(n_clusters=n_clusters, random_state=42, n_init=10).fit_predict(emb)

    sizes = Counter(labels)  # 클러스터 ID → 이미지 수
    clusters = {}
    for rel, cid in zip(rel_paths, labels):
        fname = Path(rel).name  # 파일명만 키로 사용
        clusters[fname] = {
            "cluster_id": int(cid),
            "cluster_size": int(sizes[cid]),
            "relative_path": rel,
        }

    (DATA_DIR / "clusters.json").write_text(
        json.dumps(clusters, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    np.save(DATA_DIR / "cluster_labels.npy", labels)  # (N,) 정수 배열

    result = {
        "n_clusters": n_clusters,
        "n_images": n,
        "cluster_sizes": {str(k): v for k, v in sorted(sizes.items())},
        "k_suggestion": suggestion,
    }
    (DATA_DIR / "cluster_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def plot_umap(emb: np.ndarray, labels: np.ndarray, save_path: Path | None = None):
    import umap  # 고차원 임베딩 → 2D 축소

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    reducer = umap.UMAP(n_components=2, random_state=42, n_neighbors=min(15, len(emb) - 1))
    coords = reducer.fit_transform(emb)  # (N, 2) 2D 좌표

    fig, ax = plt.subplots(figsize=(10, 8))
    # x, y 좌표에 클러스터 ID로 색칠
    scatter = ax.scatter(coords[:, 0], coords[:, 1], c=labels, cmap="tab20", s=20, alpha=0.7)
    ax.set_title("UMAP — CLIP clusters")
    plt.colorbar(scatter, ax=ax, label="cluster")
    plt.tight_layout()

    out = save_path or PREVIEW_DIR / "umap_clusters.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_elbow(emb: np.ndarray, save_path: Path | None = None):
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    n = len(emb)
    # 시도할 k 범위 (이미지 수에 따라 조절)
    ks = range(max(2, min(4, n // 25)), min(16, max(5, n // 8)))
    inertias = []
    for k in ks:
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(emb)
        inertias.append(km.inertia_)  # 클러스터 내 거리 제곱합

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(list(ks), inertias, "o-")
    ax.set_xlabel("k")
    ax.set_ylabel("inertia")
    ax.set_title("KMeans elbow")
    plt.tight_layout()
    out = save_path or PREVIEW_DIR / "elbow.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out
