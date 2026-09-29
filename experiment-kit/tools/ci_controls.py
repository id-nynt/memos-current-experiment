"""Explicit permanent required-operation controls; no retry or controller policy."""
import datetime
import json
from pathlib import Path

CONTROLS = {'CI02': 'build', 'CI03': 'test'}


def run_control(scenario, boundary, identity, evidence):
    if CONTROLS.get(scenario) != boundary:
        return False
    if not all(identity.get(k) for k in ('campaign_id', 'control_sha', 'release_sha')):
        raise ValueError('Permanent control requires exact candidate identity')
    value = dict(event='deterministic_failure', timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 scenario=scenario, boundary=boundary, **identity,
                 mechanism='permanent_required_operation_fixture', permanent=True)
    path=Path(evidence);path.mkdir(parents=True,exist_ok=True)
    with (path/'ci-control.json').open('x',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2)
    raise RuntimeError('Permanent experiment '+boundary+' failure')
