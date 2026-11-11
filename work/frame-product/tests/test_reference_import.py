import unittest
from unittest.mock import patch
import quick_reference_import as q

PID='a'*32;RID='b'*32
class ReferenceImportTests(unittest.TestCase):
    def test_link_conflict_reloads_target_without_losing_changes(self):
        first={'project_id':PID,'version':3,'video_references':[],'clips':['original']}
        changed={**first,'version':4,'clips':['new user edit']}
        done={**changed,'version':5,'video_references':[{'project_id':RID,'name':'Style'}]}
        with patch.object(q,'request',side_effect=[first,ValueError('Revision changed'),changed,done]) as request:
            result=q.link('http://localhost',PID,RID)
        self.assertEqual(request.call_args_list[-1].args[2]['expected_version'],4)
        self.assertEqual(result['project']['clips'],['new user edit'])
        self.assertEqual(result['project_id'],PID)
    def test_ambiguous_link_does_not_repeat_write_and_keeps_recovery_id(self):
        doc={'project_id':PID,'version':1,'video_references':[]}
        with patch.object(q,'request',side_effect=[doc,ValueError('Frame connection was interrupted')]) as request:
            with self.assertRaisesRegex(ValueError,'interrupted'):q.link('http://localhost',PID,RID)
        self.assertEqual(request.call_count,2)
    def test_canonical_hash_duplicate_reuses_saved_reference(self):
        doc={'project_id':PID,'version':1,'video_references':[]}
        canonical='c'*32;done={**doc,'video_references':[{'project_id':canonical,'name':'Original'}],'linked_reference_project_id':canonical}
        with patch.object(q,'request',side_effect=[doc,done]):result=q.link('http://localhost',PID,RID)
        self.assertEqual(result['reference_project_id'],canonical)
    def test_missing_or_multiple_handoffs_rejected_before_transfer(self):
        with patch.object(q.quick_import,'upload') as upload,patch.object(q,'request') as request:
            for args in [{},{'project_id':PID},{'project_id':PID,'source_path':'/x','file':{}},{'project_id':'invalid','reference_project_id':RID}]:
                with self.assertRaises(ValueError):q.import_reference('http://localhost',args)
            upload.assert_not_called();request.assert_not_called()
