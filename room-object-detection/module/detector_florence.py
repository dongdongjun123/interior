# module/detector_florence.py
import module.gpu_config
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForCausalLM

# 찾을 가구 목록: (Florence2에 물어볼 영어 단어, 우리 클래스)
TARGETS = [
    ("bed", "bed"),
    ("chair", "chair"),
    ("armchair", "chair"),
    ("nightstand", "nightstand"),
    ("side table", "nightstand"),
    ("floor lamp", "lamp"),
    ("lamp", "lamp"),
    ("potted plant", "plant"),
    ("shelf", "shelf"),
    ("cabinet", "shelf"),
    ("coffee table", "table"),
    ("table", "table"),
    ("picture frame", "picture"),
    ("rug", "rug"),
    ("carpet", "rug"),
]

_model = None
_processor = None

def load_model():
    global _model, _processor
    if _model is None:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        model_id = "microsoft/Florence-2-base"
        _model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=dtype, trust_remote_code=True
        ).to(device)
        _processor = AutoProcessor.from_pretrained(
            model_id, trust_remote_code=True
        )
    return _model, _processor


def _find_one(model, processor, image, phrase, device):
    """Florence2에게 '이 사진에서 <phrase> 어디 있어?'라고 물어 박스들을 받음."""
    prompt = "<CAPTION_TO_PHRASE_GROUNDING>" + phrase
    inputs = processor(text=prompt, images=image, return_tensors="pt").to(device)
    if torch.cuda.is_available():
        inputs["pixel_values"] = inputs["pixel_values"].half()

    generated_ids = model.generate(
        input_ids=inputs["input_ids"],
        pixel_values=inputs["pixel_values"],
        max_new_tokens=1024,
        num_beams=3,
        do_sample=False,
    )
    text = processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
    parsed = processor.post_process_generation(
        text, task="<CAPTION_TO_PHRASE_GROUNDING>", image_size=image.size
    )
    result = parsed.get("<CAPTION_TO_PHRASE_GROUNDING>", {})
    return result.get("bboxes", [])


def _boxes_overlap(a, b, thresh=0.5):
    """두 박스가 많이 겹치는지 (중복 제거용). a,b = (x,y,w,h)"""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return False
    smaller = min(aw * ah, bw * bh)
    return inter / smaller > thresh


def detect_objects(image_path, canvas_size=1000, margin=40):
    """가구 목록을 하나씩 Florence2에 물어 위치를 찾음."""
    model, processor = load_model()
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"[florence] 사용 장치: {device} (가구를 하나씩 찾는 중...)")

    image = Image.open(image_path).convert("RGB")
    img_w, img_h = image.size

    usable = canvas_size - 2 * margin
    scale_x = usable / img_w
    scale_y = usable / img_h

    raw = []
    for phrase, cls in TARGETS:
        bboxes = _find_one(model, processor, image, phrase, device)
        for bbox in bboxes:
            x1, y1, x2, y2 = bbox
            w, h = x2 - x1, y2 - y1
            if w * h > img_w * img_h * 0.9:      # 방 전체만 한 건 거름
                continue
            if w * h < img_w * img_h * 0.002:    # 너무 작은 건 거름
                continue
            raw.append((cls, x1, y1, w, h))

    # 중복 제거: 같은 위치에 여러 이름이 겹치면 하나만
    kept = []
    for item in raw:
        cls, x, y, w, h = item
        if any(_boxes_overlap((x, y, w, h), (kx, ky, kw, kh))
               for _, kx, ky, kw, kh in kept):
            continue
        kept.append(item)

    objects = []
    for cls, x, y, w, h in kept:
        objects.append({
            "class": cls,
            "x": int(margin + x * scale_x),
            "y": int(margin + y * scale_y),
            "width": int(w * scale_x),
            "height": int(h * scale_y),
            "rotation": 0,
        })

    print(f"[florence] 인식된 물건 수: {len(objects)}")
    for o in objects:
        print(f"   - {o['class']}")
    return objects