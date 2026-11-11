"""Durable local asset library; immutable blobs and SQLite indexed descriptions.

Shared records have project_id=None. Project searches include shared records plus
that project's private records. Nothing is fetched from the network by this module.
"""
import contextlib
import hashlib
import fcntl
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import uuid

KINDS = ('clip', 'audio', 'sound_effect', 'image', 'render', 'style', 'template', 'document')
RECIPE_KINDS = ('style', 'template')
ID = r'[a-f0-9]{32}'


def _identifier(value, label='Asset'):
    if not isinstance(value, str) or not re.fullmatch(ID, value):
        raise ValueError(label + ' identifier must be 32 lowercase hexadecimal characters.')
    return value


def _project(value):
    return None if value is None else _identifier(value, 'Project')


def _json(value, label, limit=262144):
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError(label + ' must be finite JSON.') from None
    if len(result.encode()) > limit:
        raise ValueError(label + ' is too large.')
    return result


def _description(name, kind, tags, metadata):
    if not isinstance(name, str) or not name.strip() or len(name) > 180 or '\x00' in name:
        raise ValueError('Asset name must contain 1–180 characters.')
    name = name.replace('\\', '/').split('/')[-1].strip()
    if name in ('', '.', '..'):
        raise ValueError('Supply a usable asset name.')
    if kind not in KINDS:
        raise ValueError('Choose a supported asset kind.')
    if tags is None:
        tags = []
    if not isinstance(tags, list) or len(tags) > 64 or any(not isinstance(t, str) or not t.strip() or len(t) > 80 for t in tags):
        raise ValueError('Use up to 64 nonempty tags of at most 80 characters.')
    tags = sorted(set(t.strip().lower() for t in tags))
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError('Asset metadata must be an object.')
    return name, kind, tags, json.loads(_json(metadata, 'Metadata'))


def _root(app):
    base = Path(app.WORK).resolve()
    root = base / '.asset-library'
    if root.is_symlink():
        raise ValueError('Library root cannot be a symbolic link.')
    root.mkdir(parents=True, exist_ok=True)
    if root.resolve().parent != base:
        raise ValueError('Invalid library root.')
    blobs = root / 'blobs'
    if blobs.is_symlink():
        raise ValueError('Library blobs cannot be symbolic links.')
    blobs.mkdir(exist_ok=True)
    return root


@contextlib.contextmanager
def _db(app):
    root = _root(app)
    path = root / 'catalog.sqlite3'
    if path.is_symlink():
        raise ValueError('Library catalog cannot be a symbolic link.')
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute('PRAGMA busy_timeout=30000')
        con.execute('PRAGMA synchronous=FULL')
        con.execute('''CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
            project_id TEXT, name TEXT NOT NULL, kind TEXT NOT NULL,
            tags TEXT NOT NULL, metadata TEXT NOT NULL, recipe TEXT,
            sha256 TEXT NOT NULL, size INTEGER NOT NULL, mime_type TEXT NOT NULL,
            created_at REAL NOT NULL)''')
        con.execute('CREATE INDEX IF NOT EXISTS assets_scope_kind ON assets(project_id,kind)')
        yield con
        con.commit()
    finally:
        con.close()


def _record(row):
    result = dict(row)
    result.pop('fingerprint', None)
    for key in ('tags', 'metadata', 'recipe'):
        if result[key] is not None:
            result[key] = json.loads(result[key])
    result['scope'] = 'shared' if result['project_id'] is None else 'project'
    return result


def _digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _sync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _blob(app, digest):
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('Invalid library blob digest.')
    path = _root(app) / 'blobs' / digest
    if path.is_symlink() or not path.is_file():
        raise ValueError('Library asset bytes are unavailable.')
    if _digest(path) != digest:
        raise ValueError('Library asset integrity check failed.')
    return path


