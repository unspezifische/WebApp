import unittest
from unittest import mock

import app as app_module


class QuickEffectSlotsTest(unittest.TestCase):
    def test_serialization_always_exposes_six_slots(self):
        with app_module.app.app_context(), mock.patch.object(app_module.SoundQuickEffectSlot, 'query') as query:
            query.filter_by.return_value.all.return_value = []
            slots = app_module.serialized_quick_effect_slots(42)

        self.assertEqual([slot['slot'] for slot in slots], [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(slot['sound'] is None for slot in slots))


if __name__ == '__main__':
    unittest.main()
