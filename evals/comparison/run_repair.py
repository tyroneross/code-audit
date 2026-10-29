#!/usr/bin/env python3
"""F2: isolated repair trials for four arms. R1 reuses matched/repair.py; R2 replays a real historical bug."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from common import ARMS,MODEL,EFFORT,EVALS,guidance,guidance_sha256,load,guarded

repair=load('comparison_repair',EVALS/'matched/repair.py')
isolation=load('comparison_isolation',EVALS/'matched/isolation.py')
SOURCE_REPO=Path(os.environ.get('CODE_PRINCIPLES_AUDIT_REPO','/Users/tyroneross/dev/git-folder/code-principles-audit'))
# Deny model reads of every local checkout, so no arm can read the historical fix or another arm's output.
PROTECTED_ROOT=Path(os.environ.get('CODE_AUDIT_PROTECTED_ROOT','/Users/tyroneross/dev/git-folder'))
FIX='4361bd38045e21e4651ec265261d0aad7a9092ff'
DIR='skills/code-principles/scripts'
EDITABLE={'scan.py','test_code_principles.py'}
PROMPT='''Repair the source scanner in this directory (scan.py; run it with `python3 scan.py --json <path>`). Users report that a scan of a tree containing files the scanner never read still prints a normal "Scanned N files" summary and no warning: a file that is not valid UTF-8 and a directory without read permission both disappear silently, so a partial scan looks complete and clean. Find the cause and repair it.

Output contract the fix must meet: "files_scanned" counts only files whose contents were actually scanned. The --json object gains a top-level "skipped" list of {"path": ..., "reason": ...} objects, one per input that was not scanned; use the reason "not UTF-8" for an undecodable file and a reason starting with "directory not readable" for a directory that cannot be listed. Keep every existing key, hit, exit code and text summary line; also make skipped inputs visible in the text output. Edit only scan.py and optionally test_code_principles.py; do not edit outcome.py. No dependencies, network or background processes. Stay inside this directory and do not look for hidden tests, earlier solutions or other workspaces. Verify with local tests and report the actual checks and limits.

GUIDANCE
'''


def baseline():
    files={}
    for name in ['scan.py','outcome.py','test_code_principles.py']:
        files[name]=subprocess.check_output(['git','-C',str(SOURCE_REPO),'show',f'{FIX}^:{DIR}/{name}'])
    withheld=subprocess.check_output(['git','-C',str(SOURCE_REPO),'show',f'{FIX}:{DIR}/test_code_principles.py'])
    fixed=subprocess.check_output(['git','-C',str(SOURCE_REPO),'show',f'{FIX}:{DIR}/scan.py'])
    return files,withheld,fixed


def verify(scan_bytes,outcome_bytes,withheld,protected,timeout=60):
    """Run the withheld historical test against candidate scan.py in a fresh sandboxed directory."""
    with tempfile.TemporaryDirectory(prefix='code-audit-r2-verify-') as folder:
        work=Path(folder).resolve();case=work/'case';case.mkdir()
        (case/'scan.py').write_bytes(scan_bytes);(case/'outcome.py').write_bytes(outcome_bytes);(case/'test_code_principles.py').write_bytes(withheld)
        env={'PATH':os.environ['PATH'],'HOME':str(work),'TMPDIR':str(work),'PYTHONDONTWRITEBYTECODE':'1'}
        command=isolation.sandbox_command(['python3','-m','unittest','test_code_principles'],work,protected)
        try:result=isolation.run_bounded(command,text=False,env=env,cwd=case,timeout=timeout)
        except subprocess.TimeoutExpired:return {'status':'timeout','exit_code':None,'output':''}
        text=(result.stdout+result.stderr).decode(errors='replace')
        tail=[line for line in text.splitlines() if line.startswith(('Ran ','OK','FAILED','FAIL:','ERROR:'))]
        return {'status':'passed' if result.returncode==0 else 'failed','exit_code':result.returncode,'summary':tail[-12:]}


def preflight(out):
    files,withheld,fixed=baseline();protected=[PROTECTED_ROOT,EVALS.parent,out]
    pre=verify(files['scan.py'],files['outcome.py'],withheld,protected);post=verify(fixed,files['outcome.py'],withheld,protected)
    if pre['status']!='failed' or post['status']!='passed':raise RuntimeError(f'R2 oracle preflight failed: pre={pre} post={post}')
    return {'pre_fix':pre,'historical_fix':post,'fix_commit':FIX,'baseline_sha256':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()},'withheld_sha256':hashlib.sha256(withheld).hexdigest()}


def run_r2(arm,repeat,out,timeout,ledger):
    dest=out/f'r2-{arm}-{repeat}';dest.mkdir(parents=True,exist_ok=False)
    files,withheld,_=baseline();text=guidance(arm);prompt=PROMPT+text;(dest/'prompt.txt').write_text(prompt)
    meta={'case':'R2','arm':arm,'repeat':repeat,'requested_model':MODEL,'effort':'medium','served_models':None,'timeout_seconds':timeout,'guidance_sha256':guidance_sha256(arm),'guidance_words':len(text.split()),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'status':'unavailable'}
    start=time.monotonic();protected=[PROTECTED_ROOT,EVALS.parent,out.resolve()]
    try:
        with tempfile.TemporaryDirectory(prefix='code-audit-r2-') as folder:
            work=Path(folder).resolve();candidate=work/'candidate';candidate.mkdir()
            for name,data in files.items():(candidate/name).write_bytes(data)
            (work/'tmp').mkdir();home=work/'codex-home';home.mkdir()
            auth=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'auth.json'
            if not auth.is_file():raise RuntimeError('existing Codex file session unavailable')
            (home/'auth.json').symlink_to(auth.resolve())
            env={**os.environ,'CODEX_HOME':str(home),'TMPDIR':str(work/'tmp'),'RALLY_HOOKS':'off','PYTHONDONTWRITEBYTECODE':'1'}
            meta['kernel_canary']=isolation.check_boundary(work,EVALS/'comparison/README.md',protected)
            cmd=['codex','exec','--ephemeral','--ignore-user-config','--skip-git-repo-check','--json','-s','danger-full-access','-m',MODEL,'-c','approval_policy="never"','-c','cli_auth_credentials_store="file"','-c',EFFORT,'-']
            meta['command']=cmd;before=len(ledger)
            try:
                result=guarded(isolation.run_bounded,ledger)(isolation.sandbox_command(cmd,work,protected),input=prompt.encode(),text=False,env=env,cwd=candidate,timeout=timeout)
                (dest/'host-output.jsonl').write_bytes(result.stdout);(dest/'stderr.txt').write_bytes(result.stderr);meta['exit_code']=result.returncode
                rows=[json.loads(line) for line in result.stdout.decode(errors='replace').splitlines() if line.strip().startswith('{')]
                ends=[row for row in rows if row.get('type')=='turn.completed']
                meta['usage']=ends[0].get('usage') if ends else None
                meta['status']='completed' if result.returncode==0 and len(ends)==1 and not any(r.get('type') in ['error','turn.failed'] for r in rows) else 'host_failed'
            except subprocess.TimeoutExpired as error:
                meta['status']='host_timeout'
                (dest/'host-output.jsonl').write_bytes(error.stdout or b'');(dest/'stderr.txt').write_bytes(error.stderr or b'')
            meta['launch_assertion']=ledger[before] if len(ledger)>before else None
            meta['elapsed_seconds']=round(time.monotonic()-start,3)
            produced=repair.candidate_bytes(candidate)
            changed=sorted(n for n in set(produced)|set(files) if produced.get(n)!=files.get(n))
            meta['changed_files']=changed;meta['protected_changes']=[n for n in changed if n not in EDITABLE]
            (dest/'candidate').mkdir()
            for name in ['scan.py','test_code_principles.py']:
                if name in produced:(dest/'candidate'/name).write_bytes(produced[name])
            check=verify(produced.get('scan.py',b''),files['outcome.py'],withheld,protected) if 'scan.py' in produced else {'status':'missing_candidate'}
            meta['verification']=check
            meta['passed']=meta['status']=='completed' and not meta['protected_changes'] and check['status']=='passed'
    except Exception as error:
        meta.update({'status':'harness_error','error':str(error),'error_type':type(error).__name__,'passed':False})
    meta.setdefault('elapsed_seconds',round(time.monotonic()-start,3))
    (dest/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
    return meta


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--case',choices=['R1','R2','both'],default='both')
    p.add_argument('--repeats',type=int,default=2);p.add_argument('--timeout',type=int,default=300);p.add_argument('--arms',nargs='*',default=ARMS)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);ledger=[]
    if a.case in ['R2','both'] and not (out/'r2-preflight.json').exists():(out/'r2-preflight.json').write_text(json.dumps(preflight(out),indent=2)+'\n')
    repair.run_bounded=guarded(repair.run_bounded,ledger);frozen=repair.snapshot()
    for repeat in range(1,a.repeats+1):
        arms=a.arms if repeat%2 else list(reversed(a.arms))
        for arm in arms:
            if a.case in ['R1','both'] and not (out/f'repair-codex-{arm}-{repeat}').exists():
                before=len(ledger);meta=repair.run('codex',arm,repeat,out,MODEL,a.timeout,frozen)
                meta['launch_assertion']=ledger[before] if len(ledger)>before else None;meta['guidance_sha256']=guidance_sha256(arm)
                meta['passed']=meta.get('status')=='completed' and meta.get('verification_status')=='passed' and not meta.get('protected_changes')
                (out/f'repair-codex-{arm}-{repeat}'/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
                print('R1',arm,repeat,meta.get('status'),meta.get('verification_status'),meta.get('elapsed_seconds'),flush=True)
            if a.case in ['R2','both'] and not (out/f'r2-{arm}-{repeat}').exists():
                meta=run_r2(arm,repeat,out,a.timeout,ledger);print('R2',arm,repeat,meta['status'],meta.get('verification',{}).get('status'),meta.get('elapsed_seconds'),flush=True)

if __name__=='__main__':main()