def _insert(app, *, name, kind, tags, metadata, project_id, digest, size, mime_type, recipe=None):
    values = dict(project_id=project_id, name=name, kind=kind, tags=tags, metadata=metadata,
                  recipe=recipe, sha256=digest, size=size, mime_type=mime_type)
    fingerprint = hashlib.sha256(_json(values, 'Asset').encode()).hexdigest()
    with _db(app) as con:
        con.execute('INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (uuid.uuid4().hex, fingerprint, project_id, name, kind, _json(tags, 'Tags'),
                     _json(metadata, 'Metadata'), _json(recipe, 'Recipe') if recipe is not None else None,
                     digest, size, mime_type, time.time()))
        return _record(con.execute('SELECT * FROM assets WHERE fingerprint=?', (fingerprint,)).fetchone())


def register_file(app, source_path, *, name=None, kind=None, tags=None, metadata=None, project_id=None):
    """Copy a file before publishing metadata; same content/description is idempotent."""
    project_id = _project(project_id)
    if not isinstance(source_path, (str, Path)) or not Path(source_path).is_absolute():
        raise ValueError('Supply an absolute local source path.')
    source = Path(source_path)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Source must be a regular local file, not a symbolic link.')
    if name is not None and not isinstance(name, str):
        raise ValueError('Asset name must be a string.')
    mime_type = mimetypes.guess_type(name or source.name)[0] or 'application/octet-stream'
    if kind is None:
        kind = {'video': 'clip', 'audio': 'audio', 'image': 'image'}.get(mime_type.split('/')[0], 'document')
    if kind in RECIPE_KINDS:
        raise ValueError('Use save_recipe for styles and templates.')
    name, kind, tags, metadata = _description(name or source.name, kind, tags, metadata)
    root = _root(app)
    fd, temporary = tempfile.mkstemp(prefix='.upload-', dir=root / 'blobs')
    temporary = Path(temporary)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as incoming:
            for chunk in iter(lambda: incoming.read(1024 * 1024), b''):
                size += len(chunk)
                if size > getattr(app, 'MAX_UPLOAD', 700 * 1024 * 1024):
                    raise ValueError('Asset exceeds the upload size limit.')
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if not size:
            raise ValueError('Asset must not be empty.')
        hexdigest = digest.hexdigest()
        target = root / 'blobs' / hexdigest
        try:
            os.link(temporary, target)  # atomic publication, never overwrite a blob
            _sync_dir(target.parent)
        except FileExistsError:
            _blob(app, hexdigest)
        return _insert(app, name=name, kind=kind, tags=tags, metadata=metadata,
                       project_id=project_id, digest=hexdigest, size=size, mime_type=mime_type)
    finally:
        temporary.unlink(missing_ok=True)


def save_recipe(app, *, name, kind, recipe, tags=None, project_id=None):
    if kind not in RECIPE_KINDS or not isinstance(recipe, dict):
        raise ValueError('A style or template requires a JSON recipe object.')
    name, kind, tags, metadata = _description(name, kind, tags, {})
    encoded = _json(recipe, 'Recipe').encode()
    return _insert(app, name=name, kind=kind, tags=tags, metadata=metadata,
                   project_id=_project(project_id), digest=hashlib.sha256(encoded).hexdigest(),
                   size=len(encoded), mime_type='application/json', recipe=json.loads(encoded))


def get(app, asset_id):
    with _db(app) as con:
        row = con.execute('SELECT * FROM assets WHERE id=?', (_identifier(asset_id),)).fetchone()
        if row is None:
            raise ValueError('Library asset not found.')
        return _record(row)


def resolve(app, asset_id):
    record = get(app, asset_id)
    if record['kind'] in RECIPE_KINDS:
        raise ValueError('This asset is a recipe; use its recipe field.')
    return _blob(app, record['sha256'])


