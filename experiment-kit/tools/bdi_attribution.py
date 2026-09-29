"""Separate native controller decisions from passive outcomes without rewriting evidence."""
from collections import Counter
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


def instant(value):
    if not isinstance(value, str):
        raise ValueError('Timestamp must be a string')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('Timestamp has no timezone')
    # Native Java timestamps have nanoseconds; do not round a post-terminal
    # event into the accepted boundary via Python's microsecond datetime.
    fraction = re.search(r'T\d{2}:\d{2}:\d{2}(?:\.(\d+))?', value)
    if not fraction:
        raise ValueError('Expected ISO event timestamp')
    return Decimal(int(stamp.replace(microsecond=0).timestamp())) + Decimal('0.'+(fraction.group(1) or '0'))


def classify(journal, passive):
    starts = [e for e in journal if e.get('event') == 'controller_started']
    ends = [e for e in journal if e.get('event') == 'controller_finished']
    counts = Counter()
    excluded = []
    start = end = None
    complete = False
    try:
        if len(starts) == len(ends) == 1:
            start, end = instant(starts[0]['timestamp']), instant(ends[0]['timestamp'])
            complete = start <= end
        for e in journal:
            stamp = instant(e['timestamp'])
            if complete and start <= stamp <= end:
                counts[e.get('event', 'unknown')] += 1
                if e.get('event') == 'bdi_decision':
                    counts['decision:'+str(e.get('decision'))] += 1
            elif e.get('event') not in ('controller_started','controller_finished'):
                excluded.append({'timestamp': e['timestamp'], 'event': e.get('event'), 'reason': 'outside_or_unknown_controller_horizon'})
    except (KeyError, TypeError, ValueError):
        complete = False
    after = unknown = 0
    for event in passive:
        try:
            if not complete:
                unknown += 1
            elif instant(event['timestamp']) > end:
                after += 1
        except (KeyError, TypeError, ValueError):
            unknown += 1
    return {'schema_version': 1, 'controller_horizon_complete': complete,
            'controller_started_at': starts[0].get('timestamp') if len(starts)==1 else None,
            'controller_finished_at': ends[0].get('timestamp') if len(ends)==1 else None,
            'native_in_horizon_event_counts': dict(counts) if complete else None,
            'excluded_native_events': excluded,
            'passive_measurement': {'role': 'EXPERIMENT MEASUREMENT', 'samples': len(passive),
                'post_controller_samples': after if complete else None, 'unbounded_or_invalid_samples': unknown,
                'attributed_to_bdi': False},
            'rule': 'Only native controller journal events within known controller bounds may support BDI decisions. Passive samples never do, even during execution. Counts do not establish recovery success or causality.'}


def report(directory):
    directory = Path(directory)
    errors = []
    hashes = {}
    def read_lines(relative):
        path = directory/relative
        if not path.exists():
            return []
        try:
            raw = path.read_bytes()
            hashes[relative] = hashlib.sha256(raw).hexdigest()
            events = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
            if any(not isinstance(e,dict) for e in events):
                raise ValueError('Event must be an object')
            return events
        except (OSError, ValueError) as exc:
            errors.append(relative+': '+type(exc).__name__)
            return []
    result = classify(read_lines('controller/controller-journal.jsonl'), read_lines('common-observations.jsonl'))
    result['read_errors'] = errors
    result['source_sha256'] = hashes
    result['native_directory'] = str(directory)
    result['endpoint_evidence'] = {'role': 'EXPERIMENT MEASUREMENT', 'path': str(directory/'endpoint.json'),
                                 'exists': (directory/'endpoint.json').exists(), 'attributed_to_bdi': False}
    result['legacy_record'] = {'path': str(directory/'record.json'), 'bdi_attribution_authority': False}
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('native_directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.native_directory), indent=2))
