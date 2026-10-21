"""Fail-closed macOS filesystem boundary for synthetic repair processes."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import os
import signal


def profile(workspace, protected):
    workspace=Path(workspace).resolve()
    quote=lambda p:json.dumps(str(Path(p).resolve()))
    # Read system/runtime/auth files, but never another temporary workspace or the repository/oracles.
    temp_roots={Path('/tmp').resolve(),Path('/private/var/folders').resolve(),Path(tempfile.gettempdir()).resolve()}
    rules=['(version 1)','(allow default)',f'(deny file-write* (require-all (require-not (subpath {quote(workspace)})) (require-not (subpath \"/dev\"))))']
    for parent in sorted(temp_roots):
        rules.append(f'(deny file-read-data (require-all (subpath {quote(parent)}) (require-not (subpath {quote(workspace)}))))')
    for path in protected:
        rules.append(f'(deny file-read-data (subpath {quote(path)}))')
    return '\n'.join(rules)+'\n'


def sandbox_command(command, workspace, protected):
    sandbox=shutil.which('sandbox-exec')
    if not sandbox:raise RuntimeError('OS read isolation unavailable: sandbox-exec is required; no prompt-only fallback')
    path=Path(workspace)/'repair.sb';path.write_text(profile(workspace,protected))
    return [sandbox,'-f',str(path),*command]


def check_boundary(workspace, protected_file, protected=None):
    """Exercise the real generation policy, including repository/output and foreign temp data."""
    workspace=Path(workspace).resolve();protected=list(protected or [protected_file])
    own=workspace/'read-canary';own.write_text('local')
    outside=None
    try:
        with tempfile.TemporaryDirectory(prefix='code-audit-foreign-canary-') as folder:
            foreign=Path(folder)/'secret';foreign.write_text('foreign')
            with tempfile.NamedTemporaryFile(prefix='code-audit-write-canary-',dir=Path(protected_file).parent,delete=False) as stream:outside=Path(stream.name)
            outside.unlink()
            def call(command):return subprocess.run(sandbox_command(command,workspace,protected),capture_output=True,timeout=5)
            allowed=call(['/bin/cat',str(own)]);denied=call(['/bin/cat',str(protected_file)]);peer=call(['/bin/cat',str(foreign)])
            write=call(['/usr/bin/touch',str(outside)])
            if allowed.returncode or allowed.stdout!=b'local' or denied.returncode==0 or peer.returncode==0 or write.returncode==0:raise RuntimeError('OS isolation canary failed')
            return {'own_read':'allowed','protected_read':'denied','foreign_temp_read':'denied','outside_write':'denied'}
    finally:
        if outside and outside.exists():outside.unlink()

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
