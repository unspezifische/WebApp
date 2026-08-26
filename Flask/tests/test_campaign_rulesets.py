import unittest

from app import Campaign, DND_RULESET_SYSTEMS


class CampaignRulesetTests(unittest.TestCase):
    def test_each_dnd_ruleset_has_a_distinct_catalog_key(self):
        self.assertEqual(DND_RULESET_SYSTEMS, {
            '3.5e': 'D&D 3.5e',
            '4e': 'D&D 4e',
            '5e': 'D&D 5e',
            '5e (2024)': 'D&D 5e (2024)',
        })

    def test_campaign_exposes_system_and_effective_rules_system(self):
        campaign = Campaign(name='Test', system='D&D', ruleset='5e (2024)', owner_id=1, dm_id=1)
        self.assertEqual(campaign.system, 'D&D')
        self.assertEqual(campaign.rules_system, 'D&D 5e (2024)')

    def test_legacy_five_e_campaign_remains_compatible_before_migration(self):
        campaign = Campaign(name='Legacy', system='D&D 5e', owner_id=1, dm_id=1)
        self.assertEqual(campaign.rules_system, 'D&D 5e')


if __name__ == '__main__':
    unittest.main()
