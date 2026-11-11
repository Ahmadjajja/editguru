import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import editor

class MediaProbeTests(unittest.TestCase):
    def test_valid_video_preserves_metadata_with_bounded_probe(self):
        data={'streams':[{'codec_type':'video','width':1920,'height':1080},{'codec_type':'audio'}],'format':{'duration':'4.25'}}
        with patch.object(editor,'run',return_value=json.dumps(data)) as run:
            self.assertEqual(editor.probe(Path('/private/input.mp4')),{'duration':4.25,'audio':True,'width':1920,'height':1080})
            self.assertEqual(run.call_args.kwargs['timeout'],30)

    def test_phone_rotation_reports_displayed_dimensions(self):
        cases=[({'side_data_list':[{'rotation':-90}]},(1080,1920)),
               ({'side_data_list':[{'rotation':90}]},(1080,1920)),
               ({'tags':{'rotate':'270'}},(1080,1920)),
               ({'side_data_list':[{'rotation':180}]},(1920,1080)),
               ({'side_data_list':[{'rotation':0}],'tags':{'rotate':'90'}},(1920,1080))]
        for extra,expected in cases:
            data={'streams':[{'codec_type':'video','width':1920,'height':1080,**extra}],'format':{'duration':'4.25'}}
            with self.subTest(extra=extra),patch.object(editor,'run',return_value=json.dumps(data)):
                result=editor.probe(Path('phone.mov'))
                self.assertEqual((result['width'],result['height']),expected)

    def test_non_square_pixels_report_display_shape_before_rotation(self):
        for extra,expected in [({'sample_aspect_ratio':'2:1'},(320,90)),
                               ({'sample_aspect_ratio':'2:1','side_data_list':[{'rotation':90}]},(90,320)),
                               ({'sample_aspect_ratio':'1:2'},(80,90)),
                               ({'sample_aspect_ratio':'N/A'},(160,90)),
                               ({'sample_aspect_ratio':'0:1'},(160,90))]:
            data={'streams':[{'codec_type':'video','width':160,'height':90,**extra}],'format':{'duration':'1'}}
            with self.subTest(extra=extra),patch.object(editor,'run',return_value=json.dumps(data)):
                info=editor.probe(Path('input.mp4'))
                self.assertEqual((info['width'],info['height']),expected)

    def test_timeout_and_decoder_failures_have_actionable_messages(self):
        for error,message in [(subprocess.TimeoutExpired(['ffprobe','/private/input.mp4'],30),'within 30 seconds'),(RuntimeError('/private/input.mp4: Invalid data'),'H.264/AAC MP4')]:
            with self.subTest(error=error),patch.object(editor,'run',side_effect=error):
                with self.assertRaisesRegex(ValueError,message) as caught:editor.probe(Path('/private/input.mp4'))
                self.assertNotIn('/private/',str(caught.exception))

    def test_bad_metadata_is_a_readable_validation_error(self):
        values=[json.dumps({'streams':[{'codec_type':'video','width':20,'height':20,'tags':{'rotate':'nan'}}],'format':{'duration':'1'}}),'not json',json.dumps([]),json.dumps({}),json.dumps({'streams':[{'codec_type':'video','width':0,'height':20}],'format':{'duration':'1'}}),json.dumps({'streams':[{'codec_type':'video','width':20,'height':20}],'format':{'duration':'N/A'}})]
        for value in values:
            with self.subTest(value=value),patch.object(editor,'run',return_value=value):
                with self.assertRaisesRegex(ValueError,'[Tt]ry exporting'):editor.probe(Path('input.mp4'))

    def test_audio_only_is_not_a_video(self):
        with patch.object(editor,'run',return_value=json.dumps({'streams':[{'codec_type':'audio'}],'format':{'duration':'1'}})):
            with self.assertRaisesRegex(ValueError,'upload a video'):editor.probe(Path('audio.mp3'))

    def test_duration_limits_remain_enforced(self):
        for duration in ['nan','inf','0','301']:
            data={'streams':[{'codec_type':'video','width':20,'height':20}],'format':{'duration':duration}}
            with self.subTest(duration=duration),patch.object(editor,'run',return_value=json.dumps(data)):
                with self.assertRaisesRegex(ValueError,'300 seconds'):editor.probe(Path('input.mp4'))
        data['format']['duration']='301'
        with patch.object(editor,'run',return_value=json.dumps(data)):
            self.assertEqual(editor.probe(Path('output.mp4'),enforce_limit=False)['duration'],301)

if __name__=='__main__':unittest.main()
