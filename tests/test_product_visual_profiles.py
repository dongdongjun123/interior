from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from model2.web_floorplan import (
    _add_direct_product_icon,
    _add_profiled_product_shape,
    _apply_product_title_cues,
    _normalize_visual_profile,
)
from model2.product_icon_svg import sanitize_product_icon_svg


class ProductVisualProfileTests(unittest.TestCase):
    def test_title_corrects_storage_bed_color_and_structure(self) -> None:
        profile = _apply_product_title_cues(
            {
                "shape": "rounded_rectangle",
                "primary_color": "#9E8872",
                "secondary_color": "#D8C8B6",
                "corner_roundness": 0.8,
                "has_cushions": True,
            },
            {
                "type": "bed",
                "title": "리프트업 수납 침대 프레임 화이트 오크",
            },
        )
        self.assertEqual(profile["primary_color"], "#E6DDCD")
        self.assertEqual(profile["shape"], "rectangle")
        self.assertEqual(profile["storage_type"], "lift_up")
        self.assertTrue(profile["is_frame_only"])
        self.assertFalse(profile["has_cushions"])

    def test_local_image_color_beats_generic_title_option(self) -> None:
        profile = _apply_product_title_cues(
            {
                "shape": "rounded_rectangle",
                "primary_color": "#656D72",
                "secondary_color": "#899AA5",
                "analysis_source": "local",
            },
            {
                "type": "bed",
                "title": "패브릭 침대 아이방 화이트 쿠션 저상형 헤드",
            },
        )
        self.assertEqual(profile["primary_color"], "#656D72")

    def test_multiple_rug_color_options_do_not_override_image(self) -> None:
        profile = _apply_product_title_cues(
            {
                "shape": "rectangle",
                "primary_color": "#D1C3BA",
                "secondary_color": "#B6A598",
                "analysis_source": "local",
            },
            {
                "type": "rug",
                "title": "극세사 머스타드 브라운 월넛 차콜 패드",
            },
        )
        self.assertEqual(profile["primary_color"], "#D1C3BA")

    def test_lift_up_profile_renders_storage_detail(self) -> None:
        group = ET.Element("g")
        profile = _normalize_visual_profile(
            {
                "shape": "rectangle",
                "primary_color": "#E6DDCD",
                "secondary_color": "#F6F2E9",
                "material": "wood",
                "corner_roundness": 0.08,
                "has_headboard": True,
                "has_cushions": False,
                "storage_type": "lift_up",
                "is_frame_only": True,
            }
        )
        _add_profiled_product_shape(
            group,
            profile,
            item_type="bed",
            width=144,
            height=192,
        )
        dashed = [
            element
            for element in group.iter()
            if element.attrib.get("stroke-dasharray") == "5 3"
        ]
        self.assertEqual(len(dashed), 1)

    def test_gemini_parts_are_validated_and_rendered(self) -> None:
        profile = _normalize_visual_profile(
            {
                "shape": "rectangle",
                "primary_color": "#E6DDCD",
                "secondary_color": "#F6F2E9",
                "parts": [
                    {
                        "primitive": "rect",
                        "role": "frame",
                        "x": -2,
                        "y": 0,
                        "width": 1.4,
                        "height": 1,
                        "fill": "primary",
                        "z_index": 0,
                    },
                    {
                        "primitive": "ellipse",
                        "role": "cushion",
                        "x": 0.1,
                        "y": 0.1,
                        "width": 0.35,
                        "height": 0.2,
                        "fill": "light",
                        "z_index": 2,
                    },
                    {
                        "primitive": "line",
                        "role": "division",
                        "x": 0.5,
                        "y": 0.2,
                        "width": 0.5,
                        "height": 0.8,
                        "fill": "none",
                        "z_index": 3,
                    },
                    {
                        "primitive": "script",
                        "role": "invalid",
                    },
                ],
            }
        )
        self.assertEqual(len(profile["parts"]), 3)
        self.assertEqual(profile["parts"][0]["x"], 0.0)
        self.assertEqual(profile["parts"][0]["width"], 1.0)

        group = ET.Element("g")
        _add_profiled_product_shape(
            group,
            profile,
            item_type="bed",
            width=144,
            height=192,
        )
        roles = {
            element.attrib.get("data-product-part")
            for element in group.iter()
        }
        self.assertIn("frame", roles)
        self.assertIn("cushion", roles)
        self.assertIn("division", roles)
        self.assertNotIn("invalid", roles)

    def test_direct_icon_svg_is_sanitized_and_fitted(self) -> None:
        sanitized = sanitize_product_icon_svg(
            """
            <svg viewBox="0 0 200 200">
              <defs>
                <linearGradient id="fabric">
                  <stop offset="0" stop-color="#ddeeff"/>
                  <stop offset="1" stop-color="#88aacc"/>
                </linearGradient>
              </defs>
              <g id="icon">
                <rect x="10" y="20" width="180" height="160"
                      fill="url(#fabric)"/>
              </g>
            </svg>
            """
        )
        self.assertNotIn('id="fabric"', sanitized)
        self.assertIn("url(#pi-", sanitized)
        group = ET.Element("g")
        self.assertTrue(
            _add_direct_product_icon(
                group,
                sanitized,
                width=100,
                height=80,
            )
        )
        self.assertEqual(
            group[0].attrib.get("data-direct-product-icon"),
            "true",
        )

    def test_direct_icon_svg_rejects_executable_content(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_product_icon_svg(
                """
                <svg viewBox="0 0 200 200">
                  <rect onclick="alert(1)" width="100" height="100"/>
                </svg>
                """
            )


if __name__ == "__main__":
    unittest.main()
