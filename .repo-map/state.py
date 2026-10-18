#!/usr/bin/env python3
"""Read/publish only the dedicated repo-map branch; never push application branches."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse

BRANCH = 'repo-map'


def git(directory, *args, env=None, allowed=(0,)):
    result = subprocess.run(['git', '-C', str(directory), *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode not in allowed:
        raise ValueError(f'Git {args[0]} failed; check repository access, branch protection, or a concurrent update. No force push was attempted.')
    return result


def remote_url(repo):
    url = git(repo, 'remote', 'get-url', 'origin').stdout.decode().strip()
    if '://' in url:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Origin must be HTTPS without embedded credentials')
    elif not url.startswith('git@'):
        # Local paths are permitted only for offline integration tests.
        if not Path(url).is_absolute() or os.environ.get('REPO_MAP_LOCAL_TEST') != '1':
            raise ValueError('Use an HTTPS or SSH GitHub origin')
    return url


def environment(url):
    env = os.environ.copy()
    token = env.pop('GH_TOKEN', '')
    env.pop('LLM_API_KEY', None)
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, GIT_TERMINAL_PROMPT='0')
    if token:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https':
            raise ValueError('GitHub token authentication requires an HTTPS origin')
        auth = base64.b64encode(('x-access-token:' + token).encode()).decode()
        env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0=f'http.{parsed.scheme}://{parsed.netloc}/.extraheader',
                   GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + auth)
    return env


def prepare(repo, state):
    if state.exists() and any(state.iterdir()):
        raise ValueError('State destination must be empty')
    if state.resolve().is_relative_to(repo.resolve()):
        raise ValueError('State checkout must be outside the source repository')
    url = remote_url(repo)
    env = environment(url)
    state.mkdir(parents=True, exist_ok=True)
    git(state, 'init', '--quiet', '--initial-branch=' + BRANCH, env=env)
    git(state, 'remote', 'add', 'origin', url, env=env)
    exists = git(state, 'ls-remote', '--exit-code', '--heads', 'origin', 'refs/heads/' + BRANCH, env=env, allowed=(0, 2))
    if exists.returncode == 0:
        git(state, 'fetch', '--quiet', '--depth=1', '--no-tags', 'origin', 'refs/heads/' + BRANCH, env=env)
        git(state, 'checkout', '--quiet', '-B', BRANCH, 'FETCH_HEAD', env=env)
        manifest = state / 'manifest.json'
        if manifest.is_symlink() or not manifest.is_file() or json.loads(manifest.read_text()).get('generator') != 'repo-map-pipeline':
            raise ValueError('Existing repo-map branch is not managed by this pipeline; refusing to overwrite it')
    print('Dedicated map checkout ready. No source branch was changed.')


def publish(repo, state):
    manifest = state / 'manifest.json'
    if manifest.is_symlink() or not manifest.is_file() or json.loads(manifest.read_text()).get('generator') != 'repo-map-pipeline':
        raise ValueError('Missing managed map manifest; nothing was published')
    if git(state, 'branch', '--show-current').stdout.decode().strip() != BRANCH:
        raise ValueError('Refusing to publish a branch other than repo-map')
    allowed = {'README.md', 'manifest.json', 'update.json', 'maps', 'overview', '.git'}
    if any(p.name not in allowed for p in state.iterdir()):
        raise ValueError('Unexpected files in map checkout; nothing was staged')
    if any(p.is_symlink() for p in state.rglob('*') if '.git' not in p.relative_to(state).parts):
        raise ValueError('Symlinks are not publishable map content')
    url = remote_url(repo)
    if git(state, 'remote', 'get-url', 'origin').stdout.decode().strip() != url:
        raise ValueError('Source and map checkouts must use the same origin')
    env = environment(url)
    source_branch = os.environ.get('REPO_MAP_SOURCE_BRANCH', '')
    if source_branch:
        head = git(state, 'ls-remote', '--exit-code', '--heads', 'origin', 'refs/heads/' + source_branch, env=env).stdout.decode().split()[0]
        if json.loads(manifest.read_text()).get('source_revision') != head:
            print('Source branch advanced; skipped publishing an older snapshot. A queued update can catch up.')
            return
    git(state, 'config', 'user.name', 'github-actions[bot]', env=env)
    git(state, 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com', env=env)
    git(state, 'add', '--all', '--', 'README.md', 'manifest.json', 'update.json', 'maps', 'overview', env=env)
    if git(state, 'diff', '--cached', '--quiet', env=env, allowed=(0, 1)).returncode == 0:
        print('No map changes to publish.')
        return
    git(state, 'commit', '--quiet', '-m', 'Update repository maps [skip ci]', env=env)
    git(state, 'push', '--quiet', 'origin', 'HEAD:refs/heads/' + BRANCH, env=env)
    print('Published updated maps to repo-map. Source branches unchanged.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'publish'])
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    try:
        (prepare if args.operation == 'prepare' else publish)(args.repo.resolve(), args.state.resolve())
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f'Map branch operation failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
