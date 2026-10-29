"""Fail-closed macOS filesystem boundary for synthetic repair processes."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import os
import signal

# Resolved once at import, before any lane rewrites HOME for a child.
REAL_HOME=Path.home().resolve()
# The only parent variables a model lane receives; everything else (tokens, API keys, agent hooks) is dropped.
LANE_PATH='/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'


def lane_env(work, **extra):
    """Minimal child environment: fixed PATH, HOME and TMPDIR inside the workspace, plus named extras."""
    work=Path(work).resolve()
    env={'PATH':LANE_PATH,'HOME':str(work),'TMPDIR':str(work),'LANG':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1','RALLY_HOOKS':'off'}
    env.update({k:str(v) for k,v in extra.items()})
    return env


def profile(workspace, protected, readable=()):
    workspace=Path(workspace).resolve()
    quote=lambda p:json.dumps(str(Path(p).resolve()))
    # Read system/runtime/auth files, but never another temporary workspace or the repository/oracles.
    temp_roots={Path('/tmp').resolve(),Path('/private/var/folders').resolve(),Path(tempfile.gettempdir()).resolve()}
    rules=['(version 1)','(allow default)',f'(deny file-write* (require-all (require-not (subpath {quote(workspace)})) (require-not (subpath \"/dev\"))))']
    for parent in sorted(temp_roots):
        rules.append(f'(deny file-read-data (require-all (subpath {quote(parent)}) (require-not (subpath {quote(workspace)}))))')
    for path in protected:
        rules.append(f'(deny file-read-data (subpath {quote(path)}))')
    # The home folder is unreadable except the workspace and named files (the existing Codex auth file).
    allow=''.join(f' (require-not (literal {quote(p)}))' for p in readable)
    rules.append(f'(deny file-read-data (require-all (subpath {quote(REAL_HOME)}) (require-not (subpath {quote(workspace)})){allow}))')
    rules.append(f'(deny file-read* (subpath {quote(REAL_HOME/"Library/Keychains")}))')
    rules.append('(deny process-exec (literal "/usr/bin/security"))')
    return '\n'.join(rules)+'\n'


def sandbox_command(command, workspace, protected, readable=()):
    sandbox=shutil.which('sandbox-exec')
    if not sandbox:raise RuntimeError('OS read isolation unavailable: sandbox-exec is required; no prompt-only fallback')
    path=Path(workspace)/'repair.sb';path.write_text(profile(workspace,protected,readable))
    return [sandbox,'-f',str(path),*command]


def check_boundary(workspace, protected_file, protected=None, readable=()):
    """Exercise the real generation policy: repository/output, foreign temp data, the home folder and the environment."""
    workspace=Path(workspace).resolve();protected=list(protected or [protected_file])
    own=workspace/'read-canary';own.write_text('local')
    outside=None;home_dir=None
    try:
        home_dir=Path(tempfile.mkdtemp(prefix='code-audit-home-canary-',dir=REAL_HOME/'Library/Caches'))
        home_file=home_dir/'secret';home_file.write_text('home')
        os.environ['CODE_AUDIT_ENV_CANARY']='parent-only'
        env_seen=subprocess.run(sandbox_command(['/usr/bin/env'],workspace,protected,readable),env=lane_env(workspace),capture_output=True,timeout=5).stdout
        os.environ.pop('CODE_AUDIT_ENV_CANARY',None)
        home=subprocess.run(sandbox_command(['/bin/cat',str(home_file)],workspace,protected,readable),capture_output=True,timeout=5)
        if home.returncode==0 or b'CODE_AUDIT_ENV_CANARY' in env_seen or not env_seen:raise RuntimeError('OS isolation canary failed: home folder or environment reachable')
        with tempfile.TemporaryDirectory(prefix='code-audit-foreign-canary-') as folder:
            foreign=Path(folder)/'secret';foreign.write_text('foreign')
            with tempfile.NamedTemporaryFile(prefix='code-audit-write-canary-',dir=Path(protected_file).parent,delete=False) as stream:outside=Path(stream.name)
            outside.unlink()
            def call(command):return subprocess.run(sandbox_command(command,workspace,protected,readable),capture_output=True,timeout=5)
            allowed=call(['/bin/cat',str(own)]);denied=call(['/bin/cat',str(protected_file)]);peer=call(['/bin/cat',str(foreign)])
            write=call(['/usr/bin/touch',str(outside)])
            if allowed.returncode or allowed.stdout!=b'local' or denied.returncode==0 or peer.returncode==0 or write.returncode==0:raise RuntimeError('OS isolation canary failed')
            return {'own_read':'allowed','protected_read':'denied','foreign_temp_read':'denied','outside_write':'denied','home_read':'denied','parent_env':'absent'}
    finally:
        os.environ.pop('CODE_AUDIT_ENV_CANARY',None)
        if outside and outside.exists():outside.unlink()
        if home_dir:shutil.rmtree(home_dir,ignore_errors=True)

def run_bounded(command, *, timeout, **kwargs):
    """Terminate the entire owned process group before reading model-created artifacts."""
    data=kwargs.pop('input',None)
    process=subprocess.Popen(command,start_new_session=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs)
    try:
        stdout,stderr=process.communicate(data,timeout=timeout)
        return subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
    except subprocess.TimeoutExpired as error:
        try:os.killpg(process.pid,signal.SIGKILL)
        except (ProcessLookupError,PermissionError):pass
        try:stdout,stderr=process.communicate(timeout=.5)
        except subprocess.TimeoutExpired as drain:
            stdout,stderr=drain.stdout,drain.stderr;error.escaped_pipe=True
            for stream in [process.stdin,process.stdout,process.stderr]:
                if stream:stream.close()
        error.stdout=stdout;error.stderr=stderr
        raise error
    finally:
        try:os.killpg(process.pid,signal.SIGKILL)
        except (ProcessLookupError,PermissionError):pass
        process.wait()
