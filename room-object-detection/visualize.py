# visualize_detection.py  (인식 결과를 원본 사진에 그려서 확인)
import module.gpu_config
import torch
from PIL import Image, ImageDraw, ImageFont

from module.detector_florence import (
    TARGETS, load_model, _find_one, _boxes_overlap
)

IMAGE_PATH = "samples/room.jpg"
OUT_PATH = "outputs/detected.jpg"

def main():
    model, processor = load_model()
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    image = Image.open(IMAGE_PATH).convert("RGB")
    img_w, img_h = image.size
    print(f"사진 크기: {img_w} x {img_h}")

    raw = []      # 전부
    for phrase, cls in TARGETS:
        bboxes = _find_one(model, processor, image, phrase, device)
        print(f"  '{phrase}' → {len(bboxes)}개 발견")
        for bbox in bboxes:
            x1, y1, x2, y2 = bbox
            w, h = x2 - x1, y2 - y1
            area_ratio = (w * h) / (img_w * img_h)
            reason = None
            if area_ratio > 0.9:
                reason = "너무 큼"
            elif area_ratio < 0.002:
                reason = "너무 작음"
            raw.append({
                "cls": cls, "phrase": phrase,
                "box": (x1, y1, w, h),
                "filtered": reason,
            })

    # 중복 제거 (실제 detector와 같은 로직)
    kept = []
    for item in raw:
        if item["filtered"]:
            continue
        x, y, w, h = item["box"]
        if any(_boxes_overlap((x, y, w, h), k["box"]) for k in kept):
            item["filtered"] = "중복"
            continue
        kept.append(item)

    # 그리기
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", max(16, img_w // 45))
    except Exception:
        font = ImageFont.load_default()

    # 걸러진 것: 회색 얇은 선
    for item in raw:
        if not item["filtered"]:
            continue
        x, y, w, h = item["box"]
        draw.rectangle([x, y, x + w, y + h], outline=(160, 160, 160), width=2)
        draw.text((x + 4, y + 4), f"{item['phrase']} ({item['filtered']})",
                  fill=(160, 160, 160), font=font)

    # 채택된 것: 빨간 굵은 선
    for item in kept:
        x, y, w, h = item["box"]
        draw.rectangle([x, y, x + w, y + h], outline=(255, 40, 40), width=5)
        label = f"{item['cls']}"
        draw.rectangle([x, y - 30, x + len(label) * 16 + 10, y],
                       fill=(255, 40, 40))
        draw.text((x + 5, y - 28), label, fill=(255, 255, 255), font=font)

    image.save(OUT_PATH)
    print(f"\n전체 발견: {len(raw)}개 / 최종 채택: {len(kept)}개")
    print("채택된 것:", [k["cls"] for k in kept])
    print(f"저장됨 → {OUT_PATH}")

if __name__ == "__main__":
    main()