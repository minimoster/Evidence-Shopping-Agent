"""Recheck a recorded C-arm gate trace offline; never re-execute tools or models.

This verifies internal consistency, not authenticity or simulator success.
"""
import argparse
import json
from prototype import EvidenceLedger, verify_purchase
from .constraints import compile_query


def verify_gate_replay(row):
    trajectory = row['trajectory']
    initial = trajectory['initial_result']
    compilation = compile_query(initial['instruction'])
    ledger = EvidenceLedger()
    state = initial['observation_state']
    ledger.ingest(state)
    events = iter(row['gate_events'])
    checked = 0
    for step in trajectory['steps']:
        if row['arm'] == 'C' and step['tool_name'] == 'buy_now':
            event = next(events, None)
            function = (step.get('tool_call') or {}).get('function') or {}
            arguments = function.get('arguments', '{}')
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if (event is None or event.get('index') != checked or
                event.get('action') != 'click[Buy Now]' or step.get('env_action') != 'click[Buy Now]' or
                function.get('name') != 'buy_now' or arguments != {} or event['observation_state'] != state):
                raise ValueError('gate event missing or bound to different observation')
            decision = verify_purchase(compilation.requirements, ledger,
                intended_asin=(state.get('product') or {}).get('asin', ''),
                intended_options=state.get('selected_options', {}))
            if event['decision'] != decision.to_dict():
                raise ValueError('gate decision mismatch')
            rejected = bool(step['result'].get('gate_rejected'))
            execution_uncertain = (decision.allowed and not rejected and
                bool(step.get('error')) and event['executed'] is None)
            if not execution_uncertain and (event['executed'] != decision.allowed or rejected == decision.allowed):
                raise ValueError('gate execution mismatch')
            checked += 1
        result = step.get('result') or {}
        if result.get('observation_state') is not None:
            state = result['observation_state']
            ledger.ingest(state)
    if next(events, None) is not None:
        raise ValueError('unmatched gate event')
    return {'gate_decisions_checked': checked, 'consistent': True,
            'execution_kind': row['execution_kind'], 'authenticity_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace')
    args = parser.parse_args()
    with open(args.trace, encoding='utf-8') as stream:
        print(json.dumps(verify_gate_replay(json.load(stream)), ensure_ascii=False))

if __name__ == '__main__':
    main()
