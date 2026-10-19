#!/usr/bin/env python3
"""Persist separate JSON subsystem maps; update affected maps and reuse unchanged views."""
import argparse
import copy
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import generate as base

GENERATOR = 'repo-map-pipeline'
SCHEMA = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def safe_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[a-z][a-z0-9-]{0,47}', value))


def read_manifest(state):
    manifest = state / 'manifest.json'
    if manifest.is_symlink():
        raise base.MapError('Symlinked state manifest is not allowed')
    if not manifest.exists():
        if state.exists() and any(p.name != '.git' for p in state.iterdir()):
            raise base.MapError('Existing state has no recognized manifest; refusing to overwrite it')
        return None
    data = json.loads(manifest.read_text())
    if data.get('generator') != GENERATOR or data.get('schema_version') != SCHEMA:
        raise base.MapError('Unknown state schema; migrate it explicitly instead of overwriting')
    if not isinstance(data.get('maps'), dict) or any(not safe_id(mid) for mid in data['maps']):
        raise base.MapError('Invalid map IDs in saved state')
    if not re.fullmatch(r'[0-9a-f]{40,64}', data.get('source_revision', '')):
        raise base.MapError('Invalid saved source revision')
    for mid in data['maps']:
        target = state / 'maps' / mid
        if target.is_symlink() or not target.resolve().is_relative_to(state.resolve()):
            raise base.MapError('Symlinked or external saved map path')
    if any(p.is_symlink() for p in state.rglob('*') if '.git' not in p.relative_to(state).parts):
        raise base.MapError('Symlinks are not allowed in saved map content')
    return data


def load_config(path):
    config = base.load_config(path)
    config.setdefault('maps', {})
    config.setdefault('max_total_calls', 24)
    config.setdefault('full_refresh_after_updates', 20)
    if not isinstance(config['maps'], dict) or len(config['maps']) > 12:
        raise base.MapError('maps must be an object with at most 12 subsystem definitions')
    if type(config['max_total_calls']) is not int or not 2 <= config['max_total_calls'] <= 100:
        raise base.MapError('max_total_calls must be between 2 and 100')
    if type(config['full_refresh_after_updates']) is not int or not 1 <= config['full_refresh_after_updates'] <= 1000:
        raise base.MapError('full_refresh_after_updates must be between 1 and 1000')
    for mid, spec in config['maps'].items():
        if not safe_id(mid) or not isinstance(spec, dict):
            raise base.MapError('Use safe lowercase map IDs and object definitions')
        for key in ('include', 'depends_on'):
            if not isinstance(spec.get(key, []), list) or any(not isinstance(p, str) for p in spec.get(key, [])):
                raise base.MapError('Map include/depends_on must be lists of strings')
        if not spec.get('include') or any(d not in config['maps'] or d == mid for d in spec.get('depends_on', [])):
            raise base.MapError('Map needs include globs and dependencies referencing other configured maps')
    return config


def inventory(repo, config):
    files, skipped = {}, []
    names = [p.decode('utf-8', 'strict') for p in base.git(repo, 'ls-files', '-z').split(b'\0') if p]
    for name in names:
        if not base.eligible(name, config):
            continue
        path = repo / name
        if path.is_symlink() or not path.resolve().is_relative_to(repo) or not path.is_file():
            skipped.append(name)
            continue
        # Hash every eligible file for invalidation, even if analysis excerpts are capped.
        h = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(65536), b''):
                h.update(block)
        files[name] = h.hexdigest()
    return files, skipped


def infer_dependencies(repo, files, owners):
    """Conservative hints for resolvable JS/Python imports. Explicit config fills gaps."""
    result = {mid: set() for mids in owners.values() for mid in mids}
    for name in files:
        path = repo / name
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeError:
            continue
        imports = re.findall(r'''(?:from\s+|(?:import|require)\s*\(?\s*)["']([^"']+)["']''', text)
        targets = set()
        for value in imports:
            if value.startswith('.'):
                stem = posixpath.normpath(posixpath.join(posixpath.dirname(name), value))
                targets.update([stem, *(stem + ext for ext in ('.js', '.jsx', '.ts', '.tsx', '.mjs', '.py')),
                                *(stem + '/index' + ext for ext in ('.js', '.ts', '.tsx'))])
        if name.endswith('.py'):
            for value in re.findall(r'^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)', text, re.M):
                stem = value.replace('.', '/')
                targets.update([stem + '.py', stem + '/__init__.py'])
        for target in targets & files.keys():
            for owner in owners[name]:
                result[owner].update(set(owners[target]) - {owner})
    return result


