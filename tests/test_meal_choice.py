"""User choice regressions; synthetic profiles and disposable databases only."""
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
from zizai.core import Problem, pools_for, validate_plan


class MealChoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'test.sqlite3'
        self.app = Application(self.database)
        self.configure(profile(meal_sources=['canteen'], ai_consent=True))

    def configure(self, p):
        existing = self.app.store.profile()
        self.app.mutate('PUT', '/api/profile', {'profile': p, 'expected_version': existing['version'] if existing else 0})
        old = self.app.store.plan(DAY)
        self.plan = self.app.mutate('POST', '/api/plans/generate', {'date': DAY, 'mode': 'demo', 'expected_version': old['version'] if old else 0})['plan']

    def call(self, path, **kwargs):
        return self.app.mutate('POST', '/api/meals/' + path,
                               dict(date=DAY, expected_version=self.plan['version'], meal='lunch', **kwargs))

    def optional(self, enabled):
        self.plan = self.app.mutate('POST', '/api/meals/optional',
            dict(date=DAY, expected_version=self.plan['version'], meal='snack', enabled=enabled))['plan']
        return self.plan

    def test_search_by_name_ingredient_and_pagination_is_read_only(self):
        before = self.app.store.export()
        a = self.call('search', query='', limit=6)
        b = self.call('search', query='', offset=6, limit=6)
        self.assertTrue(a['has_more'])
        self.assertEqual(a['total'], b['total'])
        self.assertFalse({o['id'] for o in a['options']} & {o['id'] for o in b['options']})
        result = self.call('search', query='米粉', limit=12)
        self.assertTrue(result['options'])
        for o in result['options']:
            self.assertIn('米粉', o['title'] + ''.join(i['name'] for i in o['ingredients']) + o['meal_family'])
        self.assertEqual(self.call('search', query='不存在的菜名')['options'], [])
        self.assertEqual(self.app.store.export(), before)

    def test_choose_search_result_outside_current_batch_and_persist(self):
        current = {o['id'] for o in self.plan['meals']['lunch']['candidates']}
        result = self.call('search', query='', exclude_ids=list(current))
        selected = result['options'][0]
        with self.assertRaises(Problem):
            self.call('select', option_id=selected['id'])
        self.plan = self.call('select', selection_source='catalog', option_id=selected['id'])['plan']
        saved = Application(self.database).store.plan(DAY)
        self.assertEqual(saved['meals']['lunch']['selected'], selected)
        self.assertEqual(saved['version'], self.plan['version'])

    def test_takeout_overrides_only_search_scene_and_does_not_change_selected(self):
        before = copy.deepcopy(self.plan)
        a = self.call('search', scene='delivery', limit=3)
        b = self.call('search', scene='delivery', limit=3, exclude_ids=[o['id'] for o in a['options']])
        self.assertFalse({o['id'] for o in a['options']} & {o['id'] for o in b['options']})
        brand = self.call('search', scene='delivery', query='汉堡', limit=12)['options'][0]
        self.assertIn('-brand-', brand['id'])
        self.assertEqual(self.app.store.plan(DAY), before)
        self.plan = self.call('select', scene='delivery', selection_source='catalog', option_id=brand['id'])['plan']
        self.assertEqual(self.app.store.profile()['data']['meal_sources'], ['canteen'])
        self.assertEqual(self.plan['meals']['lunch']['selected']['id'], brand['id'])

    def test_allergen_search_and_selection_cannot_bypass_constraints(self):
        unsafe = self.call('search', scene='delivery', query='鱼', limit=12)['options'][0]['id']
        self.configure(profile(exclusions=['鱼'], meal_sources=['canteen']))
        self.assertEqual(self.call('search', scene='delivery', query='鱼', limit=12)['options'], [])
        before = copy.deepcopy(self.plan)
        with self.assertRaises(Problem):
            self.call('select', scene='delivery', selection_source='catalog', option_id=unsafe)
        self.assertEqual(self.app.store.plan(DAY), before)

    def test_completed_meal_cannot_be_replaced_from_search_and_unknown_id_rejected(self):
        candidate = self.call('search', query='', offset=6)['options'][0]
        with self.assertRaises(Problem):
            self.call('select', selection_source='catalog', option_id='made-up')
        self.plan = self.call('complete', completed=True)['plan']
        with self.assertRaises(Problem) as exc:
            self.call('select', selection_source='catalog', option_id=candidate['id'])
        self.assertEqual(exc.exception.code, 'meal_completed')

    def test_search_version_and_paging_validation(self):
        for invalid in ({'offset': -1}, {'limit': 100}, {'query': 'x' * 61}, {'exclude_ids': 'not-a-list'}, {'scene': 'arbitrary'}):
            with self.subTest(invalid=invalid), self.assertRaises(Problem):
                self.call('search', **invalid)
        self.plan = self.call('complete', completed=True)['plan']
        with self.assertRaises(Problem) as exc:
            self.app.mutate('POST', '/api/meals/search', dict(date=DAY, expected_version=self.plan['version'] - 1, meal='lunch'))
        self.assertEqual(exc.exception.code, 'conflict')

    def test_optional_removal_and_restore_exact_nutrition_and_other_entries(self):
        self.plan = self.app.mutate('POST', '/api/activities/add', dict(date=DAY, expected_version=self.plan['version'], kind='swim', minutes=30))['plan']
        self.plan['snacks'] = [{'entry_id': 'test-extra', 'name': '已添加的小食', 'nutrition': {'kcal': 100}}]
        self.plan = self.app.store.save_plan(self.plan, self.plan['version'], self.app.store.profile(), 'test_setup', {})
        before = copy.deepcopy(self.plan)
        self.optional(False)
        for k, v in before['meals']['snack']['selected']['nutrition'].items():
            self.assertAlmostEqual(self.plan['totals'][k], round(before['totals'][k] - v, 1), delta=.11)
        for meal in ('breakfast', 'lunch', 'dinner'):
            self.assertEqual(self.plan['meals'][meal], before['meals'][meal])
        self.assertEqual(self.plan['activities'], before['activities'])
        self.assertEqual(self.plan['snacks'], before['snacks'])
        self.assertFalse(Application(self.database).store.plan(DAY)['meals']['snack']['enabled'])
        self.optional(True)
        self.assertEqual(self.plan['totals'], before['totals'])
        self.assertEqual(self.plan['meals']['snack']['selected'], before['meals']['snack']['selected'])

    def test_optional_low_reference_is_honest_and_does_not_force_more_food(self):
        self.configure(profile(age=40, height_cm=150, current_weight_kg=45, target_weight_kg=45))
        self.assertEqual(self.plan['reference']['midpoint'], 1600)
        before = copy.deepcopy(self.plan)
        self.optional(False)
        self.assertLess(self.plan['totals']['kcal'], 1500)
        checks = {c['name']: c['passed'] for c in self.plan['checks']}
        self.assertFalse(checks['原型最低能量护栏'])
        self.assertIn('未达到', self.plan['optional_snack_note'])
        self.assertEqual(self.plan['meals']['dinner'], before['meals']['dinner'])
        # Opt-out must not permit an otherwise invalid generated composition.
        tampered = copy.deepcopy(self.plan)
        tampered['meals']['lunch']['selected']['nutrition']['kcal'] = 0
        with self.assertRaises(Problem):
            validate_plan(tampered, self.app.store.profile()['data'])

    def test_disabled_snack_cannot_be_completed_or_reselected_or_refreshed(self):
        self.optional(False)
        for endpoint, extra in [('complete', {'completed': True}), ('select', {'selection_source': 'catalog', 'option_id': 'snack-1'}), ('refresh', {})]:
            with self.subTest(endpoint=endpoint), self.assertRaises(Problem) as exc:
                self.app.mutate('POST', '/api/meals/' + endpoint, dict(date=DAY, expected_version=self.plan['version'], meal='snack', **extra))
            self.assertEqual(exc.exception.code, 'meal_disabled')

    def test_demo_milk_tea_does_not_restore_cancelled_snack_or_replace_dinner(self):
        self.optional(False)
        before = copy.deepcopy(self.plan)
        with self.assertRaises(Problem) as exc:
            self.app.mutate('POST', '/api/adjustments', dict(date=DAY,
                expected_version=self.plan['version'], mode='demo', request='下午想喝奶茶'))
        self.assertEqual(exc.exception.code, 'meal_disabled')
        self.assertEqual(self.app.store.plan(DAY), before)

    def test_completed_optional_cannot_be_removed_and_old_flag_absence_is_supported(self):
        self.plan = self.app.mutate('POST', '/api/meals/complete', dict(date=DAY, expected_version=self.plan['version'], meal='snack', completed=True))['plan']
        with self.assertRaises(Problem):
            self.optional(False)
        old = copy.deepcopy(self.plan)
        for m in old['meals'].values():
            m.pop('enabled', None)
        validate_plan(old, self.app.store.profile()['data'])
        self.assertEqual(old['totals'], self.plan['totals'])

    def test_model_gets_disabled_state_and_cannot_change_optional_snack(self):
        self.optional(False)
        p = self.app.store.profile()['data']
        ref, pools = pools_for(p, self.app.store.foods())
        data = dict(blocked=False, choices={'snack': pools['snack'][1]['id']}, message='调整安排。', rest=False)
        def response():
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(data)}}]}).encode())
        before = self.app.store.export()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only'}), patch('urllib.request.urlopen', side_effect=[response(), response()]) as network:
            with self.assertRaises(Problem) as exc:
                deepseek.recommend(p, pools, ref, '改一下今天的安排', self.plan)
        self.assertIn('已取消', str(exc.exception))
        context = json.loads(json.loads(network.call_args[0][0].data)['messages'][1]['content'])
        self.assertFalse(context['current_plan']['snack']['enabled'])
        self.assertEqual(self.app.store.export(), before)


if __name__ == '__main__':
    unittest.main()
