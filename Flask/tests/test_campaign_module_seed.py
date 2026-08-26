import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as app_module


class RecordingSession:
    def __init__(self):
        self.added = []
        self.flushes = 0

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flushes += 1

    def delete(self, value):
        self.added.remove(value) if value in self.added else None


class QueryResult:
    def __init__(self, first=None, all_values=None):
        self.first_value = first
        self.all_values = all_values or []

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self.first_value

    def all(self):
        return self.all_values


class CampaignModuleSeedTest(unittest.TestCase):
    def test_waterdeep_campaign_gets_primary_settlement_party_and_pois(self):
        campaign = SimpleNamespace(id=41, module="Waterdeep Dragon Heist")
        session = RecordingSession()

        with patch.object(app_module.db, "session", session), \
                patch.object(app_module, "persist_reference_layer_media", side_effect=lambda _campaign_id, template: template):
            location = app_module.seed_campaign_world(campaign)

        self.assertEqual(location.name, "Waterdeep")
        self.assertEqual(location.map_key, "waterdeep")
        self.assertTrue(location.is_primary)
        self.assertAlmostEqual(location.atlas_x, 0.455)
        self.assertAlmostEqual(location.atlas_y, 0.265)
        self.assertGreaterEqual(len(location.roads), 6)
        self.assertTrue(any(layer.get("layer_type") == "heightmap" for layer in location.reference_layers))
        self.assertEqual(session.flushes, 1)
        self.assertEqual(sum(isinstance(value, app_module.PartyMapPosition) for value in session.added), 1)
        self.assertGreaterEqual(sum(isinstance(value, app_module.MapPointOfInterest) for value in session.added), 12)

    def test_homebrew_campaign_keeps_generic_creation_path(self):
        campaign = SimpleNamespace(id=42, module="Homebrew")
        session = RecordingSession()

        with patch.object(app_module.db, "session", session):
            location = app_module.seed_campaign_world(campaign)

        self.assertIsNone(location)
        self.assertEqual(session.added, [])

    def test_module_calendar_is_created_with_harptos_and_module_year(self):
        campaign = SimpleNamespace(id=43, name="Continued Heroes")
        definition = app_module.module_definition("waterdeep_dragon_heist")
        format_element = SimpleNamespace(id=9)
        session = RecordingSession()

        with app_module.app.app_context(), \
             patch.object(app_module.GameElement, "query", QueryResult(first=format_element)), \
             patch.object(app_module.Calendar, "query", QueryResult(first=None)), \
             patch.object(app_module.db, "session", session):
            calendar = app_module.ensure_module_calendar(campaign, definition, strategy="use_module")

        self.assertEqual(calendar.format_slug, "harptos")
        self.assertEqual(calendar.current_year, 1492)
        self.assertIn(calendar, session.added)

    def test_merge_preserves_existing_records_and_adds_new_stable_ids(self):
        existing = [{"id": "custom-road", "name": "DM road"}, {"id": "shared", "name": "Current"}]
        incoming = [{"id": "shared", "name": "Module replacement"}, {"id": "module-road", "name": "Module road"}]

        merged = app_module._merge_template_records(existing, incoming)

        self.assertEqual([record["id"] for record in merged], ["custom-road", "shared", "module-road"])
        self.assertEqual(merged[1]["name"], "Current")

    def test_module_npc_refresh_adds_missing_named_npcs_without_duplicates(self):
        campaign = SimpleNamespace(id=44)
        existing = SimpleNamespace(name="Laeral Silverhand")
        session = RecordingSession()
        definition = app_module.module_definition("waterdeep_dragon_heist")

        with app_module.app.app_context(), \
             patch.object(app_module.NPC, "query", QueryResult(all_values=[existing])), \
             patch.object(app_module.db, "session", session):
            added = app_module.seed_module_npcs(campaign, definition)

        self.assertGreaterEqual(len(added), 34)
        self.assertNotIn("Laeral Silverhand", {npc.name for npc in added})
        self.assertIn("Jarlaxle Baenre", {npc.name for npc in added})
        self.assertEqual(len(added), len(session.added))


if __name__ == "__main__":
    unittest.main()
