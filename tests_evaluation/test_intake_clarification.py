"""Human clarification is an independent source, never inferred model semantics."""
from copy import deepcopy
import unittest

from evaluation.confirmed_demo import QUERY, fixture_client, fixture_proposal, fixture_response
from evaluation.confirmed_intent import (LLMProposalProvider, REVIEW_STATEMENT, prepare_intent,
    clarify_budget, confirm_intent, validate_confirmation)
from shopping_demo.confirmed import APPROXIMATE_QUERY, ConfirmedProduct


class ClarificationTests(unittest.TestCase):
    def review(self, budget):
        import json
        p = fixture_proposal()
        p['budget'].update(budget)
        client = fixture_client(lambda *args: fixture_response({'role': 'assistant', 'content': json.dumps(p)}))
        return prepare_intent(QUERY, LLMProposalProvider(client))

    def test_budget_answer_preserves_original_model_proposal_and_call(self):
        product = ConfirmedProduct(APPROXIMATE_QUERY)
        old = product.review()
        product.clarify(product.revision, '90.50')
        new = product.review()
        self.assertEqual(new['proposal'], old['proposal'])
        self.assertEqual(new['budget_clarification']['source_review'], old)
        self.assertEqual(new['proposal_usage'], old['proposal_usage'])
        self.assertEqual(len(product.client.records), 1)
        self.assertIn('90.50元', new['candidate_query'])
        self.assertEqual(new['proposal']['budget']['classification'], 'approximate_target')
        confirmed = confirm_intent(new, statement=REVIEW_STATEMENT, reviewer='offline-test')
        self.assertEqual(validate_confirmation(confirmed, APPROXIMATE_QUERY), new['candidate_query'])
        changed = deepcopy(confirmed)
        changed['review']['budget_clarification']['ceiling_cny'] = '900'
        with self.assertRaises(ValueError):
            validate_confirmation(changed)

    def test_range_soft_foreign_or_ambiguous_budget_cannot_be_overwritten(self):
        for budget in [{'classification': 'range', 'amounts': ['70', '100'], 'comparator': 'range'},
                       {'classification': 'soft_target', 'comparator': 'target'},
                       {'classification': 'approximate_target', 'currency': 'USD', 'approximate': True},
                       {'classification': 'ambiguous'}]:
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                clarify_budget(self.review(budget), '100')

    def test_invalid_answers_and_second_rewrite_are_rejected(self):
        original = ConfirmedProduct(APPROXIMATE_QUERY).review()
        for answer in ['', '0', '-1', 'NaN', '100左右', '90.123', 100, True]:
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                clarify_budget(original, answer)
        clarified = clarify_budget(original, '90')
        with self.assertRaises(ValueError):
            clarify_budget(clarified, '100')

    def test_snapshot_mutation_cannot_edit_server_confirmation(self):
        product = ConfirmedProduct(QUERY)
        state = product.state()
        product.confirm(state['revision'], state['review']['review_sha256'], True)
        snapshot = product.state()
        snapshot['confirmation']['review']['candidate_query'] = 'changed'
        snapshot['review']['proposal']['budget']['amounts'] = ['999']
        self.assertEqual(product.state()['review']['proposal']['budget']['amounts'], ['100'])
        self.assertNotEqual(product.state()['confirmation']['review']['candidate_query'], 'changed')


if __name__ == '__main__':
    unittest.main()
