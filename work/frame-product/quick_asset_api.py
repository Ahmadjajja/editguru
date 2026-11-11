"""Loopback API for creator assets; project-owned sources only, never path uploads."""
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import quick_timeline as timeline
import quick_asset_library as library


def identifier(value, label='project'):
    if not isinstance(value, str) or not re.fullmatch(timeline.ID, value):
        raise ValueError('Invalid '+label+' ID.')
    return value


def project(app, pid):
    identifier(pid)
    with timeline.LOCK:
        return timeline.load(app, pid)


def accessible(app, aid, pid=None):
    asset = library.get(app, identifier(aid, 'library asset'))
    if pid is not None:
        project(app, pid)
    if asset.get('project_id') is not None and asset['project_id'] != pid:
        raise ValueError('Asset is scoped to another project.')
    return asset


def owned_file(app, pid, relative):
    root = app.WORK.resolve()/identifier(pid)
    path = root/relative
    if path.is_symlink() or root.is_symlink() or any(p.is_symlink() for p in path.parents if p == root or root in p.parents):
        raise ValueError('Asset source must be an owned project file.')
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('Asset source must be an owned project file.')
    return path


def save_project_asset(app, args):
    pid = args.get('project_id')
    doc = project(app, pid)
    aid, export_id = args.get('asset_id'), args.get('export_id')
    if (aid is None) == (export_id is None):
        raise ValueError('Choose exactly one project asset_id or export_id (source for original footage).')
    provenance = {'project_id': pid}
    kind = args.get('kind')
    tags = args.get('tags')
    if aid is not None:
        identifier(aid, 'project asset')
        asset = next((a for a in doc.get('assets', []) if a['id'] == aid), None)
        if not asset:
            raise ValueError('Project asset not found.')
        path = owned_file(app, pid, asset['path'])
        name = args.get('name') or asset['name']
        if kind is None and asset.get('kind') in library.KINDS:
            kind = asset['kind']
        if tags is None:
            tags = asset.get('tags')
        provenance['asset_id'] = aid
    elif export_id == 'source':
        path = owned_file(app, pid, 'input.mp4')
        name = args.get('name') or doc['name']
        provenance['export_id'] = 'source'
        kind = kind or 'clip'
    else:
        identifier(export_id, 'export')
        output = timeline.completed_export(doc, export_id)
        if not output:
            # Legacy approval renderer persists completed versions in project.json.
            legacy = app.project(pid)
            version = next((v for v in legacy.get('versions', []) if v.get('id') == export_id), None)
            if version is None:
                raise ValueError('Choose a completed saved export.')
            output = version
        path = owned_file(app, pid, 'versions/'+export_id+'/edited.mp4')
        name = args.get('name') or doc['name']+' render'
        provenance.update(export_id=export_id, timeline_version=output.get('timeline_version'))
        kind = kind or 'render'
    metadata = args.get('metadata', {})
    if not isinstance(metadata, dict):
        raise ValueError('Metadata must be an object.')
    scope = args.get('scope', 'shared')
    if scope not in ('shared', 'project'):
        raise ValueError('Scope must be shared or project.')
    return library.register_file(app, path, name=name, kind=kind, tags=tags,
        metadata={**metadata, 'provenance': provenance}, project_id=pid if scope == 'project' else None)



def index_project_assets(app, args):
    """Explicit bounded backfill; project files remain unchanged and errors stay visible."""
    pid = args.get('project_id')
    include_source = args.get('include_source', False)
    include_renders = args.get('include_renders', True)
    limit = args.get('limit', 50)
    if type(include_source) is not bool or type(include_renders) is not bool:
        raise ValueError('include_source and include_renders must be booleans.')
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('Index limit must be an integer between 1 and 200.')
    doc = project(app, pid)
    candidates = []
    seen = set()
    def add(key, value):
        identity = (key, str(value))
        if identity not in seen:
            seen.add(identity)
            candidates.append({key: value})
    for asset in doc.get('assets', []):
        add('asset_id', asset.get('id'))
    if include_source:
        add('export_id', 'source')
    if include_renders:
        for export in doc.get('exports', []):
            if export.get('status') == 'done':
                add('export_id', export.get('id'))
        for version in app.project(pid).get('versions', []):
            add('export_id', version.get('id'))
    assets, errors = [], []
    for source in candidates[:limit]:
        try:
            assets.append(save_project_asset(app, {'project_id':pid, 'scope':'project', **source}))
        except Exception as exc:
            errors.append({**source, 'error':str(exc)[-600:]})
    return {'assets':assets, 'errors':errors, 'truncated':len(candidates) > limit,
            'candidates_count':len(candidates)}


def execute(app, operation, args):
    if operation == 'index_project_assets':
        return index_project_assets(app, args)
    if operation == 'create_video_from_library':
        import quick_asset_sequence
        return quick_asset_sequence.create_video_from_library(app, args.get('items'),
            name=args.get('name', 'Library video'), style_id=args.get('style_id'))
    if operation in ('plan_asset_assembly', 'apply_asset_assembly'):
        import quick_asset_assembly
        fn = quick_asset_assembly.plan_assembly if operation == 'plan_asset_assembly' else quick_asset_assembly.apply_assembly
        return fn(app, args.get('project_id'), args.get('expected_version'), args.get('items', []),
            style_id=args.get('style_id'), template_id=args.get('template_id'))
    if operation == 'save_library_asset':
        return {'asset': save_project_asset(app, args)}
    if operation == 'save_library_recipe':
        pid = args.get('project_id')
        if pid is not None:
            project(app, pid)
        return {'asset': library.save_recipe(app, name=args.get('name'), kind=args.get('kind'),
            recipe=args.get('recipe'), tags=args.get('tags'), project_id=pid)}
    if operation == 'search_asset_library':
        pid = args.get('project_id')
        if pid is not None:
            project(app, pid)
        return {'assets': library.search(app, query=args.get('query', ''), kind=args.get('kind'),
            tags=args.get('tags'), project_id=pid, limit=args.get('limit', 50))}
    if operation == 'get_library_asset':
        return {'asset': accessible(app, args.get('library_asset_id'), args.get('project_id'))}
    if operation == 'attach_library_asset':
        accessible(app, args.get('library_asset_id'), args.get('project_id'))
        return library.attach(app, args['library_asset_id'], args['project_id'], args.get('expected_version'))
    raise ValueError('Unknown asset library operation.')


def route(handler, app, method):
    parsed = urlparse(handler.path)
    if parsed.path != '/api/quick/library':
        return False
    try:
        if method == 'POST':
            size = int(handler.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024*1024:
                raise ValueError('Library request must be 1 byte to 1 MiB.')
            args = json.loads(handler.rfile.read(size))
            if not isinstance(args, dict):
                raise ValueError('Library request must be an object.')
            result = execute(app, args.get('operation'), args)
        elif method == 'GET':
            query = parse_qs(parsed.query)
            args = {k: v[-1] for k, v in query.items()}
            if 'limit' in args:
                args['limit'] = int(args['limit'])
            if 'tags' in query:
                args['tags'] = query['tags']
            result = execute(app, 'get_library_asset' if 'library_asset_id' in args else 'search_asset_library', args)
        else:
            raise ValueError('Unsupported asset library request.')
        handler.json(200, result)
    except timeline.Conflict as exc:
        handler.json(409, {'error': str(exc)})
    except (ValueError, TypeError, KeyError, FileNotFoundError) as exc:
        handler.json(400, {'error': str(exc)})
    return True
