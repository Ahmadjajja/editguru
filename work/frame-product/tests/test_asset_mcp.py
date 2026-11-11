import io
import json
import unittest
from unittest.mock import patch
import quick_asset_mcp as bridge
import quick_mcp


class AssetMCPTests(unittest.TestCase):
    def test_schema_has_project_optional_reads_and_explicit_mutation_version(self):
        specs={tool['name']:tool for tool in quick_mcp.tools()}
        self.assertEqual(specs['index_project_assets']['inputSchema']['required'],['project_id'])
        self.assertNotIn('expected_version',specs['index_project_assets']['inputSchema']['properties'])
        self.assertNotIn('project_id',specs['search_asset_library']['inputSchema']['required'])
        self.assertNotIn('expected_version',specs['save_library_asset']['inputSchema']['properties'])
        self.assertEqual(specs['attach_library_asset']['inputSchema']['required'],['library_asset_id','project_id','expected_version'])
        self.assertNotIn('project_id',specs['create_video_from_library']['inputSchema']['properties'])
        self.assertNotIn('expected_version',specs['create_video_from_library']['inputSchema']['properties'])
        self.assertTrue(specs['plan_asset_assembly']['annotations']['readOnlyHint'])
        self.assertFalse(specs['apply_asset_assembly']['annotations']['readOnlyHint'])
        self.assertEqual(set(specs)&bridge.TOOLS,bridge.TOOLS)

    def test_bridge_preserves_structured_args_and_explicit_operation(self):
        response=io.BytesIO(b'{"assets":[]}')
        with patch.object(bridge.urllib.request,'urlopen',return_value=response) as request:
            result=quick_mcp.call('search_asset_library',{'tags':['cinematic'],'query':'whoosh'})
        self.assertEqual(result,{'assets':[]})
        req=request.call_args[0][0]
        self.assertEqual(json.loads(req.data),{'operation':'search_asset_library','tags':['cinematic'],'query':'whoosh'})
        self.assertTrue(req.full_url.endswith('/api/quick/library'))

    def test_initialize_contains_reuse_guidance(self):
        result=quick_mcp.dispatch({'id':1,'method':'initialize'})
        self.assertIn('search_asset_library',result['result']['instructions'])
        self.assertIn('reference data',result['result']['instructions'])

if __name__ == '__main__':unittest.main()
