"""Preview and atomically apply reusable media layers to an existing Frame cut.

The original source clips remain the base track. Placements use edited output
seconds; video layers are visual overlays (their audio must be placed separately).
"""
import copy
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import time
import uuid

import quick_asset_library as library
import quick_studio as studio
import quick_timeline as timeline

STYLE_FIELDS = set(studio.DEFAULT) - {'captions', 'layers'}
ITEM_FIELDS = {'asset_id', 'start', 'end', 'inpoint', 'x', 'y', 'width', 'volume'}
MEDIA_KINDS = {'clip': 'video', 'video': 'video', 'render': 'video',
               'audio': 'audio', 'sound_effect': 'audio', 'image': 'image'}


def _digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def _visible(record, project_id):
    if record.get('project_id') not in (None, project_id):
        raise ValueError('This library asset belongs to a different project.')
    return record


def _recipe(app, asset_id, kind, project_id):
    row = _visible(library.get(app, asset_id), project_id)
    if row['kind'] != kind:
        raise ValueError('Choose a saved ' + kind + ' recipe.')
    recipe = row.get('recipe')
    if not isinstance(recipe, dict):
        raise ValueError('Saved recipe must be an object.')
    return recipe


def _prepare(app, project_id, expected_version, items, style_id, template_id):
    doc = timeline.load(app, project_id)
    if type(expected_version) is not int or expected_version != doc['version']:
        raise timeline.Conflict('Timeline changed. Refresh before assembling assets.')
    if not isinstance(items, list):
        raise ValueError('Supply an ordered list of asset placements.')
    settings = copy.deepcopy(doc.get('studio', {}))
    placements = []
    if template_id:
        recipe = _recipe(app, template_id, 'template', project_id)
        if set(recipe) - {'studio', 'items'}:
            raise ValueError('Template supports only studio and items.')
        if not isinstance(recipe.get('studio', {}), dict) or not isinstance(recipe.get('items', []), list):
            raise ValueError('Template needs studio settings and ordered items.')
        if set(recipe.get('studio', {})) - (STYLE_FIELDS | {'captions'}):
            raise ValueError('Template media must be supplied as library items.')
        settings.update(copy.deepcopy(recipe.get('studio', {})))
        placements.extend(copy.deepcopy(recipe.get('items', [])))
    if style_id:
        recipe = _recipe(app, style_id, 'style', project_id)
        if recipe.get('format') == 'frame-style/1':
            # Full styles carry pacing/captions/slots too; assembly applies only framing and look here.
            recipe = {**recipe.get('frame', {}), **recipe.get('look', {}),
                      **({'volume': recipe['audio']['voice_volume']} if 'voice_volume' in recipe.get('audio', {}) else {})}
        if set(recipe) - STYLE_FIELDS:
            raise ValueError('Style supports framing, color and volume settings only.')
        settings.update(copy.deepcopy(recipe))
    placements.extend(copy.deepcopy(items))
    if len(placements) > 16:
        raise ValueError('Use up to 16 new media layers.')
    # Reuse the production validator for every non-media studio setting.
    old_layers = settings.pop('layers', [])
    settings = studio.validate(app, project_id, doc, settings)
    settings['layers'] = old_layers
    if not isinstance(old_layers, list) or len(old_layers) + len(placements) > 16:
        raise ValueError('The assembled cut supports up to 16 media layers total.')
    duration = sum(c['end'] - c['start'] for c in doc['clips'])
    records = {}
    for index, item in enumerate(placements):
        if not isinstance(item, dict) or set(item) - ITEM_FIELDS:
            raise ValueError('Unknown assembly placement setting.')
        record = _visible(library.get(app, item.get('asset_id')), project_id)
        kind = MEDIA_KINDS.get(record['kind'])
        if not kind:
            raise ValueError('Only media assets can be placed on the timeline.')
        path = library.resolve(app, record['id'])
        start = studio.num(item.get('start'), 0, min(300, duration), 'Start')
        end = studio.num(item.get('end'), 0, min(300, duration), 'End')
        if end - start < 1 / 30:
            raise ValueError('Each placement must last at least one frame.')
        layer = {'id': 'library_' + hashlib.sha256(json.dumps([expected_version, index, item], sort_keys=True).encode()).hexdigest()[:24],
                 'asset_id': record['id'], 'kind': kind, 'start': start, 'end': end}
        for key, default, low, high in [('inpoint', 0, 0, 300), ('x', .5, 0, 1), ('y', .5, 0, 1), ('width', .4, .05, 1), ('volume', .5, 0, 2)]:
            layer[key] = studio.num(item.get(key, default), low, high, key)
        if kind == 'image':
            from PIL import Image
            try:
                with Image.open(path) as image:
                    if image.width * image.height > 40000000:
                        raise ValueError('Use an image below 40 megapixels.')
                    image.verify()
            except (OSError, SyntaxError):
                raise ValueError('This file is not a readable image.') from None
        else:
            info = studio.media_info(path)
            if not info[kind]:
                raise ValueError('The saved asset does not contain ' + kind + '.')
            if layer['inpoint'] + end - start > info['duration'] + .05:
                raise ValueError('Placement range exceeds its saved media.')
        if any(row.get('id') == layer['id'] for row in settings['layers']):
            raise ValueError('Assembly layer identifier already exists.')
        settings['layers'].append(layer)
        records[record['id']] = record
    return doc, settings, records


