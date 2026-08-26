import unittest
import io
import tempfile
from pathlib import Path
from unittest import mock

from PIL import Image
from mutagen.id3 import APIC, ID3

import app as app_module


class SoundUploadErrorTest(unittest.TestCase):
    def test_upload_errors_include_a_safe_code_and_filename(self):
        with app_module.app.app_context():
            response, status = app_module.sound_upload_error(
                'The file is larger than the 1 GB upload limit.',
                'file_too_large',
                413,
                '../../battle theme.mp3',
            )

        self.assertEqual(status, 413)
        self.assertEqual(response.get_json(), {
            'message': 'The file is larger than the 1 GB upload limit.',
            'error': {
                'code': 'file_too_large',
                'filename': 'battle_theme.mp3',
            },
        })

    def test_embedded_id3_cover_is_extracted_and_normalized(self):
        image_bytes = io.BytesIO()
        Image.new('RGB', (48, 48), '#6d4aa5').save(image_bytes, 'PNG')
        with tempfile.TemporaryDirectory() as directory:
            sound_path = Path(directory) / 'covered.mp3'
            tags = ID3()
            tags.add(APIC(mime='image/png', type=3, desc='Cover', data=image_bytes.getvalue()))
            tags.save(sound_path)

            extracted = app_module.extract_embedded_sound_cover(sound_path)

        self.assertIsNotNone(extracted)
        cover_bytes, extension, mimetype = extracted
        self.assertEqual(extension, 'jpg')
        self.assertEqual(mimetype, 'image/jpeg')
        with Image.open(io.BytesIO(cover_bytes)) as cover:
            self.assertEqual(cover.size, (48, 48))

    def test_sound_payload_includes_cover_url(self):
        asset = app_module.SoundAsset(
            id=4, name='Covered track', filename='track.mp3', original_filename='track.mp3',
            mimetype='audio/mpeg', category='music', uploaded_by_id=1,
            cover_filename='cover.jpg', cover_mimetype='image/jpeg',
        )
        self.assertEqual(asset.to_dict()['coverUrl'], '/media/sounds/covers/cover.jpg')

    @mock.patch.object(app_module.shutil, 'which', return_value='/usr/bin/ffmpeg')
    @mock.patch.object(app_module.subprocess, 'run')
    def test_lossless_audio_is_transcoded_to_streamable_mp3(self, run, _which):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'long-session.wav'
            destination = Path(directory) / 'long-session.mp3'
            source.write_bytes(b'wave data')

            def finish_conversion(command, **_kwargs):
                destination.write_bytes(b'compressed mp3 data')
                return app_module.subprocess.CompletedProcess(command, 0, '', '')

            run.side_effect = finish_conversion
            app_module.transcode_sound_to_mp3(source, destination)

        command = run.call_args.args[0]
        self.assertIn('libmp3lame', command)
        self.assertIn('192k', command)


if __name__ == '__main__':
    unittest.main()
