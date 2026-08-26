import unittest
from unittest.mock import Mock, patch

import app as app_module


class CampaignNameQuery:
    def __init__(self, campaign, conflict=None):
        self.campaign = campaign
        self.conflict = conflict

    def get(self, campaign_id):
        return self.campaign if campaign_id == self.campaign.id else None

    def filter(self, *_criteria):
        result = Mock()
        result.first.return_value = self.conflict
        return result


class CampaignNameTests(unittest.TestCase):
    def test_rename_changes_only_the_display_name(self):
        campaign = app_module.Campaign(
            id=12,
            name='Old Name',
            system='D&D',
            ruleset='5e',
            owner_id=3,
            dm_id=3,
        )
        page = app_module.Page(title='Main Page', content='Welcome', wiki_id=12)
        session = Mock()

        with app_module.app.test_request_context(
            '/api/campaigns/12/name', method='PATCH', json={'name': ' New Name '}
        ), patch.object(
            app_module.Campaign, 'query', CampaignNameQuery(campaign)
        ), patch.object(
            app_module, 'user_can_edit_campaign', return_value=True
        ), patch.object(
            app_module.db, 'session', session
        ):
            response, status = app_module.update_campaign_name.__wrapped__(12)

        self.assertEqual(status, 200)
        self.assertEqual(campaign.id, 12)
        self.assertEqual(campaign.name, 'New Name')
        self.assertEqual(page.wiki_id, 12)
        self.assertEqual(response.get_json()['campaign']['name'], 'New Name')
        session.commit.assert_called_once_with()

    def test_rename_rejects_an_ambiguous_existing_name(self):
        campaign = app_module.Campaign(
            id=12,
            name='Old Name',
            system='D&D',
            owner_id=3,
            dm_id=3,
        )
        conflict = app_module.Campaign(
            id=13,
            name='Existing Name',
            system='D&D',
            owner_id=4,
            dm_id=4,
        )

        with app_module.app.test_request_context(
            '/api/campaigns/12/name', method='PATCH', json={'name': 'existing name'}
        ), patch.object(
            app_module.Campaign, 'query', CampaignNameQuery(campaign, conflict)
        ), patch.object(
            app_module, 'user_can_edit_campaign', return_value=True
        ):
            response, status = app_module.update_campaign_name.__wrapped__(12)

        self.assertEqual(status, 409)
        self.assertEqual(campaign.name, 'Old Name')
        self.assertEqual(response.get_json()['message'], 'Another campaign already uses that name')


if __name__ == '__main__':
    unittest.main()
