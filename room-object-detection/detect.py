# detect.py
"""방 사진에서 가구를 인식해 JSON으로 출력합니다.
사용법: python detect.py samples/room.jpg
"""
import sys, json
import modules.gpu_config  # ⚠️ torch보다 먼저
import torch
from PIL import Image
from modules.detector_florence import (
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
    path = sys.argv[1] if len(sys.argv) > 1 else "samples/room.jpg"
    result = detect(path)
    out = "outputs/detection.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장됨 → {out}")