def map_specs(repo, config, files):
    specs, owners = {}, {name: [] for name in files}
    if config['maps']:
        for mid, spec in sorted(config['maps'].items()):
            selected = sorted(name for name in files if any(fnmatch.fnmatchcase(name, p) for p in spec['include']))
            if selected:
                specs[mid] = {'files': selected, 'depends_on': list(spec.get('depends_on', []))}
                for name in selected:
                    owners[name].append(mid)
    else:
        for name in sorted(files):
            parts = PurePosixPath(name).parts
            if len(parts) == 1 or parts[0].startswith('.') or parts[0] in {'docs', 'test', 'tests'}:
                mid = 'core'
            elif parts[0] in {'apps', 'packages', 'services'} and len(parts) > 2:
                mid = parts[0] + '-' + parts[1]
            elif parts[0] == 'src' and len(parts) > 2:
                mid = 'src-' + parts[1]
            else:
                mid = parts[0]
            mid = re.sub('[^a-z0-9-]', '-', mid.lower()).strip('-')[:48]
            if not mid or not mid[0].isalpha():
                mid = ('map-' + mid)[:48]
            specs.setdefault(mid, {'files': [], 'depends_on': []})['files'].append(name)
            owners[name].append(mid)
    if not specs:
        raise base.MapError('No subsystem contains eligible tracked files; review map scopes')
    if len(specs) > 12:
        raise base.MapError('Automatic discovery found over 12 maps; configure broader subsystem groups')
    inferred = infer_dependencies(repo, files, owners)
    for mid, spec in specs.items():
        spec['depends_on'] = sorted((set(spec['depends_on']) | inferred.get(mid, set())) & specs.keys())
    return specs, sorted(name for name, mids in owners.items() if not mids)


def fingerprint(config):
    here = Path(__file__).resolve().parent
    return digest({'config': config,
                   'code': [(here / n).read_text() for n in ('generate.py', 'incremental.py')],
                   'model': os.environ.get('LLM_MODEL', 'deepseek-v4.1-flash'),
                   'endpoint': os.environ.get('LLM_BASE_URL', 'https://api.kymaapi.com/v1')})


def map_outputs_exist(directory):
    if not all((directory / name).is_file() for name in ('map.json', 'README.md', 'repository-map.pdf', 'coverage.json')):
        return False
    data = json.loads((directory / 'map.json').read_text())
    return all((directory / f'diagram-{i:02}.{ext}').is_file()
               for i in range(1, len(data['map']['diagrams']) + 1) for ext in ('png', 'mmd'))


def plan(repo, state, config, force=False):
    old = read_manifest(state)
    revision = base.git(repo, 'rev-parse', 'HEAD').decode().strip()
    if old and old['source_revision'] != revision:
        # Concurrency does not promise chronological execution; never regress state.
        known = subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', old['source_revision'] + '^{commit}'], capture_output=True).returncode == 0
        if known and subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', revision, old['source_revision']], capture_output=True).returncode == 0:
            return {'stale': True, 'revision': revision}, old
    files, skipped = inventory(repo, config)
    specs, unassigned = map_specs(repo, config, files)
    fp = fingerprint(config)
    full = force or old is None or old.get('fingerprint') != fp or old.get('updates_since_refresh', 0) >= config['full_refresh_after_updates']
    if old and old['source_revision'] != revision:
        ancestral = subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', old['source_revision'], revision], capture_output=True).returncode == 0
        full = full or not ancestral
    previous = old['files'] if old else {}
    changed = {name for name in files.keys() | previous.keys() if files.get(name) != previous.get(name)}
    previous_maps = old['maps'] if old else {}
    removed = set(previous_maps) - specs.keys()
    direct = {mid for mid, spec in specs.items() if mid not in previous_maps or any(name in changed for name in spec['files'])
              or spec['files'] != previous_maps[mid]['files'] or spec['depends_on'] != previous_maps[mid]['depends_on']
              or not map_outputs_exist(state / 'maps' / mid)}
    affected = set(specs) if full else direct | removed
    # Old and new dependency edges cover removed imports/interfaces as well.
    while True:
        expanded = affected | {mid for mid in previous_maps.keys() | specs.keys()
                               if (set(previous_maps.get(mid, {}).get('depends_on', [])) | set(specs.get(mid, {}).get('depends_on', []))) & affected}
        if expanded == affected:
            break
        affected = expanded
    affected &= specs.keys()
    return {'stale': False, 'revision': revision, 'fingerprint': fp, 'files': files, 'maps': specs,
            'affected': sorted(affected), 'removed': sorted(removed), 'changed_files': sorted(changed),
            'full_refresh': bool(full), 'unassigned_files': unassigned, 'skipped_files': skipped}, old


