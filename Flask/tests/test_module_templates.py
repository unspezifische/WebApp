import unittest
from pathlib import Path

from module_templates import (
    WATERDEEP_MODULE,
    campaign_module_template,
    module_catalog,
    waterdeep_dragon_heist_template,
)


class ModuleTemplateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media_root = Path(__file__).resolve().parents[1] / "media"

    def test_waterdeep_template_contains_renderable_terrain_and_heightmap(self):
        template = waterdeep_dragon_heist_template(self.media_root)
        layers = {layer["layer_type"]: layer for layer in template["reference_layers"]}

        self.assertEqual(template["name"], "Waterdeep")
        self.assertEqual(template["map_key"], "waterdeep")
        self.assertIn("terrain_texture", layers)
        self.assertIn("heightmap", layers)
        self.assertEqual(len(layers["heightmap"]["values"]), 128 * 128)
        self.assertAlmostEqual(
            layers["terrain_texture"]["feet_per_pixel_x"],
            layers["terrain_texture"]["feet_per_pixel_y"],
            delta=0.01,
        )

    def test_waterdeep_template_seeds_editable_content_and_travel_points(self):
        template = campaign_module_template(WATERDEEP_MODULE, self.media_root)

        self.assertGreaterEqual(len(template["roads"]), 40)
        self.assertGreaterEqual(len(template["buildings"]), 3)
        self.assertGreaterEqual(len(template["points_of_interest"]), 12)
        self.assertTrue(any(point["name"] == "The Yawning Portal" for point in template["points_of_interest"]))
        self.assertTrue(any(point["water_access"] for point in template["points_of_interest"]))
        self.assertIn("The High Road", {road["name"] for road in template["roads"]})
        self.assertIn("The Way of the Dragon", {road["name"] for road in template["roads"]})
        self.assertEqual(len(template["environment"]["regions"]), 8)
        self.assertGreaterEqual(len(template["environment"]["fortifications"]), 5)
        self.assertTrue(all(wall["feature_type"] == "city_wall" for wall in template["environment"]["fortifications"]))

    def test_unknown_module_does_not_seed_a_world(self):
        self.assertIsNone(campaign_module_template("Homebrew", self.media_root))

    def test_catalog_exposes_timeline_and_calendar_reconciliation_metadata(self):
        module = module_catalog()[0]
        self.assertEqual(module["starting_year"], 1492)
        self.assertEqual(module["calendar"]["slug"], "harptos")
        self.assertGreaterEqual(module["npc_count"], 35)
        self.assertNotIn("filename", module["calendar"])


if __name__ == "__main__":
    unittest.main()
