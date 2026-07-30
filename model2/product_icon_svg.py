"""Generate a safe, self-contained product icon SVG from one shopping photo."""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from typing import Any

from google.genai import types

from .gemini_svg_experiment import _extract_svg


DEFAULT_ICON_SIZE = 200

ICON_PROMPT_TEMPLATE = """
You are an expert interior illustrator and SVG artist.
Look at the supplied shopping photo and draw only the sold furniture product
as a polished small icon for a warm hand-drawn architectural floorplan.

Visual requirements:
- Preserve the product's real silhouette, proportions, dominant colors,
  material, section count, cushions, arms, frame, storage and distinctive
  pattern as closely as a small icon allows.
- The photo is authoritative for color. Shopping titles often list several
  option colors that are not the pictured option. Use a title color only when
  that same color is visibly supported by the supplied photo.
- Convert the photographic perspective into a directly overhead orthographic
  view. A very gentle isometric cue is allowed only inside the object where it
  explains its construction.
- Make the product immediately recognizable. Use curved paths, restrained
  local highlights and small gradients to describe actual volume. Do not fake
  depth with a large offset shadow or a thick duplicate silhouette.
- Draw only the product being sold. Exclude the room, floor, wall, people,
  decorations, dimensions, labels and unrelated props.
- If the listing is for a frame, cabinet or storage product, do not invent
  bedding, cushions or accessories that are not part of that product.
- Transparent background. Keep every visible shape inside the canvas.

Technical requirements:
- Return ONLY one complete <svg>...</svg>, without Markdown or explanation.
- Use viewBox="0 0 {size} {size}", width="{size}", height="{size}".
- Put the complete icon inside one top-level <g id="icon">.
- Self-contained vector SVG only. No image, external URL, font, script,
  foreignObject, animation, event handler or embedded raster data.
- Use only svg, g, defs, path, rect, circle, ellipse, line, polyline, polygon,
  linearGradient, radialGradient, stop and clipPath elements.
- Use SVG presentation attributes directly on elements. Do not use a style
  element or style attributes.
- Use at most 120 SVG elements. Keep paths compact.
""".strip()


ALLOWED_TAGS = {
    "svg", "g", "defs", "path", "rect", "circle", "ellipse", "line",
    "polyline", "polygon", "linearGradient", "radialGradient", "stop",
    "clipPath",
}


def generate_product_icon_svg(
    client: Any,
    image_bytes: bytes,
    mime_type: str,
    *,
    title: str,
    category: str,
    model: str,
    size: int = DEFAULT_ICON_SIZE,
) -> str:
    """Ask Gemini for a direct SVG icon and return a sanitized SVG document."""
    prompt = ICON_PROMPT_TEMPLATE.format(size=size)
    prompt += (
        "\n\nPRODUCT INFO:"
        f"\n- category: {category}"
        f"\n- title: {title}"
    )
    response = client.models.generate_content(
        model=model,
        contents=[
            prompt,
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="text/plain",
            temperature=0.2,
            max_output_tokens=12000,
        ),
    )
    if not response.text:
        raise RuntimeError("Gemini가 상품 아이콘 SVG를 반환하지 않았습니다.")
    return sanitize_product_icon_svg(
        _extract_svg(str(response.text)),
        size=size,
    )


def sanitize_product_icon_svg(svg_text: str, *, size: int = DEFAULT_ICON_SIZE) -> str:
    """Validate direct SVG output and namespace local definition IDs."""
    root = ET.fromstring(svg_text)
    elements = list(root.iter())
    if len(elements) > 140:
        raise ValueError("상품 아이콘 SVG 요소가 너무 많습니다.")

    prefix = "pi-" + hashlib.sha256(svg_text.encode("utf-8")).hexdigest()[:10]
    id_map: dict[str, str] = {}
    for element in elements:
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in ALLOWED_TAGS:
            raise ValueError(f"상품 아이콘에 허용되지 않는 SVG 요소: {tag}")
        element_id = str(element.attrib.get("id") or "")
        if element_id:
            id_map[element_id] = f"{prefix}-{element_id}"

        for name, value in list(element.attrib.items()):
            local_name = name.rsplit("}", 1)[-1].lower()
            lowered = str(value).lower()
            if (
                local_name.startswith("on")
                or local_name in {"href", "style"}
                or "javascript:" in lowered
                or "data:" in lowered
                or "url(http" in lowered
            ):
                raise ValueError("상품 아이콘 SVG에 외부 또는 실행 속성이 포함됐습니다.")
            if local_name == "d" and len(str(value)) > 6000:
                raise ValueError("상품 아이콘 SVG path가 너무 복잡합니다.")

    for element in elements:
        element_id = str(element.attrib.get("id") or "")
        if element_id in id_map:
            element.set("id", id_map[element_id])
        for name, value in list(element.attrib.items()):
            rewritten = str(value)
            for old_id, new_id in id_map.items():
                rewritten = rewritten.replace(f"url(#{old_id})", f"url(#{new_id})")
                rewritten = rewritten.replace(f"#{old_id}", f"#{new_id}")
            element.set(name, rewritten)

    root.set("viewBox", root.attrib.get("viewBox") or f"0 0 {size} {size}")
    root.set("width", str(size))
    root.set("height", str(size))
    return ET.tostring(root, encoding="unicode")
