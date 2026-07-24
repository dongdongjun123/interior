# detect.py
"""방 사진에서 가구를 인식해 JSON으로 출력합니다.
사용법:
  python detect.py samples/room.jpg                 # 기본: outputs/detection.json 에 저장
  python detect.py 사진.jpg --out 경로/결과.json     # 출력 경로 지정 (오케스트레이터용)
"""
import argparse, json
from pathlib import Path
import module.gpu_config  # ⚠️ torch보다 먼저
import torch
from PIL import Image
from module.detector_florence import (
    TARGETS, load_model, _find_one, _boxes_overlap
)


def detect(image_path):
    model, processor = load_model()
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    image = Image.open(image_path).convert("RGB")
    W, H = image.size

    raw = []
    for phrase, cls in TARGETS:
        for bbox in _find_one(model, processor, image, phrase, device):
            x1, y1, x2, y2 = bbox
            w, h = x2 - x1, y2 - y1
            ratio = (w * h) / (W * H)
            if ratio > 0.9 or ratio < 0.002:   # 화면 전체 / 너무 작은 것 제외
                continue
            raw.append({"cls": cls, "phrase": phrase,
                        "box": (x1, y1, w, h), "area": ratio})

    # 중복 제거 (큰 것부터 남김)
    raw.sort(key=lambda r: -r["area"])
    kept = []
    for item in raw:
        if any(_boxes_overlap(item["box"], k["box"]) for k in kept):
            continue
        kept.append(item)

    objects = []
    for i, it in enumerate(kept):
        x, y, w, h = it["box"]
        objects.append({
            "id": i,
            "class": it["cls"],
            "matched_phrase": it["phrase"],
            "bbox_pixel": {"x": round(x), "y": round(y),
                           "w": round(w), "h": round(h)},
            "bbox_norm": {"x": round(x / W, 4), "y": round(y / H, 4),
                          "w": round(w / W, 4), "h": round(h / H, 4)},
            "floor_contact": {"x": round((x + w / 2) / W, 4),
                              "y": round((y + h) / H, 4)},
        })

    return {
        "image": image_path,
        "image_size": {"width": W, "height": H},
        "object_count": len(objects),
        "objects": objects,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="방 사진 → 가구 탐지 JSON (Florence-2)")
    parser.add_argument("image", nargs="?", default="samples/room.jpg",
                        help="입력 사진 경로 (기본: samples/room.jpg)")
    parser.add_argument("--out", default="outputs/detection.json",
                        help="출력 JSON 경로 (기본: outputs/detection.json)")
    parser.add_argument("--quiet", action="store_true",
                        help="JSON 본문 표준출력 생략 (파일만 저장)")
    args = parser.parse_args()

    result = detect(args.image)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)  # 출력 폴더 없으면 생성
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장됨 → {out_path}")