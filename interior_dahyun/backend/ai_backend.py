# ai_backend.py
#
# 이 모듈은 아키텍처 다이어그램의 "AI Backend / Image Model (SDXL 등)" 자리를 대신하는
# Mock 구현체입니다. 실제 서비스에서는 이 안의 함수 내용만
# 진짜 이미지 생성 모델 API 호출로 교체하면 됩니다.
#
#   real_generate_interior(image_path, prompt, tags) -> generated_image_path
#
# 아래 mock 버전은 업로드된 사진을 PIL로 색감/밝기 보정해서
# "AI가 생성한 것 같은" 결과 이미지를 실제로 만들어 반환합니다.
# (파이프라인 전체가 실제로 동작하는 걸 보여주기 위함)

import os
import uuid
from PIL import Image, ImageEnhance, ImageFilter

STYLE_PRESETS = {
    "cozy": {"warmth": 1.25, "brightness": 1.08, "contrast": 1.05},
    "warm": {"warmth": 1.3, "brightness": 1.1, "contrast": 1.0},
    "vintage": {"warmth": 1.15, "brightness": 0.95, "contrast": 0.9},
    "loft": {"warmth": 1.0, "brightness": 1.0, "contrast": 1.15},
    "wood": {"warmth": 1.2, "brightness": 1.05, "contrast": 1.05},
    "plants": {"warmth": 1.1, "brightness": 1.05, "contrast": 1.05},
}

DEFAULT_PRESET = {"warmth": 1.15, "brightness": 1.05, "contrast": 1.05}


def _matching_preset(tags: list[str]) -> dict:
    for tag in tags:
        key = tag.strip().lower()
        if key in STYLE_PRESETS:
            return STYLE_PRESETS[key]
    return DEFAULT_PRESET


def _apply_warmth(img: Image.Image, factor: float) -> Image.Image:
    """색 온도를 살짝 따뜻하게 (R 채널 업, B 채널 다운)"""
    r, g, b = img.convert("RGB").split()
    r = r.point(lambda p: min(255, int(p * factor)))
    b = b.point(lambda p: max(0, int(p / factor)))
    return Image.merge("RGB", (r, g, b))


def generate_interior_image(upload_path: str, output_dir: str, prompt_text: str, tags: list[str]) -> str:
    """
    업로드된 방 사진을 받아 스타일 톤을 적용한 '결과 이미지'를 생성한다.
    반환값: 생성된 이미지의 파일명 (static/generated/ 기준)

    ⚠️ Mock 구현: 실제 인테리어 재배치가 아니라 색감/톤 보정만 수행합니다.
    실제 서비스에서는 이 함수 내부를 SDXL/ControlNet 등 이미지 생성 API 호출로 교체하세요.
    """
    preset = _matching_preset(tags)

    with Image.open(upload_path) as img:
        img = img.convert("RGB")
        img = _apply_warmth(img, preset["warmth"])
        img = ImageEnhance.Brightness(img).enhance(preset["brightness"])
        img = ImageEnhance.Contrast(img).enhance(preset["contrast"])
        img = img.filter(ImageFilter.SMOOTH)

        filename = f"generated_{uuid.uuid4().hex[:10]}.jpg"
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, filename)
        img.save(out_path, "JPEG", quality=90)

    return filename


def generate_description(tags: list[str], prompt_text: str) -> str:
    """AI 설명 문구 생성 (mock). 실제로는 LLM 호출로 대체 가능."""
    tag_str = ", ".join(t for t in tags) if tags else "심플한"
    base = f"{tag_str} 분위기를 반영해 따뜻한 조명과 우드톤 가구를 배치했습니다."
    if prompt_text:
        base += f" 요청하신 '{prompt_text}' 느낌을 살리는 데 집중했어요."
    return base
