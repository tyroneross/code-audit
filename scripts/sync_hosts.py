#!/usr/bin/env python3
"""Install or refresh Code Audit in every local agent host, and retire the plugins it replaces.

  sync_hosts.py                    report what would change; exit 1 if anything is pending or blocked
  sync_hosts.py --apply            make the changes (each edited config is backed up first)
  sync_hosts.py --apply --retire   also remove links into the retired code-principles-audit repo

Hosts, each handled only when its home folder exists:
  Claude Code   ~/.claude/settings.json: register this repo as its marketplace and enable the
                plugin (what `claude plugin marketplace add` / `install` record). The `claude`
                CLI is not called. If a new session does not load the plugin, run
                `/plugin marketplace add <repo>` and `/plugin install <plugin>@<marketplace>`.
  Codex         `codex plugin marketplace add` if missing, then `codex plugin add`, which also
                refreshes Codex's cached copy after this repo changes.
  Cursor        ~/.cursor/skills/<skill> links; memory server in ~/.cursor/mcp.json.
  Gemini        memory server in ~/.gemini/settings.json (skills come from ~/.agents/skills).
  Shared        ~/.agents/skills/<skill> links.

Safety: every config is parsed before anything changes, and a file that is not plain JSON, is a
symlink, or changes during the run is left untouched and reported. Writes go through a unique
temporary file. Only symlinks whose targets lie inside this repo's skills (or the retired repo)
are ever removed. Existing memory-server fields other than command and args are preserved.

The repo is the main checkout of the git repository holding this file (never a worktree),
unless --repo is given. Marketplace and plugin names come from .claude-plugin/marketplace.json.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SERVER_NAME = 'code-audit-debugger'
RETIRED_REPOS = ('code-principles-audit',)  # sibling repos whose links --retire removes


class Blocked(Exception):
    pass


def main_checkout(start):
    """The primary working tree for the repo containing `start`, so installs never point at a worktree."""
    out = subprocess.run(['git', '-C', str(start), 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                         capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        return start
    return Path(out.stdout.strip()).parent


def names(repo):
    m = json.loads((repo / '.claude-plugin' / 'marketplace.json').read_text())
    return m['name'], m['plugins'][0]['name']


def skills(repo):
    return sorted(p.parent.name for p in (repo / 'skills').glob('*/SKILL.md'))


def target_of(link):
    """Absolute, normalized target of a symlink, without following further links."""
    raw = os.readlink(link)
    return Path(os.path.normpath(os.path.join(link.parent, raw)))


def inside(path, root):
    try:
        path.relative_to(Path(os.path.normpath(root)))
        return True
    except ValueError:
        return False


def _no_nonfinite(value):
    raise ValueError(f'non-finite number {value}')


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate keys')
    return dict(pairs)


class Config:
    """A JSON config that is read once, checked, and replaced only if unchanged on disk."""

    def __init__(self, path):
        self.path, self.text, self.data, self.error = path, None, {}, None
        if path.is_symlink():
            self.error = 'is a symlink; edit its target by hand'
        elif path.exists():
            self.text = path.read_text()
            try:
                self.data = json.loads(self.text, parse_constant=_no_nonfinite, object_pairs_hook=_no_duplicates)
            except ValueError as exc:
                self.error = f'is not plain JSON ({exc}); left untouched'

    def write(self):
        current = self.path.read_text() if self.path.exists() else None
        if current != self.text:
            raise Blocked(f'{self.path} changed during this run; nothing written, rerun')
        if self.path.exists():
            fd, backup = tempfile.mkstemp(prefix=f'{self.path.name}.bak-{time.strftime("%Y%m%d-%H%M%S")}-', dir=self.path.parent)
            os.close(fd)
            shutil.copy2(self.path, backup)
        fd, tmp = tempfile.mkstemp(prefix=f'.{self.path.name}.', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as fh:
                fh.write(json.dumps(self.data, indent=2, allow_nan=False) + '\n')
            if self.path.exists():
                shutil.copymode(self.path, tmp)
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


class Sync:
    def __init__(self, repo, home, apply):
        self.repo, self.home, self.apply = repo, home, apply
        self.market, self.plugin = names(repo)
        self.server = {'command': 'node', 'args': [str(repo / 'scripts' / 'debugger-server.cjs')]}
        self.pending, self.blocked, self.done = [], [], []
        self.configs = {}

    def config(self, path):
        if path not in self.configs:
            self.configs[path] = Config(path)
        return self.configs[path]

    # --- plan -------------------------------------------------------------------------------
    def plan_claude(self):
        if not (self.home / '.claude').exists():
            return
        cfg = self.config(self.home / '.claude' / 'settings.json')
        if cfg.error:
            self.blocked.append(f'claude: {cfg.path} {cfg.error}')
            return
        want = {'source': {'source': 'directory', 'path': str(self.repo)}, 'autoUpdate': True}
        markets = cfg.data.setdefault('extraKnownMarketplaces', {})
        if markets.get(self.market) != want:
            markets[self.market] = want
            self.pending.append(('claude', f'register marketplace {self.market} -> {self.repo}', cfg))
        enabled = cfg.data.setdefault('enabledPlugins', {})
        key = f'{self.plugin}@{self.market}'
        if enabled.get(key) is not True:
            enabled[key] = True
            self.pending.append(('claude', f'enable {key}', cfg))

    def plan_mcp(self, host, path):
        if not path.parent.exists():
            return
        cfg = self.config(path)
        if cfg.error:
            self.blocked.append(f'{host}: {path} {cfg.error}')
            return
        servers = cfg.data.setdefault('mcpServers', {})
        entry = servers.get(SERVER_NAME)
        if entry is None:
            servers[SERVER_NAME] = dict(self.server)
            self.pending.append((host, f'register memory server in {path}', cfg))
        elif not isinstance(entry, dict):
            self.blocked.append(f'{host}: {SERVER_NAME} in {path} is not an object; left untouched')
        elif {k: entry.get(k) for k in self.server} != self.server:
            entry.update(self.server)  # keep env, disabled and any other user fields
            self.pending.append((host, f'update memory server command in {path}', cfg))

    def plan_links(self, host, folder):
        if not folder.parent.exists():
            return
        root = self.repo / 'skills'
        for name in skills(self.repo):
            link, target = folder / name, root / name
            if link.is_symlink() and target_of(link) == target:
                continue
            if link.is_symlink() and inside(target_of(link), root):
                self.pending.append((host, f'repoint {link}', ('relink', link, target)))
            elif link.exists() or link.is_symlink():
                self.blocked.append(f'{host}: {link} exists and is not a Code Audit link; left untouched')
            else:
                self.pending.append((host, f'link {link}', ('link', link, target)))
        if folder.exists():
            for link in folder.iterdir():
                if link.is_symlink() and inside(target_of(link), root) and not link.exists():
                    self.pending.append((host, f'remove stale {link}', ('unlink', link, None)))

    def plan_retire(self):
        roots = [self.repo.parent / r for r in RETIRED_REPOS]
        for folder in ('.claude/skills', '.codex/skills', '.cursor/skills', '.gemini/skills', '.agents/skills'):
            base = self.home / folder
            if not base.exists():
                continue
            for link in base.iterdir():
                if link.is_symlink() and any(inside(target_of(link), r) for r in roots):
                    self.pending.append(('retire', f'remove {link} -> {target_of(link)}', ('unlink', link, None)))

    def plan_codex(self, run):
        if not (self.home / '.codex').exists():
            return
        exe = shutil.which('codex')
        if not exe:
            self.blocked.append('codex: CLI not found on PATH')
            return
        listed = run([exe, 'plugin', 'marketplace', 'list'], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        lines = listed.stdout.splitlines()
        heading = f'Marketplace `{self.market}`'
        at = [i for i, line in enumerate(lines) if line.strip() == heading]
        source_ok = bool(at) and any(str(self.repo) in line for line in lines[at[0] + 1:at[0] + 3])
        if not at:
            self.pending.append(('codex', f'add marketplace {self.market}', ('codex', 'marketplace', 'add', str(self.repo))))
        elif not source_ok:
            self.blocked.append(f'codex: marketplace {self.market} points somewhere other than {self.repo}; '
                                f'run `codex plugin marketplace remove {self.market}` then rerun')
            return
        self.pending.append(('codex', f'install/refresh {self.plugin}@{self.market}', ('codex', 'add', f'{self.plugin}@{self.market}')))
        self.codex_exe = exe

    # --- apply ------------------------------------------------------------------------------
    def apply_all(self, run):
        written = set()
        for host, label, action in self.pending:
            try:
                if isinstance(action, Config):
                    if action.path not in written:
                        action.write()
                        written.add(action.path)
                elif action[0] == 'link':
                    action[1].parent.mkdir(parents=True, exist_ok=True)
                    action[1].symlink_to(action[2])
                elif action[0] == 'relink':
                    action[1].unlink()
                    action[1].symlink_to(action[2])
                elif action[0] == 'unlink':
                    if action[1].is_symlink():
                        action[1].unlink()
                elif action[0] == 'codex':
                    out = run([self.codex_exe, 'plugin', *action[1:]], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=180)
                    if out.returncode != 0:
                        raise Blocked(f'codex plugin {" ".join(action[1:])} failed: {(out.stderr or out.stdout).strip()[:300]}')
                self.done.append(f'{host}: {label}')
            except (Blocked, OSError) as exc:
                self.blocked.append(f'{host}: {label} failed: {exc}')


def main(argv=None, run=subprocess.run):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apply', action='store_true', help='make the changes (default: report only)')
    ap.add_argument('--retire', action='store_true', help='also remove links into retired repos')
    ap.add_argument('--skip-codex', action='store_true')
    ap.add_argument('--repo', type=Path, help='install from this checkout (default: main checkout of this repo)')
    a = ap.parse_args(argv)
    repo = (a.repo or main_checkout(Path(__file__).resolve().parents[1])).resolve()
    if not (repo / '.claude-plugin' / 'marketplace.json').is_file():
        print(f'{repo} has no .claude-plugin/marketplace.json; update that checkout first', file=sys.stderr)
        return 2
    s = Sync(repo, Path.home(), a.apply)
    s.plan_claude()
    if not a.skip_codex:
        s.plan_codex(run)
    s.plan_links('cursor', s.home / '.cursor' / 'skills')
    s.plan_mcp('cursor', s.home / '.cursor' / 'mcp.json')
    s.plan_mcp('gemini', s.home / '.gemini' / 'settings.json')
    s.plan_links('shared', s.home / '.agents' / 'skills')
    if a.retire:
        s.plan_retire()
    print(f'repo: {repo}')
    if a.apply:
        s.apply_all(run)
        for line in s.done:
            print(f'done     {line}')
    else:
        for host, label, _ in s.pending:
            print(f'pending  {host}: {label}')
    for line in s.blocked:
        print(f'BLOCKED  {line}')
    if not s.pending and not s.blocked:
        print('everything is in sync')
    if s.blocked:
        return 1
    # Check mode: a Codex refresh is always offered, so it alone does not count as drift.
    drift = [p for p in s.pending if not (p[0] == 'codex' and 'refresh' in p[1])]
    return 0 if a.apply or not drift else 1


if __name__ == '__main__':
    sys.exit(main())
