import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import app as app_module


class ProfileImagePresetTest(unittest.TestCase):
    def test_character_preset_resolves_to_a_public_image(self):
        character = app_module.Character(
            character_name='Mira Vale',
            avatar_mode='preset',
            avatar_preset_key='wizard',
        )

        avatar = character.get_avatar_props()

        self.assertEqual(avatar['mode'], 'preset')
        self.assertEqual(avatar['image_url'], '/avatars/wizard.webp')
        self.assertEqual(avatar['full_image_url'], '/avatars/wizard.webp')

    def test_campaign_icon_upload_is_normalized_to_a_square_webp(self):
        source = io.BytesIO()
        Image.new('RGB', (900, 450), '#845f37').save(source, format='PNG')
        source.seek(0)

        class Upload:
            stream = source

        with tempfile.TemporaryDirectory() as directory:
            previous_root = app_module.app.config['CAMPAIGN_ICON_ROOT']
            app_module.app.config['CAMPAIGN_ICON_ROOT'] = directory
            try:
                url = app_module.save_campaign_icon(Upload(), 17)
            finally:
                app_module.app.config['CAMPAIGN_ICON_ROOT'] = previous_root

            output = Path(directory) / url.removeprefix('/media/campaign-icons/')
            self.assertTrue(output.exists())
            with Image.open(output) as image:
                self.assertEqual(image.size, (512, 512))
                self.assertEqual(image.format, 'WEBP')

    def test_preset_keys_are_unique(self):
        for presets in (app_module.CAMPAIGN_ICON_PRESETS, app_module.CHARACTER_AVATAR_PRESETS):
            keys = [preset['key'] for preset in presets]
            self.assertEqual(len(keys), len(set(keys)))


if __name__ == '__main__':
    unittest.main()
