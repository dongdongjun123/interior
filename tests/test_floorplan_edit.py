from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from model2.web_floorplan import (
    apply_floorplan_edits_to_layout,
    prepare_floorplan_edit_markup,
    sanitize_floorplan_edit_svg,
)


class FloorplanEditTests(unittest.TestCase):
    def test_original_furniture_receives_edit_wrapper_and_controls(self) -> None:
        svg = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
          <rect x="100" y="70" width="824" height="880" fill="#eee"/>
          <g id="bed_1"><rect x="150" y="120" width="200" height="300"/></g>
          <g id="door_1"><path d="M0 0L20 20"/></g>
        </svg>
        """
        layout = {
            "objects": [
                {
                    "scene_id": "bed_1",
                    "type": "bed",
                    "x": 0.3,
                    "y": 0.35,
                    "w": 0.2,
                    "h": 0.3,
                },
                {
                    "scene_id": "door_1",
                    "type": "door",
                    "x": 0.1,
                    "y": 0.1,
                },
            ]
        }
        edited = prepare_floorplan_edit_markup(svg, layout)
        root = ET.fromstring(edited)
        wrappers = [
            element
            for element in root.iter()
            if element.attrib.get("data-original-furniture") == "true"
        ]
        self.assertEqual(len(wrappers), 1)
        self.assertEqual(wrappers[0].attrib["data-scene-id"], "bed_1")
        controls = [
            element
            for element in wrappers[0].iter()
            if element.attrib.get("data-edit-control") == "true"
        ]
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0].attrib["style"], "display:none")

    def test_saved_floorplan_rejects_event_handlers(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_floorplan_edit_svg(
                '<svg><rect onclick="alert(1)" width="10" height="10"/></svg>'
            )

    def test_saved_transform_updates_later_placement_layout(self) -> None:
        svg = """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">
          <rect x="100" y="70" width="824" height="880" fill="#eee"/>
          <g data-original-furniture="true" data-scene-id="bed_1"
             data-tx="512" data-ty="510" data-angle="90" data-scale="1.2"/>
        </svg>
        """
        layout = {
            "objects": [
                {
                    "scene_id": "bed_1",
                    "type": "bed",
                    "x": 0.2,
                    "y": 0.2,
                    "w": 0.2,
                    "h": 0.3,
                }
            ]
        }
        result = apply_floorplan_edits_to_layout(svg, layout)
        bed = result["objects"][0]
        self.assertAlmostEqual(bed["x"], 0.5)
        self.assertAlmostEqual(bed["y"], 0.5)
        self.assertAlmostEqual(bed["w"], 0.36)
        self.assertAlmostEqual(bed["h"], 0.24)


if __name__ == "__main__":
    unittest.main()
