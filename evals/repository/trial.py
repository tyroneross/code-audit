"""Bounded tool-less Codex calls using an existing file session; never invokes Claude/Keychain."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import sys

MATCHED=Path(__file__).resolve().parents[1]/'matched'
spec=importlib.util.spec_from_file_location('repository_matched_run',MATCHED/'run.py')
matched=importlib.util.module_from_spec(spec);spec.loader.exec_module(matched)
sys.path.insert(0,str(MATCHED))
from isolation import profile,run_bounded


def sha(data):
    return hashlib.sha256(data if isinstance(data,bytes) else data.encode()).hexdigest()


def protected_profile(work,protected):
    # Deny credential UI/helper execution and Keychain file access, even on unexpected fallback.
    rules=profile(work,protected)
    keychains=Path.home()/'Library/Keychains'
    return rules+'(deny process-exec (literal "/usr/bin/security"))\n'+f'(deny file-read* (subpath {json.dumps(str(keychains))}))\n'


def call(prompt,destination,model='gpt-6.1-sol',timeout=240,auth_file=None):
    """Save a row for every attempted call; fail closed without existing file-based authentication."""
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    (destination/'prompt.txt').write_text(prompt)
    meta={'requested_model':model,'served_models':None,'effort':'medium','status':'unavailable','prompt_sha256':sha(prompt),'timeout_seconds':timeout,'credential_path':'existing Codex file auth symlink only; Keychain denied; no copied credentials','cost_usd':None}
    start=time.monotonic()
    try:
        auth=Path(auth_file) if auth_file is not None else Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'auth.json'
        if not auth.is_file():raise RuntimeError('Existing Codex file session unavailable; no credential fallback attempted')
        sandbox=__import__('shutil').which('sandbox-exec')
        if not sandbox:raise RuntimeError('OS read isolation unavailable; no prompt-only fallback')
        with tempfile.TemporaryDirectory(prefix='code-audit-repository-') as folder:
            work=Path(folder).resolve();home=work/'codex-home';home.mkdir();(home/'auth.json').symlink_to(auth.resolve())
            env={**os.environ,'CODEX_HOME':str(home),'TMPDIR':str(work),'RALLY_HOOKS':'off'}
            rules=work/'review.sb';rules.write_text(protected_profile(work,[Path(__file__).resolve().parents[2],destination.resolve().parent]))
            command=['codex','exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--json','-s','read-only','-m',model,'-c','cli_auth_credentials_store="file"','-c','model_reasoning_effort="medium"','-']
            meta['command']=command;meta['sandbox_sha256']=sha(rules.read_bytes())
            result=run_bounded([sandbox,'-f',str(rules),*command],input=prompt.encode(),text=False,cwd=work,env=env,timeout=timeout)
            (destination/'host-output.jsonl').write_bytes(result.stdout);(destination/'stderr.txt').write_bytes(result.stderr);meta['exit_code']=result.returncode
            if result.returncode:raise ValueError('host returned nonzero exit')
            answer,usage=matched.extract('codex',result.stdout.decode(errors='replace'))
            meta.update(usage)
            value=matched.json_object(answer)
            (destination/'answer.json').write_text(json.dumps(value,indent=2)+'\n');meta.update(usage);meta['status']='completed'
    except Exception as error:
        meta.update({'error':str(error),'error_type':type(error).__name__})
        if meta.get('exit_code')==0:meta['status']='invalid_response'
        if isinstance(error,subprocess.TimeoutExpired):
            meta['status']='timeout'
            for name,value in [('host-output.jsonl',error.stdout),('stderr.txt',error.stderr)]:
                (destination/name).write_bytes(value if isinstance(value,bytes) else (value or '').encode())
    finally:
        meta['elapsed_seconds']=round(time.monotonic()-start,3)
        (destination/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
    return meta
