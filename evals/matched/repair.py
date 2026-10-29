#!/usr/bin/env python3
"""Explicit isolated repair trials with a frozen baseline and executable parent oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import stat
from isolation import sandbox_command, check_boundary, run_bounded

ROOT=Path(__file__).resolve().parent
BASELINE=ROOT.parent/'timeout-retry/baseline'
VERIFIER=ROOT.parent/'timeout-retry/verify.py'
ALLOWED={'case/checkout.py','case/gateway.py','case/policy.py','case/test_repair.py'}

def snapshot():
    return {p.relative_to(BASELINE).as_posix():p.read_bytes() for p in BASELINE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'},VERIFIER.read_bytes()

def candidate_bytes(candidate):
    """Read no linked, special, oversized or multiply linked objects in the parent."""
    files={};total=0;entries=0
    def walk(directory,relative):
        nonlocal total,entries
        if len(relative.parts)>16:raise ValueError('candidate exceeds directory-depth budget')
        for name in os.listdir(directory):
            entries+=1
            if entries>256:raise ValueError('candidate exceeds entry budget')
            if name in ['__pycache__','.pytest_cache','.git']:continue
            info=os.stat(name,dir_fd=directory,follow_symlinks=False)
            key=(relative/name).as_posix()
            if stat.S_ISDIR(info.st_mode):
                child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                try:walk(child,relative/name)
                finally:os.close(child)
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('candidate contains a linked or special file')
            if info.st_size>1048576:raise ValueError('candidate file exceeds 1 MiB')
            descriptor=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
            try:
                opened=os.fstat(descriptor)
                if not stat.S_ISREG(opened.st_mode) or opened.st_nlink!=1:raise ValueError('candidate file changed type before read')
                with os.fdopen(descriptor,'rb',closefd=False) as stream:data=stream.read(1048577)
            finally:os.close(descriptor)
            if len(files)>=64:raise ValueError('candidate exceeds 64-file budget')
            total+=len(data)
            if len(data)>1048576 or total>2097152:raise ValueError('candidate exceeds snapshot budget')
            files[key]=data
    directory=os.open(candidate,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:walk(directory,Path())
    finally:os.close(directory)
    return files

def protected_changes(candidate, baseline=None):
    baseline=baseline if baseline is not None else snapshot()[0]
    files=candidate if isinstance(candidate,dict) else candidate_bytes(candidate)
    changed=[name for name,data in baseline.items() if name not in ALLOWED and files.get(name)!=data]
    changed.extend(name for name in files if name not in baseline and name not in ALLOWED)
    return sorted(changed)

def materialize(files, destination):
    for name,data in files.items():
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)

def output_bytes(value):
    return value if isinstance(value,bytes) else (value or '').encode()

def output_text(value):
    return value.decode(errors='replace') if isinstance(value,bytes) else value or ''

def run(host,arm,repeat,out,model,timeout,frozen=None):
    baseline,verifier=frozen if frozen is not None else snapshot()
    dest=out/f'repair-{host}-{arm}-{repeat}';dest.mkdir(parents=True,exist_ok=False)
    guidance=(ROOT/'guidance'/f'{arm}.txt').read_text()
    prompt='''Repair the checkout operation in ./case. Start from case/README.md, CONTRACT.md and source; investigate duplicate receipts after lost responses, cold-start failures and deadline overruns. Preserve public APIs/contracts, simulator.py, profile.json and test_public.py exactly. Edit only checkout.py, gateway.py, policy.py and optionally test_repair.py. No dependencies, network calls, real waiting or background processes. Stay inside this workspace; do not inspect hidden oracles, earlier solutions, other workspaces or model outputs. Complete the repair using deterministic local tests and report actual checks and limits.\n\nGUIDANCE\n'''+guidance
    (dest/'prompt.txt').write_text(prompt)
    meta={'host':host,'arm':arm,'repeat':repeat,'requested_model':model,'served_models':None,'effort':'medium','timeout_seconds':timeout,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'guidance_words':len(guidance.split()),'status':'unavailable','isolation':'OS sandbox; repository/output/foreign temporary reads denied; writes confined to this workspace; frozen baseline and parent verifier'}
    start=time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix='code-audit-repair-') as folder:
            work=Path(folder).resolve();candidate=work/'candidate';materialize(baseline,candidate)
            env=os.environ.copy();env.update({'RALLY_HOOKS':'off','PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(work/'tmp'),'CLAUDE_CODE_TMPDIR':str(work/'claude-tmp')});(work/'tmp').mkdir();(work/'claude-tmp').mkdir()
            protected=[ROOT.parents[1],out.resolve()]
            meta['kernel_canary']=check_boundary(work,VERIFIER,protected)
            if host=='claude':
                cmd=['claude','-p','--safe-mode','--setting-sources','','--settings','{"disableAllHooks":true}','--disable-slash-commands','--no-session-persistence','--tools','Read,Write,Edit,Bash','--allowedTools','Read,Write,Edit,Bash','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--output-format','stream-json','--verbose','--effort','medium','--model',model]
            else:
                home=work/'codex-home';home.mkdir();auth=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'auth.json'
                if auth.exists():(home/'auth.json').symlink_to(auth)
                env['CODEX_HOME']=str(home)
                cmd=['codex','exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--json','-s','danger-full-access','-m',model,'-c','approval_policy="never"','-c','cli_auth_credentials_store="file"','-c','model_reasoning_effort="medium"','-']
            meta['command']=cmd
            try:
                result=run_bounded(sandbox_command(cmd,work,protected),input=prompt.encode(),text=False,env=env,cwd=candidate,timeout=timeout)
                (dest/'host-output.jsonl').write_bytes(result.stdout if isinstance(result.stdout,bytes) else result.stdout.encode());(dest/'stderr.txt').write_bytes(result.stderr if isinstance(result.stderr,bytes) else result.stderr.encode());meta['exit_code']=result.returncode
                rows=[json.loads(line) for line in output_text(result.stdout).splitlines() if line.strip()]
                if not all(isinstance(row,dict) for row in rows):raise ValueError('host event must be an object')
                if host=='claude':
                    ends=[row for row in rows if row.get('type')=='result']
                    if len(ends)!=1:raise ValueError('missing Claude result')
                    row=ends[0];meta.update({'served_models':list(row.get('modelUsage',{})),'usage':row.get('usage'),'cost_usd':row.get('total_cost_usd')});success=result.returncode==0 and not row.get('is_error')
                else:
                    ends=[row for row in rows if row.get('type')=='turn.completed'];success=result.returncode==0 and len(ends)==1 and not any(row.get('type') in ['error','turn.failed'] for row in rows);meta.update({'usage':ends[0].get('usage') if ends else None,'cost_usd':None})
                meta['status']='completed' if success else 'host_failed'
            except Exception as error:
                meta.update({'status':'host_protocol_error','error':str(error),'error_type':type(error).__name__})
                if isinstance(error,subprocess.TimeoutExpired):
                    meta['status']='host_timeout'
                    (dest/'host-output.jsonl').write_bytes(output_bytes(error.stdout));(dest/'stderr.txt').write_bytes(output_bytes(error.stderr));meta['escaped_pipe']=getattr(error,'escaped_pipe',False)
            meta['elapsed_seconds']=round(time.monotonic()-start,3)
            try:files=candidate_bytes(candidate)
            except (OSError,RecursionError) as error:raise ValueError('invalid candidate artifact: '+type(error).__name__) from error
            meta['protected_changes']=protected_changes(files,baseline)
            # Freeze model output into a distinct parent-only workspace before introducing the oracle.
            with tempfile.TemporaryDirectory(prefix='code-audit-parent-verifier-') as private:
                private=Path(private).resolve();frozen_candidate=private/'candidate'
                materialize(files,frozen_candidate)
                materialize(files,dest/'candidate')
                pristine=private/'pristine';materialize(baseline,pristine)
                for name in ['bridge.py','worker.py','isolation.py']:shutil.copyfile(ROOT/name,private/name)
                oracle=private/'verify.py';oracle.write_bytes(verifier);receipt=private/'verification.json'
                try:
                    check=run_bounded(['python3',str(private/'bridge.py'),str(oracle),str(frozen_candidate),str(receipt),str(pristine),json.dumps([str(path) for path in protected])],text=True,env={**env,'TMPDIR':str(private)},cwd=private,timeout=30)
                    (dest/'verification-output.txt').write_text(check.stdout+check.stderr);meta['verification_exit_code']=check.returncode
                    meta['verification_status']='passed' if check.returncode==0 else 'failed'
                    if receipt.exists():
                        result=json.loads(receipt.read_text());meta['verification']=result;
                        if result.get('harness_faults'):meta['verification_status']='harness_fault'
                        (dest/'verification.json').write_text(json.dumps(result,indent=2))
                    else:meta['verification_status']='missing_receipt'
                except Exception as error:
                    (dest/'verification-output.txt').write_text(output_text(getattr(error,'stdout',None))+output_text(getattr(error,'stderr',None)))
                    meta.update({'verification_status':'timeout' if isinstance(error,subprocess.TimeoutExpired) else 'error','verification_error':str(error),'verification_error_type':type(error).__name__})
                    if receipt.exists():
                        try:
                            partial=json.loads(receipt.read_text())
                            if not isinstance(partial,dict) or not isinstance(partial.get('cases'),list):raise ValueError('invalid parent receipt')
                            partial['partial']=True;meta['verification']=partial;meta['verification_partial']=True
                            (dest/'verification.json').write_text(json.dumps(partial,indent=2))
                        except (OSError,ValueError) as receipt_error:meta['verification_receipt_error']=str(receipt_error)
            current,oracle=snapshot()
            meta['source_integrity_unchanged']=current==baseline and oracle==verifier
            if not meta['source_integrity_unchanged']:meta['status']='contaminated'
    except Exception as error:
        meta.update({'status':'contaminated' if isinstance(error,ValueError) else 'unavailable','error':str(error),'error_type':type(error).__name__})
    finally:
        try:
            current,current_oracle=snapshot();meta['source_integrity_unchanged']=current==baseline and current_oracle==verifier
            if not meta['source_integrity_unchanged']:meta['status']='contaminated'
        except Exception as error:meta.update({'source_integrity_unchanged':False,'source_integrity_error':str(error),'status':'contaminated'})
        meta.setdefault('elapsed_seconds',round(time.monotonic()-start,3));(dest/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
    return meta

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--host',choices=['claude','codex'],required=True);parser.add_argument('--model',required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--repeats',type=int,default=2);parser.add_argument('--timeout',type=int,default=300);args=parser.parse_args()
    if not 1<=args.repeats<=5 or not 1<=args.timeout<=600:parser.error('repeats 1..5; timeout 1..600')
    if args.host=='claude' and not os.environ.get('ANTHROPIC_API_KEY'):parser.error('claude host refused: without an API key the Claude CLI loads its login from the macOS Keychain, which the owner rule forbids')
    args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=True);frozen=snapshot()
    (args.out/(args.host+'-baseline-hashes.json')).write_text(json.dumps({'baseline':{name:hashlib.sha256(data).hexdigest() for name,data in frozen[0].items()},'verifier':hashlib.sha256(frozen[1]).hexdigest()},indent=2))
    for repeat in range(1,args.repeats+1):
        for arm in (['none','current','trimmed'] if repeat%2 else ['trimmed','current','none']):
            meta=run(args.host,arm,repeat,args.out,args.model,args.timeout,frozen);print(json.dumps(meta),flush=True)
            if meta.get('source_integrity_unchanged') is False:raise RuntimeError('baseline/verifier source changed; batch stopped without overwriting source')
if __name__=='__main__':main()
