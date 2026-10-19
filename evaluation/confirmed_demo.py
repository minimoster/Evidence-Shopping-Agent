"""Offline HTTP-shaped fixtures exercising intake, confirmation and ABC recovery.

All interpretations and decisions below are hand-authored, not LLM outputs.
No network, credentials, real corpus or real simulator is used.
"""
import argparse
import hashlib
import json

from .confirmed_intent import LLMProposalProvider, prepare_intent, confirm_intent, REVIEW_STATEMENT
from .confirmed_runner import run_confirmed_comparison
from .intent_proposals import SCHEMA
from .model_adapter import ModelClient, ModelConfig

QUERY = '帮我挑一副黑色耳机，最多花100元人民币。'


def fixture_proposal(query=QUERY):
    return {'schema': SCHEMA, 'query_sha256': hashlib.sha256(query.encode()).hexdigest(),
            'segments': [{'start': 0, 'end': len(query), 'text': query, 'role': 'constraint'}],
            'predicates': [{'kind': 'exact', 'key': key, 'operator': 'eq', 'values': [value],
                            'unit': None, 'strength': 'hard', 'source_spans': [0]}
                           for key, value in [('category', '耳机'), ('color', '黑色')]],
            'budget': {'classification': 'explicit_ceiling', 'amounts': ['100'], 'currency': 'CNY',
                       'comparator': 'le', 'approximate': False, 'source_spans': [0]}}


def fixture_response(message, model='offline-fixture'):
    return {'model': model, 'choices': [{'message': message, 'finish_reason':
            'tool_calls' if message.get('tool_calls') else 'stop'}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 8}}


def scripted_transport(endpoint, payload, headers, timeout):
    if payload.get('response_format'):
        message = {'role': 'assistant', 'content': json.dumps(fixture_proposal(), ensure_ascii=False)}
    else:
        last = payload['messages'][-1].get('content') or ''
        name, args = ('select_option', {'value': '黑色'}) if 'Evidence gate rejected' in last else ('buy_now', {})
        message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'offline-action',
                    'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}
    return fixture_response(message, payload['model'])


class SyntheticStore:
    def __init__(self, **kwargs):
        self.color = '白色'
        self.actions = []
        self.released = False

    def state(self):
        return {'observation_version': 'shopping-observation-v2', 'page_type': 'product_detail',
                'search_available': False, 'actions': ['Buy Now', '白色', '黑色'],
                'product': {'asin': '000000000101', 'category': '耳机', 'title': '原创合成测试',
                            'brand': '测试', 'key_attributes': [], 'price': '79'},
                'selected_price': '79', 'selected_options': {'颜色': self.color},
                'available_options': {'颜色': ['白色', '黑色']}}

    def reset(self, task_id):
        return {'instruction': QUERY, 'observation_state': self.state()}

    def step(self, action):
        self.actions.append(action)
        if action == 'click[黑色]':
            self.color = '黑色'
        done = action == 'click[Buy Now]'
        good = self.color == '黑色'
        state = ({'observation_version': 'shopping-observation-v2', 'page_type': 'terminal',
                  'search_available': False, 'actions': []} if done else self.state())
        return {'observation_state': state, 'done': done, 'over': done, 'reward': int(good),
                'reward_detail': {'reward_version': 'shopsimulator-reward-v3', 'reward_valid': True,
                 'reward_type': 'gold_purchase' if good else 'wrong_purchase',
                 'termination_reason': 'gold_purchase' if good else 'wrong_purchase', 'purchase_success': good}}

    def release(self):
        self.released = True


def fixture_client(transport=scripted_transport, **overrides):
    values = dict(endpoint='https://example.invalid/v1/chat/completions', model='offline-fixture',
                  max_requests=10, max_reserved_usd='1.00', per_request_reserve_usd='0.01')
    values.update(overrides)
    return ModelClient(ModelConfig(**values), transport=transport)


def run_demo(output_dir):
    client = fixture_client()
    review = prepare_intent(QUERY, LLMProposalProvider(client))
    confirmation = confirm_intent(review, statement=REVIEW_STATEMENT, reviewer='offline_fixture_not_a_human')
    result = run_confirmed_comparison(1, confirmation, client, max_steps=3,
        max_model_calls_per_arm=4, env_factory=SyntheticStore, output_dir=output_dir)
    client.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.output_dir)['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
