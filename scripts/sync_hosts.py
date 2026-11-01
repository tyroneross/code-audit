#!/usr/bin/env python3
"""Install or refresh Code Audit in every local agent host, and retire the plugins it replaces.

  sync_hosts.py            report drift per host (no changes); exit 1 if anything needs updating
  sync_hosts.py --apply    make the changes, backing up each edited config file first
  sync_hosts.py --apply --retire   also remove links to the retired code-principles-audit repo

Hosts, each handled only when its home folder exists:
  Claude Code   ~/.claude/settings.json: register this repo as marketplace `code-audit-local`
                and enable `code-audit@code-audit-local` (what `claude plugin marketplace add`
                and `install` record). The `claude plugin` CLI is not called. If a new session
                does not load the plugin, run `/plugin marketplace add <repo>` and
                `/plugin install code-audit@code-audit-local` inside Claude Code.
  Codex         `codex plugin marketplace add` (if missing) and `codex plugin add`, which also
                refreshes Codex's cached copy after this repo changes.
  Cursor        ~/.cursor/skills/<skill> links and the memory server in ~/.cursor/mcp.json.
  Gemini        the memory server in ~/.gemini/settings.json (skills come from ~/.agents/skills).
  Shared        ~/.agents/skills/<skill> links.

The repository path is derived from this file's location.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MARKET, PLUGIN = 'code-audit-local', 'code-audit'
SERVER = {'command': 'node', 'args': [str(REPO / 'scripts' / 'debugger-server.cjs')]}
RETIRED = ('code-principles-audit',)  # repo folder names whose links are retired


def skills():
    return sorted(p.parent.name for p in (REPO / 'skills').glob('*/SKILL.md'))


def load(path):
    return json.loads(path.read_text()) if path.exists() else {}


def save(path, data, apply, notes):
    """Back up, then replace atomically."""
    if not apply:
        return
    if path.exists():
        shutil.copy2(path, path.with_name(f'{path.name}.bak-{time.strftime("%Y%m%d-%H%M%S")}'))
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    os.replace(tmp, path)
    notes.append(f'wrote {path}')


def claude(home, apply, notes):
    path = home / '.claude' / 'settings.json'
    data = load(path)
    want_market = {'source': {'source': 'directory', 'path': str(REPO)}, 'autoUpdate': True}
    drift = []
    if data.get('extraKnownMarketplaces', {}).get(MARKET) != want_market:
        drift.append(f'register marketplace {MARKET}')
        data.setdefault('extraKnownMarketplaces', {})[MARKET] = want_market
    if data.get('enabledPlugins', {}).get(f'{PLUGIN}@{MARKET}') is not True:
        drift.append(f'enable {PLUGIN}@{MARKET}')
        data.setdefault('enabledPlugins', {})[f'{PLUGIN}@{MARKET}'] = True
    if drift:
        save(path, data, apply, notes)
    return drift


def codex(home, apply, notes, run=subprocess.run):
    exe = shutil.which('codex')
    if not exe:
        return ['codex CLI not found on PATH']
    def call(*args):
        return run([exe, 'plugin', *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
    listed = call('marketplace', 'list')
    drift = []
    if MARKET not in listed.stdout:
        drift.append(f'add marketplace {MARKET}')
        if apply:
            call('marketplace', 'add', str(REPO))
    # `plugin add` copies the current repo into Codex's cache, so it doubles as the refresh step.
    drift.append(f'refresh {PLUGIN}@{MARKET} cache')
    if apply:
        out = call('add', f'{PLUGIN}@{MARKET}')
        notes.append(f'codex: {(out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr).strip() else out.returncode}')
    return drift


def links(folder, apply, notes):
    drift = []
    if not folder.parent.exists():
        return drift
    for name in skills():
        link, target = folder / name, REPO / 'skills' / name
        if link.is_symlink() and Path(os.readlink(link)) == target:
            continue
        if link.exists() or link.is_symlink():
            drift.append(f'CONFLICT {link} exists and is not this repo\'s skill; left alone')
            continue
        drift.append(f'link {link}')
        if apply:
            folder.mkdir(parents=True, exist_ok=True)
            link.symlink_to(target)
    # Remove links into this repo whose skill no longer exists.
    for link in folder.glob('*') if folder.exists() else []:
        if link.is_symlink() and str(os.readlink(link)).startswith(str(REPO / 'skills')) and not link.exists():
            drift.append(f'remove stale {link}')
            if apply:
                link.unlink()
    return drift


def mcp(path, apply, notes):
    if not path.parent.exists():
        return []
    data = load(path)
    if data.get('mcpServers', {}).get('code-audit-debugger') == SERVER:
        return []
    data.setdefault('mcpServers', {})['code-audit-debugger'] = SERVER
    save(path, data, apply, notes)
    return [f'register memory server in {path}']


def retire(home, apply, notes):
    drift = []
    for folder in ('.claude/skills', '.codex/skills', '.cursor/skills', '.gemini/skills', '.agents/skills'):
        for link in (home / folder).glob('*') if (home / folder).exists() else []:
            if link.is_symlink() and any(f'/{r}/' in os.readlink(link) for r in RETIRED):
                drift.append(f'retire {link} -> {os.readlink(link)}')
                if apply:
                    link.unlink()
    return drift


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--apply', action='store_true', help='make the changes (default: report only)')
    ap.add_argument('--retire', action='store_true', help='also remove links to retired plugins')
    ap.add_argument('--skip-codex', action='store_true')
    a = ap.parse_args(argv)
    home, notes = Path.home(), []
    report = {
        'claude': claude(home, a.apply, notes) if (home / '.claude').exists() else [],
        'codex': [] if a.skip_codex or not (home / '.codex').exists() else codex(home, a.apply, notes),
        'cursor': links(home / '.cursor' / 'skills', a.apply, notes) + mcp(home / '.cursor' / 'mcp.json', a.apply, notes),
        'gemini': mcp(home / '.gemini' / 'settings.json', a.apply, notes),
        'shared': links(home / '.agents' / 'skills', a.apply, notes),
    }
    if a.retire:
        report['retire'] = retire(home, a.apply, notes)
    for host, items in report.items():
        print(f'{host}: ' + ('ok' if not items else '; '.join(items)))
    for n in notes:
        print(n)
    pending = [i for host, items in report.items() for i in items
               if not i.startswith(('refresh', 'codex CLI not found', 'CONFLICT'))]
    return 0 if a.apply or not pending else 1


if __name__ == '__main__':
    sys.exit(main())
