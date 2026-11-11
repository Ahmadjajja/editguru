"""Make a verified revised export the source of the next editing round."""
import hashlib
import copy
import shutil
import time
import uuid
from pathlib import Path

import quick_timeline as timeline


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def eligible(doc):
    pointer = doc.get('next_revision') or {}
    return (pointer.get('source_version') == doc.get('version')
            and not any(n.get('included') is not False and n.get('status') not in ('applied', 'done', 'removed')
                        for n in doc.get('notes', [])))


def ensure(app, doc):
    """Idempotent, scoped import. Never replace source pixels or copy old anchors."""
    if any(n.get('included') is not False and n.get('status') not in ('applied', 'done', 'removed')
           for n in doc.get('notes', [])):
        return
    last = (doc.get('accepted_edits') or [{}])[-1]
    if last.get('operation') != 'record_revision_result':
        return  # A newer manual edit must not be replaced with an older export.
    result = last['arguments']['result']
    target = timeline.load(app, result['project_id'])
    exported = timeline.completed_export(target, result['export_id'])
    if not exported or exported.get('section_id') or exported.get('status') != 'done':
        raise ValueError('The revised full-video export is unavailable.')
    source = app.WORK / target['project_id'] / 'versions' / result['export_id'] / 'edited.mp4'
    digest = file_digest(source)
    if digest != result['sha256']:
        raise ValueError('The revised export changed after verification. Export and verify again.')
    pid = uuid.uuid5(uuid.NAMESPACE_URL, 'frame:revision:'+doc['project_id']+':'+result['export_id']+':'+digest).hex
    folder = app.WORK / pid
    folder.mkdir(exist_ok=True)
    media = folder / 'input.mp4'
    if not media.exists():
        temporary = folder / 'input.importing'
        shutil.copyfile(source, temporary)
        if file_digest(temporary) != digest:
            raise ValueError('Could not verify the revised copy import.')
        temporary.replace(media)
    elif file_digest(media) != digest:
        raise ValueError('The saved revised copy does not match its verified export.')
    if not (folder / 'project.json').exists():
        timeline.write(folder / 'project.json', {
            'id': pid, 'name': Path(doc['name']).stem+' · Revised.mp4', 'created': time.time(),
            'versions': [], 'history': [], 'current_segments': None, 'current_version': None})
    child = timeline.load(app, pid)
    parent = {'project_id': doc['project_id'], 'source_version': doc['version'],
              'result_project_id': target['project_id'], 'export_id': result['export_id'], 'sha256': digest}
    if not child.get('revision_parent'):
        child['revision_parent'] = parent
        if doc.get('work_project'):
            child['work_project'] = {**copy.deepcopy(doc['work_project']), 'role':'cut', 'label':'Revised cut'}
        # References remain reusable; old source-anchored pins/notes stay in the parent.
        if doc.get('video_references'):
            child['video_references'] = doc['video_references']
        timeline.write(folder / 'timeline.json', child)
        timeline.activity(app, pid, 'revision_import', 'Revised video imported. Ready for the next revision; previous project and annotations are preserved.', 'done')
    doc['next_revision'] = {'project_id': pid, 'source_version': doc['version'],
                            'export_id': result['export_id'], 'sha256': digest}


def resolve(doc, get_project):
    """Follow only an explicit verified lineage, never project-library recency."""
    seen = set()
    while eligible(doc) and (doc.get('next_revision') or {}).get('project_id'):
        if doc['project_id'] in seen:
            raise ValueError('Invalid revision continuation loop.')
        seen.add(doc['project_id'])
        pointer = doc['next_revision']
        child = get_project(pointer['project_id'])
        parent = child.get('revision_parent') or {}
        if (parent.get('project_id') != doc['project_id'] or parent.get('sha256') != pointer['sha256']
                or parent.get('export_id') != pointer['export_id']):
            raise ValueError('Revised copy does not match this project.')
        doc = child
    return doc
