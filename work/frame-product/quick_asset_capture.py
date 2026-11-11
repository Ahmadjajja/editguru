"""Copy completed renders into the persistent library without losing export success."""
def capture_upload(app, project_id, asset):
    try:
        import quick_asset_library
        item = quick_asset_library.register_file(
            app, app.WORK/project_id/asset['path'], name=asset['name'],
            project_id=project_id, metadata={'source_project_id': project_id,
                'source_asset_id': asset['id']})
        return {'library_asset_id': item['id']}
    except Exception as exc:
        return {'library_capture_error': str(exc)[-600:]}


def capture_render(app, project_id, export_id, source_path, name, timeline_version=None):
    try:
        import quick_asset_library
        item = quick_asset_library.register_file(
            app, source_path, name=name, kind='render', project_id=project_id,
            tags=['render'], metadata={'source_project_id': project_id,
                'export_id': export_id, 'timeline_version': timeline_version})
        return {'library_asset_id': item['id']}
    except Exception as exc:
        # The original completed render is still the canonical export. A failed
        # library copy is visible and can be retried through save_library_asset.
        return {'library_capture_error': str(exc)[-600:]}
