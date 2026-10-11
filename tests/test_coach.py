"""Grounded companion feedback, profile separation and preferences persistence."""
import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from app import Application
from test_app import DAY, profile
from zizai.coach import companion_card, history_window, profile_scope
from zizai.core import Problem, make_plan, seed_foods


class CoachHistoryTests(unittest.TestCase):
    def setUp(self):
        self.today = dt.date(2026, 10, 11)
        self.p = {'version': 1, 'data': profile()}
        foods = {f['id']: f for f in seed_foods()}
        self.plan = make_plan(self.p['data'], foods, '2026-10-11', 'demo')
        self.plan['profile_version'] = 1

    def row(self, day, completed=False, data=None):
        value = copy.deepcopy(self.plan)
        value['date'] = day
        value['meals']['lunch']['completed'] = completed
        return {'date': day, 'data': value, 'profile_snapshot': data or copy.deepcopy(self.p['data'])}

    def card(self, history, plan=None, day='2026-10-11'):
        return companion_card(self.p, self.plan if plan is None else plan, history, day, today=self.today)

    def test_generated_plans_do_not_claim_execution(self):
        rows = [self.row(f'2026-10-{d:02d}') for d in [7, 8, 9]]
        card = self.card(rows)
        self.assertEqual(card['stats'], {'planned_days': 3, 'completed_days': 0, 'completed_meals': 0})
        self.assertIn('保存过饮食安排', card['progress'])
        self.assertNotIn('标记过餐次完成', card['progress'])

    def test_weekly_completion_is_based_on_marks_and_excludes_future_and_old_days(self):
        rows = [self.row(f'2026-10-{d:02d}', completed=True) for d in [4, 7, 8, 9, 12]]
        card = self.card(rows)
        self.assertEqual(card['stats']['completed_days'], 3)
        self.assertIn('3 天标记过餐次完成', card['progress'])
        self.assertIn('不推断实际', card['record_note'])
        future = self.card(rows, day='2026-10-20')
        self.assertEqual(future['window']['end'], '2026-10-11')
        self.assertEqual(future['stats']['completed_days'], 3)

    def test_changed_test_profiles_cannot_share_history_but_consent_does_not_reset(self):
        b = profile(nickname='另一个测试用户', preferences='喜欢豆腐')
        same = dict(self.p['data'], ai_consent=not self.p['data']['ai_consent'])
        rows = [self.row('2026-10-08', True, b), self.row('2026-10-09', True, same)]
        card = self.card(rows)
        self.assertEqual(card['stats']['planned_days'], 1)
        self.assertEqual(card['stats']['completed_days'], 1)
        self.assertNotEqual(profile_scope(b), profile_scope(self.p['data']))
        self.assertEqual(profile_scope(same), profile_scope(self.p['data']))

    def test_optional_disabled_meal_does_not_count_as_completed(self):
        r = self.row('2026-10-09')
        r['data']['meals']['snack'].update(enabled=False, completed=True)
        card = self.card([r])
        self.assertEqual(card['stats']['completed_meals'], 0)

    def test_no_plan_stale_profile_and_optional_rest_have_relevant_actions(self):
        card = companion_card(self.p, None, [], '2026-10-11', today=self.today)
        self.assertEqual(card['cta']['action'], 'generate')
        stale = copy.deepcopy(self.plan)
        stale['profile_version'] = 0
        self.assertEqual(self.card([], stale)['kind'], 'profile_changed')
        off = copy.deepcopy(self.plan)
        off['meals']['snack']['enabled'] = False
        self.assertEqual(self.card([], off)['cta']['route'], 'snacks')
        self.assertEqual(history_window('2026-10-08', self.today), ('2026-10-02', '2026-10-08'))


class CoachPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.app = Application(self.path)

    def save_profile(self, p):
        old = self.app.store.profile()
        return self.app.mutate('PUT', '/api/profile', {'profile': p, 'expected_version': old['version'] if old else 0})['profile']

    def preference(self, p, collapsed):
        return self.app.mutate('POST', '/api/coach/preferences', {'date': DAY, 'expected_profile_version': p['version'], 'collapsed': collapsed})['coach']

    def test_no_profile_returns_no_card_and_no_model_network_is_used(self):
        from unittest.mock import patch
        with patch('urllib.request.urlopen') as network:
            self.assertIsNone(self.app.get('/api/coach', {'date': [DAY]})['coach'])
            self.save_profile(profile())
            self.assertEqual(self.app.get('/api/coach', {'date': [DAY]})['coach']['source'], 'local_records')
        network.assert_not_called()

    def test_collapse_persists_scopes_to_profile_and_does_not_change_plan(self):
        p = self.save_profile(profile())
        plan = self.app.mutate('POST', '/api/plans/generate', {'date': DAY})['plan']
        self.preference(p, True)
        self.assertEqual(self.app.store.plan(DAY), plan)
        restarted = Application(self.path)
        self.assertTrue(restarted.get('/api/coach', {'date': [DAY]})['coach']['collapsed'])
        q = self.save_profile(profile(nickname='画像B'))
        self.assertFalse(self.app.get('/api/coach', {'date': [DAY]})['coach']['collapsed'])
        with self.assertRaises(Problem):
            self.preference(p, False)
        self.assertFalse(self.preference(q, False)['collapsed'])
        p = self.save_profile(profile())
        self.assertTrue(self.app.get('/api/coach', {'date': [DAY]})['coach']['collapsed'])
        self.assertFalse(self.preference(p, False)['collapsed'])

    def test_current_profile_statistics_and_completion_toggle_do_not_inflate_history(self):
        self.save_profile(profile())
        plan = self.app.mutate('POST', '/api/plans/generate', {'date': DAY})['plan']
        for completed in [True, False, True]:
            plan = self.app.mutate('POST', '/api/meals/complete', {'date': DAY, 'meal': 'lunch', 'expected_version': plan['version'], 'completed': completed})['plan']
        card = self.app.get('/api/coach', {'date': [DAY]})['coach']
        self.assertEqual(card['stats']['completed_days'], 1)
        self.assertEqual(card['stats']['completed_meals'], 1)
        self.save_profile(profile(preferences='另一个测试画像的口味'))
        card = self.app.get('/api/coach', {'date': [DAY]})['coach']
        self.assertEqual(card['stats']['planned_days'], 0)
        self.assertEqual(card['kind'], 'profile_changed')

    def test_export_and_delete_include_preferences_and_keep_reference_foods(self):
        p = self.save_profile(profile())
        self.preference(p, True)
        data = self.app.get('/api/export', {})
        self.assertEqual(len(data['coach_preferences']), 1)
        self.assertTrue(data['coach_preferences'][0]['collapsed'])
        self.app.mutate('POST', '/api/data/delete', {'confirmation': '删除我的本地数据'})
        self.assertEqual(self.app.get('/api/export', {})['coach_preferences'], [])
        self.assertIsNone(self.app.get('/api/coach', {'date': [DAY]})['coach'])
        self.assertTrue(self.app.store.foods())

    def test_invalid_preference_is_rejected_without_changes(self):
        p = self.save_profile(profile())
        for value in ['true', 1, None]:
            with self.subTest(value=value), self.assertRaises(Problem):
                self.preference(p, value)
        self.assertEqual(self.app.get('/api/export', {})['coach_preferences'], [])


if __name__ == '__main__':
    unittest.main()
