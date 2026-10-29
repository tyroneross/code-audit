#!/usr/bin/env python3
"""F1: tool-less full-module reviews for four arms; raw outputs stay outside the repository."""
import argparse
import json
from pathlib import Path
from common import ARMS,MODEL,EVALS,guidance,guidance_sha256,load,guarded

trial=load('comparison_trial',EVALS/'repository/trial.py')
experiment=load('comparison_experiment',EVALS/'repository/experiment.py')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=EVALS.parent);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=2);p.add_argument('--timeout',type=int,default=240);p.add_argument('--only',nargs='*',default=None,help='folder names to run, for resuming a partial batch')
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((EVALS/'repository/cases.json').read_text())
    ledger=[];trial.run_bounded=guarded(trial.run_bounded,ledger)
    for repeat in range(1,a.repeats+1):
        arms=ARMS if repeat%2 else list(reversed(ARMS))
        for case in (manifest['cases'] if repeat%2 else list(reversed(manifest['cases']))):
            source=experiment.packet(case,manifest,a.repo)
            for arm in arms:
                folder=out/f'{case["id"]}-{arm}-{repeat}'
                if a.only is not None and folder.name not in a.only:continue
                if folder.exists():print(folder.name,'exists; skipped',flush=True);continue
                text=guidance(arm);prompt=experiment.FORMAT+'\nGUIDANCE\n'+text+'\nCASE\n'+json.dumps(source)
                before=len(ledger);meta=trial.call(prompt,folder,MODEL,a.timeout)
                meta.update({'case_id':case['id'],'arm':arm,'repeat':repeat,'source_revision':case['revision'],'guidance_sha256':guidance_sha256(arm),'guidance_words':len(text.split()),'launch_assertion':ledger[before] if len(ledger)>before else None})
                if meta['status']=='completed':
                    try:experiment.validate_review(json.loads((folder/'answer.json').read_text()),case['id'])
                    except (ValueError,KeyError,TypeError) as error:meta.update({'status':'invalid_review','error':str(error)})
                (folder/'meta.json').write_text(json.dumps(meta,indent=2)+'\n')
                print(folder.name,meta['status'],meta.get('elapsed_seconds'),flush=True)

if __name__=='__main__':main()
