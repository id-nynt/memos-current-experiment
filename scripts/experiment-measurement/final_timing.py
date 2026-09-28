"""Common final-experiment timing. No controller decisions or scenario schedules."""
import datetime
import json
import math
from pathlib import Path

CONTRACT = json.loads((Path(__file__).with_name('phase6-timing.json')).read_text())
HORIZON = CONTRACT['independent_horizon_seconds']


def window(anchor_epoch):
    if not math.isfinite(anchor_epoch):
        raise ValueError('Finite recorded anchor required')
    return {'timing_contract': CONTRACT['contract_id'], 'measurement_start_epoch': anchor_epoch,
            'endpoint_epoch': anchor_epoch + HORIZON, 'horizon_seconds': HORIZON,
            'affects_native_outcome': False}


def require_current_scenario(scenario):
    if scenario in CONTRACT['historical_runtime_scenarios']:
        raise ValueError('Historical runtime scenario: use retained evidence, not the Phase 6 final profile; Phase 7 replacements required')


def native_terminal(directory):
    """Use the immutable native terminal; do not substitute collection completion."""
    path = Path(directory) / 'controller/controller-journal.jsonl'
    if not path.exists():
        return None
    ends = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ends = [e for e in ends if e.get('event') == 'controller_finished']
    if len(ends) != 1:
        return None
    stamp = datetime.datetime.fromisoformat(ends[0]['timestamp'].replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Native terminal timezone required')
    return stamp.timestamp()