def metadata(repo, revision, client):
    slug = os.environ.get('GITHUB_REPOSITORY', '')
    server = os.environ.get('GITHUB_SERVER_URL', 'https://github.com').rstrip('/')
    return {'revision': revision, 'generated_at': base.dt.datetime.now(base.dt.timezone.utc).isoformat(),
            'model': client.model, 'model_responses': client.served_models,
            'local_changes': bool(base.git(repo, 'status', '--porcelain')),
            'repository_url': f'{server}/{slug}' if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', slug) else None}


def seed_result(path, repo, owned, config):
    data = json.loads(path.read_text())
    sources = data['sources']
    if not sources or not isinstance(sources, dict):
        raise base.MapError('Seed needs nonempty source metadata')
    for source in sources.values():
        if source.get('path') not in owned or not all(type(source.get(k)) is int for k in ('start', 'end')):
            raise base.MapError('Seed source must belong to the map and use integer line ranges')
        lines = (repo / source['path']).read_text().splitlines()
        if not 1 <= source['start'] <= source['end'] <= len(lines):
            raise base.MapError('Seed evidence points outside actual source lines')
        source.pop('text', None)
    findings = data['findings']
    if not isinstance(findings, dict) or not findings:
        raise base.MapError('Seed needs findings')
    for finding in findings.values():
        finding['statement'] = base.short(finding.get('statement'), 'seed finding', 600)
        finding['sources'] = base.refs(finding.get('sources'), sources)
        if type(finding.get('uncertain')) is not bool:
            raise base.MapError('Seed finding needs boolean uncertainty')
    return base.validate_result(data['map'], findings, config), findings, sources


def build_map(repo, target, previous, mid, spec, config, client, revision, changed, seed=None, context=None, rerender=False):
    snippets, coverage = base.scan(repo, config, scope_files=set(spec['files']), priority_files=set(changed))
    before = client.calls if client else 0
    if seed:
        result, findings, sources = seed_result(seed, repo, set(spec['files']), config)
        processed = list(sources)
        coverage['scope'] = 'Locally authored seed; evidence references checked. Source interpretation needs review.'
    else:
        findings, processed = base.analyze(snippets, config, client, context=context)
        result = base.synthesize(findings, config, client, context=context)
        sources = {s['id']: {k: v for k, v in s.items() if k != 'text'} for s in snippets if s['id'] in processed}
    calls = client.calls - before if client else 0
    coverage.update({'analyzed_files': len({s['path'] for s in sources.values()}), 'api_calls': calls,
                     'usage': client.usage[before:] if client else [], 'limits': config,
                     'not_analyzed_due_to_call_budget': [s['path'] for s in snippets if s['id'] not in processed]})
    if seed:
        coverage['not_cited_in_seed'] = sorted(set(spec['files']) - {s['path'] for s in sources.values()})
        coverage['not_analyzed_due_to_call_budget'] = []
        class Local:
            model, served_models = 'local-skill-seed', []
        meta = metadata(repo, revision, Local())
    else:
        meta = metadata(repo, revision, client)
    target.mkdir(parents=True)
    base.write_artifacts(result, findings, sources, coverage, meta, target, reuse_dir=previous if not rerender else None)
    return {'files': spec['files'], 'depends_on': spec['depends_on'], 'source_revision': revision,
            'summary': result['summary'], 'api_calls_last_update': calls}


def overview(specs, entries, source_state, staged_maps):
    """Compose the root overview from subsystem architecture diagrams already analyzed by the model."""
    views = []
    for mid in sorted(entries):
        staged_map = staged_maps / mid / 'map.json'
        saved_map = source_state / 'maps' / mid / 'map.json'
        path = staged_map if staged_map.is_file() else saved_map
        if not path.is_file():
            raise base.MapError(f'Missing generated subsystem map for overview: {mid}')
        saved = json.loads(path.read_text())
        diagrams = saved.get('map', {}).get('diagrams', [])
        if not diagrams:
            raise base.MapError(f'Subsystem map has no architecture diagram: {mid}')
        diagram = copy.deepcopy(diagrams[0])
        diagram['title'] = f'{mid}: {diagram["title"]}'[:100]
        # Evidence IDs are local to each subsystem and are shown in that subsystem's linked page.
        for node in diagram['nodes']:
            node['finding_ids'] = []
        for edge in diagram['edges']:
            edge['finding_ids'] = []
        views.append(diagram)
    return {
        'summary': 'The overview brings together the analyzed architecture view from each subsystem. Open a subsystem map for its source evidence, detailed flows, and uncertainties.',
        'diagrams': views,
        'unknowns': ['Subsystem boundaries and configured or import-inferred dependencies are recorded in manifest.json; they do not establish runtime calls.'],
    }


def write_index(state, specs, entries, revision, source_state, staged_maps, rerender=False):
    result = overview(specs, entries, source_state, staged_maps)
    directory = state / 'overview'
    previous = json.loads((directory / 'map.json').read_text()) if (directory / 'map.json').is_file() else None
    if rerender or previous is None or previous['map'] != result or not map_outputs_exist(directory):
        backup = None
        if directory.exists():
            backup = Path(tempfile.mkdtemp(prefix='repo-map-overview-')) / 'old'
            shutil.move(str(directory), str(backup))
        directory.mkdir(parents=True, exist_ok=True)
        try:
            meta = {'revision': revision, 'generated_at': base.dt.datetime.now(base.dt.timezone.utc).isoformat()}
            coverage = {'scope': 'Source-backed architecture views composed from each subsystem map. See linked subsystem pages for evidence.', 'analyzed_files': 0, 'eligible_files': 0, 'excluded_files': 0, 'api_calls': 0}
            base.write_artifacts(result, {}, {}, coverage, meta, directory, reuse_dir=None if rerender else backup)
        finally:
            if backup:
                shutil.rmtree(backup.parent)
    lines = ['# Repository map', '', f'Source revision: `{revision}`', '',
             'Browse the Mermaid diagrams below on GitHub. PDFs and PNGs are linked for download.', '',
             '[Overview PDF](overview/repository-map.pdf) | [Overview details](overview/README.md)', '']
    for mid, diagram in zip(sorted(entries), result['diagrams']):
        lines += [f'## {diagram["title"]}', '', entries[mid]['summary'], '', diagram['description'], '',
                  '```mermaid', base.mermaid_text(diagram).rstrip(), '```', '', base.diagram_legend(diagram), '',
                  f'[More about this area and its source evidence](maps/{mid}/README.md)', '']
    lines += ['## Subsystem maps', '', '| Map | Summary | Views | Last analyzed source |', '| --- | --- | --- | --- |']
    for mid in sorted(entries):
        entry = entries[mid]
        summary = entry['summary'].replace('|', '/').replace('\n', ' ')
        lines.append(f'| [{mid}](maps/{mid}/README.md) | {summary} | [PDF](maps/{mid}/repository-map.pdf) · [JSON](maps/{mid}/map.json) | `{entry["source_revision"][:12]}` |')
    lines += ['', 'JSON is the source of truth; Mermaid, PNGs, and PDFs are generated views.', '',
              'Unchanged subsystem views are retained. Source existence checks do not prove model interpretation. See manifest.json and update.json for dependencies, coverage and updates.']
    (state / 'README.md').write_text('\n'.join(lines) + '\n')


def update(repo, state, config, force=False, plan_only=False, client=None, seed_dir=None):
    state.mkdir(parents=True, exist_ok=True)
    current, old = plan(repo, state, config, force)
    if current['stale']:
        print('Skipped: this source commit is older than the saved map revision.')
        return current
    if plan_only:
        print(json.dumps(current, indent=2))
        return current
    if old and old['source_revision'] == current['revision'] and not current['full_refresh'] and not current['affected']:
        print('No changes; existing maps are current.')
        return current
    affected = current['affected']
    seeded = seed_dir is not None and old is None
    if seed_dir is not None and old is not None:
        raise base.MapError('Seed is only accepted for an empty state; use incremental updates thereafter')
    if len(affected) * 2 > config['max_total_calls'] and not seeded:
        raise base.MapError('Call budget too small for affected subsystems; increase max_total_calls or use broader groups')
    if affected and not seeded:
        client = client or base.Client(config | {'max_calls': config['max_total_calls']})
    entries = copy.deepcopy(old['maps']) if old else {}
    # Stage all updates outside saved state. Any failure leaves its contents unchanged.
    with tempfile.TemporaryDirectory(prefix='repo-map-stage-') as tmp:
        staged = Path(tmp)
        for index, mid in enumerate(affected):
            spec = current['maps'][mid]
            if seeded:
                seed = seed_dir / 'maps' / mid / 'map.json'
                if not seed.is_file():
                    raise base.MapError(f'Missing local seed for map {mid}')
                budget = config['max_calls']
            else:
                seed = None
                budget = min(config['max_calls'], config['max_total_calls'] - client.calls - 2 * (len(affected) - index - 1))
            context = {'subsystem': mid, 'changed_files': [p for p in current['changed_files'] if p in spec['files']],
                       'dependencies': spec['depends_on'], 'previous_summary': entries.get(mid, {}).get('summary'),
                       'neighbor_summaries': {d: entries[d]['summary'] for d in spec['depends_on'] if d in entries}}
            previous = state / 'maps' / mid
            if (previous / 'map.json').is_file():
                context['previous_map'] = json.loads((previous / 'map.json').read_text())['map']
            print(f'Updating subsystem {mid} ({index + 1}/{len(affected)}); API call budget: {budget}', flush=True)
            try:
                entries[mid] = build_map(repo, staged / mid, previous, mid, spec, config | {'max_calls': budget}, client,
                                         current['revision'], current['changed_files'], seed, context, rerender=current['full_refresh'])
            except base.MapError as error:
                raise base.MapError(f'subsystem {mid}: {error}') from None
        # Stage index/overview as well, so PDF/layout failures cannot advance the manifest.
        staged_state = staged / 'state'
        staged_state.mkdir()
        if (state / 'overview').exists():
            shutil.copytree(state / 'overview', staged_state / 'overview')
        for mid in current['removed']:
            entries.pop(mid, None)
        write_index(staged_state, current['maps'], entries, current['revision'], state, staged,
                    rerender=current['full_refresh'])
        manifest = {'generator': GENERATOR, 'schema_version': SCHEMA, 'source_revision': current['revision'],
                    'fingerprint': current['fingerprint'], 'files': current['files'], 'maps': entries,
                    'updates_since_refresh': 0 if current['full_refresh'] else old['updates_since_refresh'] + bool(affected),
                    'unassigned_files': current['unassigned_files'], 'skipped_files': current['skipped_files']}
        report = {k: current[k] for k in ('revision', 'affected', 'removed', 'changed_files', 'full_refresh', 'unassigned_files', 'skipped_files')}
        report.update({'api_calls': client.calls if client else 0, 'usage': client.usage if client else [], 'seeded_locally': seeded,
                       'dependency_policy': 'Changed maps and all transitive known dependents are rechecked. Unchanged presentations reuse PNG/PDF files.'})
        (staged_state / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (staged_state / 'update.json').write_text(json.dumps(report, indent=2) + '\n')
        (state / 'maps').mkdir(exist_ok=True)
        for mid in affected:
            target = state / 'maps' / mid
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(staged / mid), str(target))
        for mid in current['removed']:
            shutil.rmtree(state / 'maps' / mid, ignore_errors=True)
        if (state / 'overview').exists():
            shutil.rmtree(state / 'overview')
        shutil.move(str(staged_state / 'overview'), str(state / 'overview'))
        for name in ('manifest.json', 'update.json', 'README.md'):
            shutil.copyfile(staged_state / name, state / name)
    print(f'Updated {len(affected)} maps; removed {len(current["removed"])}; API calls: {client.calls if client else 0}.')
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path(__file__).with_name('config.json'))
    parser.add_argument('--full', action='store_true')
    parser.add_argument('--plan', action='store_true', help='Show affected maps without API calls or modifying saved maps')
    parser.add_argument('--seed', type=Path, help='Locally authored maps/<id>/map.json files for first run, without an API key')
    args = parser.parse_args()
    try:
        repo, state = args.repo.resolve(), args.state.resolve()
        if state.is_relative_to(repo):
            raise base.MapError('Use a separate state checkout outside the source repository')
        if base.git(repo, 'status', '--porcelain', '--untracked-files=no'):
            raise base.MapError('Commit or stash source changes before mapping a revision')
        update(repo, state, load_config(args.config), args.full, args.plan, seed_dir=args.seed.resolve() if args.seed else None)
    except (base.MapError, OSError, ValueError, KeyError, TypeError, ImportError, subprocess.CalledProcessError) as error:
        print(f'Incremental map failed: {error if isinstance(error, base.MapError) else type(error).__name__}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