def search(app, *, query='', kind=None, tags=None, project_id=None, limit=50):
    project_id = _project(project_id)
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('Search query must contain at most 500 characters.')
    if kind is not None and kind not in KINDS:
        raise ValueError('Choose a supported asset kind.')
    _, _, tags, _ = _description('search', kind or 'document', tags, {})
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError('Search limit must be between 1 and 200.')
    sql = 'SELECT * FROM assets WHERE (project_id IS NULL OR project_id=?)'
    params = [project_id]
    if kind:
        sql += ' AND kind=?'
        params.append(kind)
    with _db(app) as con:
        records = [_record(r) for r in con.execute(sql + ' ORDER BY created_at DESC,id', params)]
    terms = query.lower().split()
    found = []
    for record in records:
        text = ' '.join([record['name'], record['kind'], *record['tags'], _json(record['metadata'], 'Metadata')]).lower()
        if all(t in text for t in terms) and set(tags).issubset(record['tags']):
            found.append(record)
            if len(found) >= limit:
                break
    return found


@contextlib.contextmanager
def mutation_lock(app, project_id):
    """Serialize library/assembly mutations in the server and across workers.

    Existing editor commands use timeline.LOCK; the runtime owns its store lock.
    Offline tools must not bypass that runtime by editing the same store directly.
    """
    import quick_timeline as timeline
    project_id = _identifier(project_id, 'Project')
    base = Path(app.WORK).resolve()
    project = base / project_id
    if project.is_symlink() or not project.is_dir() or project.resolve().parent != base:
        raise ValueError('Invalid project storage directory.')
    lock = project / '.library-mutation.lock'
    if lock.is_symlink():
        raise ValueError('Invalid project mutation lock.')
    with timeline.LOCK:
        with lock.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def attach(app, asset_id, project_id, expected_version):
    """Materialize durable independent project bytes with optimistic versioning."""
    import quick_timeline as timeline
    project_id = _identifier(project_id, 'Project')
    if type(expected_version) is not int:
        raise ValueError('Supply the current integer timeline version.')
    record = get(app, asset_id)
    if record['project_id'] not in (None, project_id):
        raise ValueError('This asset belongs to a different project.')
    source = resolve(app, asset_id)
    with mutation_lock(app, project_id):
        doc = timeline.load(app, project_id)
        if doc['version'] != expected_version:
            raise timeline.Conflict('Timeline changed; read the current version and retry.')
        existing = next((a for a in doc.get('assets', []) if a.get('sha256') == record['sha256']), None)
        if existing:
            import quick_studio
            _, existing_path = quick_studio.asset_path(app, project_id, doc, existing['id'])
            if _digest(existing_path) != record['sha256']:
                raise ValueError('Existing project asset integrity check failed.')
            result = timeline.public(doc)
            result.update(attached_asset_id=existing['id'], library_asset_id=asset_id, asset_reused=True)
            return result
        project = Path(app.WORK).resolve() / project_id
        if project.is_symlink() or project.resolve().parent != Path(app.WORK).resolve():
            raise ValueError('Invalid project storage directory.')
        assets = project / 'assets'
        if assets.is_symlink():
            raise ValueError('Project assets cannot be symbolic links.')
        aid = uuid.uuid4().hex
        folder = assets / aid
        folder.mkdir(parents=True)
        target = folder / record['name']
        # Keep bytes if the metadata commit has an uncertain outcome, as upload does.
        committed = False
        try:
            with source.open('rb') as incoming, target.open('xb') as output:
                shutil.copyfileobj(incoming, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            if _digest(target) != record['sha256']:
                raise ValueError('Library asset changed during attachment.')
            _sync_dir(folder)
            _sync_dir(assets)
            asset = {key: record[key] for key in ('name', 'size', 'sha256', 'mime_type', 'created_at')}
            asset.update(id=aid, library_asset_id=asset_id, kind=record['kind'], tags=record['tags'],
                         path='assets/' + aid + '/' + record['name'],
                         url='/api/quick/projects/' + project_id + '/assets/' + aid + '/download')
            doc.setdefault('assets', []).append(asset)
            doc['version'] += 1
            committed = True
            timeline.write(project / 'timeline.json', doc)
        except Exception:
            if not committed:
                shutil.rmtree(folder, ignore_errors=True)
            raise
        result = timeline.public(doc)
        result.update(attached_asset_id=aid, library_asset_id=asset_id, asset_reused=False)
        return result
