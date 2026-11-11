import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import quick_timeline as timeline
import quick_revision as revision

class GeneralRevisionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.pid='a'*32;self.root=Path(temp.name);(self.root/self.pid).mkdir()
        self.app=types.SimpleNamespace(WORK=self.root,project=lambda _: {'name':'General fixture','current_segments':None})
        probe=patch.object(timeline,'probe',return_value={'duration':4,'audio':True});probe.start();self.addCleanup(probe.stop)
    def act(self,action,**args):
        doc=timeline.load(self.app,self.pid)
        return revision.act(self.app,self.pid,dict(action=action,expected_version=doc['version'],**args))
    def test_stack_reload_remove_restore_and_version_conflict(self):
        first=self.act('add_general_note',instruction='Make the whole video warmer.')
        second=self.act('add_general_note',instruction='Use consistent titles.')
        loaded=timeline.load(self.app,self.pid)
        self.assertEqual(loaded['pins'],[])
        self.assertEqual(len(loaded['notes']),2)
        self.assertEqual(loaded['clips'],first['clips'])
        self.assertEqual([n['scope'] for n in loaded['notes']],['general','general'])
        self.assertTrue(all(n['section_id'] is None and n['source_time_ms'] is None for n in loaded['notes']))
        self.assertEqual([n['created_version'] for n in loaded['notes']],[1,2])
        nid=loaded['notes'][0]['id']
        self.act('remove_note',note_id=nid)
        self.assertFalse(timeline.load(self.app,self.pid)['notes'][0]['included'])
        self.act('keep_note',note_id=nid)
        self.assertTrue(timeline.load(self.app,self.pid)['notes'][0]['included'])
        with self.assertRaises(timeline.Conflict):
            revision.act(self.app,self.pid,dict(action='add_general_note',expected_version=second['version'],instruction='Stale'))
    def test_general_notes_validate_text_and_reject_section_anchors(self):
        for extra in [dict(instruction=' '),dict(instruction='x'*2001),dict(instruction='Valid',section_id='b'*32),dict(instruction='Valid',source_time_ms=0)]:
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.act('add_general_note',**extra)
        self.assertEqual(timeline.load(self.app,self.pid)['notes'],[])
        doc=self.act('add_general_note',instruction='Valid')
        with self.assertRaises(ValueError):self.act('edit_note',note_id=doc['notes'][0]['id'],instruction='Changed',pinpoints=[0])

if __name__=='__main__':unittest.main()
