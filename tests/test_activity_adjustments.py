"""Regressions: actual exercise entries must participate in confirmed drafts."""
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Application
from test_app import DAY, profile
from zizai import deepseek
from zizai.core import Problem, adjusted_plan, make_plan, pools_for, seed_foods


class ActivityAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.p = profile(ai_consent=True)
        self.foods = {f['id']: f for f in seed_foods()}
        self.plan = make_plan(self.p, self.foods, DAY, 'demo')
        self.plan['activities'] = [
            {'entry_id': 'swim-id', 'kind': 'swim', 'name': '休闲游泳', 'minutes': 30},
            {'entry_id': 'walk-id', 'kind': 'walk', 'name': '中速步行', 'minutes': 10},
        ]

    def ai(self, **changes):
        value = dict(choices={}, message='按你的要求取消游泳，其他安排保留。', rest=False,
                     activity_action={'type': 'remove', 'entry_ids': ['swim-id']}, model='test-model')
        value.update(changes)
        return value

    def test_ai_only_removes_selected_activity_and_preserves_meals_and_input(self):
        before = copy.deepcopy(self.plan)
        result, _, changes = adjusted_plan(self.plan, self.p, self.foods, '取消游泳，步行保留', 'deepseek', self.ai())
        self.assertEqual(self.plan, before)
        self.assertEqual(result['activities'], [before['activities'][1]])
        self.assertEqual(result['meals'], before['meals'])
        self.assertIn('运动安排', changes)

    def test_rest_advice_does_not_delete_activities(self):
        result, _, changes = adjusted_plan(self.plan, self.p, self.foods, '今天累了，有什么建议', 'deepseek',
            self.ai(rest=True, activity_action={'type': 'keep', 'entry_ids': []}))
        self.assertEqual(result['activities'], self.plan['activities'])
        self.assertNotIn('运动安排', changes)

    def test_demo_specific_removal_and_negative_request(self):
        for request, remaining in [('取消游泳，步行保留', ['walk-id']), ('今天不想运动', []),
                                   ('今天加班，不要取消游泳', ['swim-id', 'walk-id'])]:
            with self.subTest(request=request):
                result, _, _ = adjusted_plan(self.plan, self.p, self.foods, request, 'demo')
                self.assertEqual([a['entry_id'] for a in result['activities']], remaining)

    def response(self, action):
        data = dict(blocked=False, choices={}, message='按你的要求调整运动，其他安排保留。',
                    rest=False, activity_action=action)
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(data)}}]}).encode())

    def test_model_context_has_ids_and_accepts_empty_meal_choices(self):
        ref, pools = pools_for(self.p, self.foods)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only'}), patch('urllib.request.urlopen',
            return_value=self.response({'type': 'remove', 'entry_ids': ['swim-id']})) as network:
            result = deepseek.recommend(self.p, pools, ref, '取消游泳', self.plan)
        context = json.loads(json.loads(network.call_args[0][0].data)['messages'][1]['content'])
        self.assertEqual(context['activities'][0]['entry_id'], 'swim-id')
        self.assertEqual(result['choices'], {})
        self.assertEqual(result['activity_action']['entry_ids'], ['swim-id'])

    def test_unknown_or_malformed_activity_actions_are_rejected(self):
        ref, pools = pools_for(self.p, self.foods)
        for action in ({'type': 'remove', 'entry_ids': ['invented-id']},
                       {'type': 'remove', 'entry_ids': ['swim-id', 'swim-id']},
                       {'type': 'keep', 'entry_ids': ['swim-id']},
                       {'type': 'remove', 'entry_ids': []}, {'type': 'clear', 'entry_ids': []}):
            with self.subTest(action=action), patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only'}), \
                 patch('urllib.request.urlopen', side_effect=[self.response(action), self.response(action)]):
                with self.assertRaises(Problem) as caught:
                    deepseek.recommend(self.p, pools, ref, '取消游泳', self.plan)
                self.assertEqual(caught.exception.code, 'invalid_model_output')

    def test_confirm_discard_restart_and_stale_draft(self):
        for confirm in (False, True):
            with self.subTest(confirm=confirm), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'test.sqlite3'
                app = Application(path)
                app.mutate('PUT', '/api/profile', {'profile': self.p, 'expected_version': 0})
                plan = app.mutate('POST', '/api/plans/generate', {'date': DAY, 'mode': 'demo'})['plan']
                for kind in ('swim', 'walk'):
                    plan = app.mutate('POST', '/api/activities/add', dict(date=DAY, expected_version=plan['version'], kind=kind, minutes=30))['plan']
                ai = self.ai(activity_action={'type': 'remove', 'entry_ids': [plan['activities'][0]['entry_id']]})
                with patch('zizai.deepseek.recommend', return_value=ai):
                    draft = app.mutate('POST', '/api/adjustments', dict(date=DAY, expected_version=plan['version'], mode='deepseek', request='取消游泳，步行保留'))['adjustment']
                self.assertEqual(app.store.plan(DAY), plan)
                action = 'confirm' if confirm else 'discard'
                app.mutate('POST', f"/api/adjustments/{draft['id']}/{action}", {})
                saved = Application(path).store.plan(DAY)
                self.assertEqual(saved['activities'], [plan['activities'][1]] if confirm else plan['activities'])
                self.assertEqual(saved['meals'], plan['meals'])
                if confirm:
                    with self.assertRaises(Problem):
                        app.mutate('POST', f"/api/adjustments/{draft['id']}/confirm", {})


if __name__ == '__main__':
    unittest.main()
