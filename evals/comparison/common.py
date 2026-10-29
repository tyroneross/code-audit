"""Shared arm, model and launch-assertion settings for the source-retirement comparison."""
import hashlib
import importlib.util
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
EVALS=ROOT.parent
ARMS=['code-audit','coding-debugger','code-principles-audit','none']
MODEL='gpt-6.1-sol'
EFFORT='model_reasoning_effort="medium"'
sys.path.insert(0,str(EVALS/'matched'));sys.path.insert(0,str(EVALS/'repository'))


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def guidance(arm):
    if arm not in ARMS:raise ValueError('unknown arm '+arm)
    return (EVALS/'matched/guidance'/f'{arm}.txt').read_text()


def guidance_sha256(arm):
    return hashlib.sha256(guidance(arm).encode()).hexdigest()


def assert_launch(command):
    """Refuse to start a model process unless the pinned model and effort are on the command line."""
    flat=[str(part) for part in command]
    if 'codex' not in [Path(p).name for p in flat]:raise RuntimeError('launch refused: only the codex host is used in this comparison')
    try:model=flat[flat.index('-m')+1]
    except (ValueError,IndexError):raise RuntimeError('launch refused: model not pinned with -m')
    if model!=MODEL:raise RuntimeError(f'launch refused: model {model!r} != {MODEL!r}')
    if EFFORT not in flat:raise RuntimeError('launch refused: effort not pinned')
    return {'asserted_model':model,'asserted_effort':'medium'}


def guarded(run_bounded,ledger):
    def wrapper(command,**kwargs):
        if any(Path(str(p)).name=='codex' for p in command):ledger.append(assert_launch(command))
        return run_bounded(command,**kwargs)
    return wrapper
