import copy
import tempfile
import unittest
from pathlib import Path

from app import Application
from zizai.core import Problem, diverse_candidates, make_plan, pools_for, seed_foods, nutrition
from zizai.reference import bundle, recipes, products
from test_app import profile, DAY


class MealExpansionTests(unittest.TestCase):
    def setUp(self):
        self.foods = {r['id']: r for r in seed_foods()}

    def test_recipe_totals_reconcile_to_source_components_and_no_duplicate_new_compositions(self):
        signatures = []
        for r in recipes():
            if not r['recipe_id'].startswith('m'):
                continue
            n = nutrition(r['ingredients'], self.foods)
            for key, field in [('kcal','kcal'),('protein','protein_g'),('carbs','carbs_g'),('fat','fat_g')]:
                self.assertAlmostEqual(n[key], r[field], delta=.051)
            self.assertTrue(r['order_tip'])
            self.assertIsNone(r['price_cny'])
            self.assertIsNone(r['preparation_minutes'])
            signatures.append(tuple(sorted((i['food_id'], i['grams']) for i in r['ingredients'])))
        self.assertEqual(len(signatures), 35)
        self.assertEqual(len(set(signatures)), 35)

    def test_profile_scenes_and_restrictions(self):
        for sources in [['delivery'], ['canteen'], ['home']]:
            for exclusions in [[], ['乳制品'], ['鱼'], ['虾蟹'], ['花生']]:
                with self.subTest(sources=sources, exclusions=exclusions):
                    p = profile(meal_sources=sources, exclusions=exclusions)
                    plan = make_plan(p, self.foods, DAY, 'demo')
                    self.assertTrue(all(c['passed'] for c in plan['checks']))
                    _, pools = pools_for(p, self.foods)
                    for meal in ['lunch','dinner']:
                        for o in pools[meal]:
                            self.assertLessEqual(len(o['id']), 40)
                            if o['id'].find('-brand-') >= 0:
                                self.assertIn('delivery', sources)
                                self.assertFalse(exclusions)
                            else:
                                self.assertTrue(all(not set(self.foods[i['food_id']]['tags']) & set(exclusions) for i in o['ingredients']))

    def test_small_seasonings_are_not_rounded_down_to_zero(self):
        _, pools = pools_for(profile(), self.foods)
        item = next(o for o in pools['lunch'] if o['id']=='lunch-ref-m11')
        salt = next(i for i in item['ingredients'] if i['food_id']=='salt')
        self.assertGreater(salt['grams'], 0)
        self.assertNotIn('0.0 小份', salt['portion'])

    def test_brand_quantities_are_fixed_and_calories_reconcile(self):
        _, pools = pools_for(profile(), self.foods)
        brands = {r['record_id']:r for r in products()}
        options = [o for o in pools['lunch'] if '-brand-' in o['id']]
        self.assertEqual(len(options), 5)
        for o in options:
            branded, *sides = o['ingredients']
            self.assertEqual(branded['quantity'], 1)
            self.assertNotIn('grams', branded)
            self.assertEqual(brands[branded['product_id']]['basis_unit'], 'serving')
            self.assertAlmostEqual(o['nutrition']['kcal'], brands[branded['product_id']]['kcal'] + nutrition(sides,self.foods)['kcal'], delta=.051)
            self.assertIn('自备', o['scene'])

    def test_diversity_selects_different_families_without_creating_options(self):
        _, pools = pools_for(profile(), self.foods)
        chosen = diverse_candidates(pools['lunch'])
        self.assertEqual(len({x['meal_family'] for x in chosen}), 3)
        self.assertTrue(all(o in pools['lunch'] for o in chosen))

    def test_filtered_refresh_preserves_selected_meal_and_swimming(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Application(Path(temp)/'test.sqlite3')
            app.mutate('PUT','/api/profile',{'profile':profile(),'expected_version':0})
            plan = app.mutate('POST','/api/plans/generate',{'date':DAY,'mode':'demo'})['plan']
            plan = app.mutate('POST','/api/activities/add',{'date':DAY,'expected_version':plan['version'],'kind':'swim','minutes':30})['plan']
            before = copy.deepcopy(plan)
            result = app.mutate('POST','/api/meals/refresh',{'date':DAY,'expected_version':plan['version'],'meal':'lunch','family':'米粉米线'})['plan']
            self.assertEqual({o['meal_family'] for o in result['meals']['lunch']['candidates']},{'米粉米线'})
            self.assertEqual(result['meals']['lunch']['selected'], before['meals']['lunch']['selected'])
            self.assertEqual(result['activities'], before['activities'])
            selected = result['meals']['lunch']['candidates'][0]
            adopted = app.mutate('POST','/api/meals/select',{'date':DAY,'expected_version':result['version'],'meal':'lunch','option_id':selected['id']})['plan']
            self.assertEqual(adopted['meals']['lunch']['selected']['id'], selected['id'])
            self.assertEqual(adopted['activities'], before['activities'])
            with self.assertRaises(Problem):
                app.mutate('POST','/api/meals/refresh',{'date':DAY,'expected_version':adopted['version'],'meal':'lunch','family':'不存在的类型'})
            self.assertEqual(app.store.plan(DAY), adopted)

    def test_six_refreshes_reach_different_types_without_repeating_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            app = Application(Path(temp)/'test.sqlite3')
            app.mutate('PUT','/api/profile',{'profile':profile(),'expected_version':0})
            plan=app.mutate('POST','/api/plans/generate',{'date':DAY,'mode':'demo'})['plan']
            seen = {o['id'] for o in plan['meals']['lunch']['candidates']}
            families = set()
            for _ in range(6):
                plan=app.mutate('POST','/api/meals/refresh',{'date':DAY,'expected_version':plan['version'],'meal':'lunch'})['plan']
                batch = plan['meals']['lunch']['candidates']
                self.assertFalse(seen & {o['id'] for o in batch})
                seen.update(o['id'] for o in batch)
                families.update(o['meal_family'] for o in batch)
            self.assertGreaterEqual(len(families), 6)


if __name__ == '__main__':
    unittest.main()