def plan_assembly(app, project_id, expected_version, items, style_id=None, template_id=None):
    """Validate a proposed composition without copying bytes or saving edits."""
    with timeline.LOCK:
        doc, settings, records = _prepare(app, project_id, expected_version, items, style_id, template_id)
        return {'project_id': project_id, 'expected_version': expected_version,
                'duration': sum(c['end'] - c['start'] for c in doc['clips']),
                'studio': settings, 'assets': list(records.values()),
                'base_track': 'existing_source_clips', 'applied': False,
                'video_layer_audio': 'Place a separate audio asset to include sound.'}


def apply_assembly(app, project_id, expected_version, items, style_id=None, template_id=None):
    """Copy media first, then commit all layers/settings as one undoable revision."""
    with library.mutation_lock(app, project_id):
        doc, settings, records = _prepare(app, project_id, expected_version, items, style_id, template_id)
        project_root = Path(app.WORK).resolve() / project_id
        assets_root = project_root / 'assets'
        if project_root.is_symlink() or project_root.resolve().parent != Path(app.WORK).resolve() or assets_root.is_symlink():
            raise ValueError('Project assets must use owned directories without symbolic links.')
        before = studio.snapshot(doc)
        target_doc = copy.deepcopy(doc)
        mapping = {}
        created = []
        commit_attempted = False
        try:
            for library_id, record in records.items():
                source = library.resolve(app, library_id)
                existing = next((a for a in target_doc.get('assets', []) if a.get('sha256') == record['sha256']), None)
                if existing:
                    # A hash in metadata alone does not establish available bytes.
                    _, owned = studio.asset_path(app, project_id, target_doc, existing['id'])
                    if _digest(owned) != record['sha256']:
                        raise ValueError('Existing project asset failed its checksum.')
                    mapping[library_id] = existing['id']
                    continue
                asset_id = uuid.uuid4().hex
                folder = app.WORK / project_id / 'assets' / asset_id
                folder.mkdir(parents=True)
                created.append(folder)
                # Catalog names are display data; always take a single safe basename.
                name = Path(record['name'].replace('\\', '/')).name
                if name in ('', '.', '..'):
                    name = 'asset'
                target = folder / name
                with source.open('rb') as src, target.open('xb') as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
                if _digest(target) != record['sha256']:
                    raise ValueError('Copied library asset failed its checksum.')
                directory_fd = os.open(str(folder), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                for parent in (assets_root, project_root):
                    directory_fd = os.open(str(parent), os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                target_doc.setdefault('assets', []).append({
                    'id': asset_id, 'name': name, 'path': target.relative_to(app.WORK / project_id).as_posix(),
                    'sha256': record['sha256'], 'size': target.stat().st_size,
                    'mime_type': record.get('mime_type') or mimetypes.guess_type(name)[0] or 'application/octet-stream',
                    'created_at': time.time(), 'library_asset_id': library_id,
                    'url': '/api/quick/projects/' + project_id + '/assets/' + asset_id + '/download'})
                mapping[library_id] = asset_id
            new_layer_ids = {row['id'] for row in settings['layers']} - {row['id'] for row in doc.get('studio', {}).get('layers', [])}
            for layer in settings['layers']:
                if layer['id'] in new_layer_ids:
                    layer['asset_id'] = mapping[layer['asset_id']]
            target_doc['studio'] = studio.validate(app, project_id, target_doc, settings)
            if before == studio.snapshot(target_doc):
                return timeline.public(doc)
            target_doc['undo'] = (target_doc.get('undo', []) + [before])[-100:]
            target_doc['redo'] = []
            target_doc['version'] += 1
            target_doc.setdefault('accepted_edits', []).append({
                'id': uuid.uuid4().hex, 'provider': 'asset_library', 'operation': 'apply_asset_assembly',
                'arguments': {'items': items, 'style_id': style_id, 'template_id': template_id},
                'timeline_version': target_doc['version'], 'accepted_at': time.time()})
            commit_attempted = True
            timeline.write(app.WORK / project_id / 'timeline.json', target_doc)
            result = timeline.public(target_doc)
            result['assembly_asset_mapping'] = mapping
            return result
        except Exception:
            # Once atomic replace was attempted, its outcome can be uncertain.
            # Preserve bytes rather than risk deleting a committed dependency.
            if not commit_attempted:
                for folder in created:
                    shutil.rmtree(folder, ignore_errors=True)
            raise
