#!/usr/bin/env python3
"""Protect the approved work while another agent tests FRAME.

    python3 work/frame-product/tests/frame_test_guard.py snapshot   # before testing
    python3 work/frame-product/tests/frame_test_guard.py verify     # after testing: lists anything that changed

Protected: the approved Fable project (every file), the Fable kit and media kit, saved styles, the ChatGPT Mastery
recipe, and the tracked source tree (git status must not gain changes). Snapshots go to ~/frame-test-runs/guard.json.
Exit code 0 = nothing protected changed, 1 = something did (the report says what).
"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRODUCT = REPO / 'work' / 'frame-product'
FABLE = PRODUCT / 'jobs' / '8ba3cd4acef0484dbb2a2d9a6927abe4'
PROTECTED = [FABLE, REPO / 'recipes' / 'fable-52-higgsfield-mcp', REPO / 'recipes' / '_styles', REPO / 'recipes' / 'chatgpt-mastery-9x16']
OUT = Path.home() / 'frame-test-runs' / 'guard.json'
BIG = 64 * 1024 * 1024


def fingerprint(f):
    st = f.stat()
    if st.st_size > BIG:                       # huge media: size + mtime is enough to see a rewrite
        return 'size:%d mtime:%d' % (st.st_size, int(st.st_mtime))
    h = hashlib.sha256()
    with f.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def scan():
    files = {}
    for root in PROTECTED:
        if root.is_file():
            files[str(root.relative_to(REPO))] = fingerprint(root)
        elif root.is_dir():
            for f in sorted(root.rglob('*')):
                if f.is_file() and '__pycache__' not in f.parts and f.name != '.DS_Store':
                    files[str(f.relative_to(REPO))] = fingerprint(f)
    git = subprocess.run(['git', '-C', str(REPO), 'status', '--porcelain'], capture_output=True, text=True).stdout.splitlines()
    head = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    branch = subprocess.run(['git', '-C', str(REPO), 'branch', '--show-current'], capture_output=True, text=True).stdout.strip()
    return {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': files, 'git_status': sorted(git), 'head': head, 'branch': branch}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'snapshot':
        OUT.parent.mkdir(parents=True, exist_ok=True)
        snap = scan()
        OUT.write_text(json.dumps(snap, indent=1))
        print('Snapshot of %d protected files, git HEAD %s on %s, %d pre-existing uncommitted entries -> %s'
              % (len(snap['files']), snap['head'][:7], snap['branch'], len(snap['git_status']), OUT))
        return 0
    if cmd == 'verify':
        if not OUT.exists():
            print('No snapshot. Run "snapshot" before testing.'); return 2
        old, new = json.loads(OUT.read_text()), scan()
        changed = sorted(k for k in old['files'] if k in new['files'] and old['files'][k] != new['files'][k])
        gone = sorted(k for k in old['files'] if k not in new['files'])
        added = sorted(k for k in new['files'] if k not in old['files'] and not Path(k).name.startswith('codex-'))   # test styles are allowed
        git_new = sorted(set(new['git_status']) - set(old['git_status']))
        git_gone = sorted(set(old['git_status']) - set(new['git_status']))
        problems = changed or gone or added or git_new or git_gone or old['head'] != new['head'] or old['branch'] != new['branch']
        print('Protected files: %d checked, %d changed, %d deleted, %d added' % (len(old['files']), len(changed), len(gone), len(added)))
        for label, xs in (('CHANGED', changed), ('DELETED', gone), ('ADDED', added), ('NEW UNCOMMITTED', git_new), ('UNCOMMITTED CHANGE REVERTED/COMMITTED', git_gone)):
            for x in xs:
                print('  %s  %s' % (label, x))
        if old['head'] != new['head'] or old['branch'] != new['branch']:
            print('  GIT HEAD/BRANCH MOVED: %s %s -> %s %s' % (old['branch'], old['head'][:7], new['branch'], new['head'][:7]))
        print('RESULT:', 'FAIL - protected work changed' if problems else 'PASS - nothing protected changed')
        return 1 if problems else 0
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main())
