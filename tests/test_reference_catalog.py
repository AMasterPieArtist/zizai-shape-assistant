import contextlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import Application
from zizai.core import Problem, pools_for
from zizai.reference import CATALOG_VERSION
from zizai.storage import Store
from test_app import profile, DAY


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'personal.sqlite3'
        self.app = Application(self.path)

    def generate(self, exclusions=None):
        self.app.mutate('PUT', '/api/profile', {'profile': profile(exclusions=exclusions or []), 'expected_version': 0})
        return self.app.mutate('POST', '/api/plans/generate', {'date': DAY, 'mode': 'demo'})['plan']

    def test_catalog_sources_and_candidate_expansion(self):
        info = self.app.get('/api/status', {})['catalog']
        self.assertEqual((info['foods'], info['products'], info['available_products'], info['recipes'], info['meal_templates']), (80, 46, 45, 54, 50))
        foods = self.app.store.foods()
        self.assertEqual(foods['beef']['source_record_id'], '171794')
        self.assertEqual(foods['beef']['kcal'], 230)
        self.assertEqual(foods['tofu']['source_record_id'], '172448')
        _, pools = pools_for(profile(), foods, self.app.store.recipes())
        self.assertEqual(len(pools['lunch']), 57)
        self.assertTrue(any(x['id'] == 'lunch-ref-r04' for x in pools['lunch']))
        self.assertEqual(len(pools['breakfast']), 11)

    def test_brand_portion_is_counted_and_swim_survives_restart(self):
        plan = self.generate()
        products = self.app.store.products()
        item = next(r for r in products if r['name_cn'] == '热奶铁' and r['portion_label'] == '中')
        result = self.app.mutate('POST', '/api/snacks/add', {'date': DAY, 'expected_version': plan['version'], 'snack_id': item['record_id']})['plan']
        self.assertEqual(result['snacks'][0]['nutrition']['kcal'], item['kcal'])
        self.assertIsNone(result['snacks'][0]['nutrition']['caffeine_mg'])
        self.assertEqual(result['totals'], plan['totals'])  # Extras are added separately, never deducted from meals.
        result = self.app.mutate('POST', '/api/activities/add', {'date': DAY, 'expected_version': result['version'], 'kind': 'swim', 'minutes': 30})['plan']
        self.assertEqual(Application(self.path).store.plan(DAY), result)

    def test_quarantined_product_never_selectable_and_unknown_remains_unknown(self):
        plan = self.generate()
        held = next(r for r in self.app.store.products() if r['calculation_use'] == 'hold_for_review')
        catalog = self.app.get('/api/snacks', {})['snacks']
        self.assertNotIn(held['record_id'], [r['id'] for r in catalog])
        self.assertIsNone(next(r for r in catalog if r['id'] == 'milk_tea')['nutrition'])
        with self.assertRaises(Problem):
            self.app.mutate('POST', '/api/snacks/add', {'date': DAY, 'expected_version': plan['version'], 'snack_id': held['record_id']})

    def test_unknown_brand_allergens_are_blocked(self):
        plan = self.generate(['乳制品'])
        product = next(r for r in self.app.get('/api/snacks', {})['snacks'] if r['id'].startswith('mcd_'))
        with self.assertRaises(Problem) as caught:
            self.app.mutate('POST', '/api/snacks/add', {'date': DAY, 'expected_version': plan['version'], 'snack_id': product['id']})
        self.assertEqual(caught.exception.code, 'exclusion_conflict')
        self.assertEqual(self.app.store.plan(DAY), plan)

    def test_migration_backs_up_and_preserves_all_personal_rows(self):
        plan = self.generate()
        plan = self.app.mutate('POST', '/api/activities/add', {'date': DAY, 'expected_version': plan['version'], 'kind': 'swim', 'minutes': 30})['plan']
        self.app.mutate('POST', '/api/adjustments', {'date': DAY, 'expected_version': plan['version'], 'mode': 'demo', 'request': '今晚加班，不想运动'})
        def snapshot(db):
            return {t: db.execute('SELECT * FROM ' + t + ' ORDER BY rowid').fetchall() for t in ['profiles', 'plans', 'adjustments', 'events']}
        # Emulate the pre-catalog schema while retaining genuine saved personal data.
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            for t in ['catalog_meta', 'reference_products', 'recipe_templates']:
                db.execute('DROP TABLE ' + t)
            db.execute("UPDATE foods SET data=? WHERE id='tofu'", (json.dumps({'id': 'tofu', 'kcal': 144}),))
            db.commit()
            before = snapshot(db)
        migrated = Store(self.path)
        with contextlib.closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(snapshot(db), before)
        backup = Path(migrated.catalog_info()['backup_path'])
        self.assertTrue(backup.exists())
        with contextlib.closing(sqlite3.connect(backup)) as db:
            self.assertEqual(snapshot(db), before)
            self.assertEqual(json.loads(db.execute("SELECT data FROM foods WHERE id='tofu'").fetchone()[0])['kcal'], 144)
        self.assertEqual(migrated.plan(DAY), plan)
        self.assertEqual(migrated.catalog_info()['version'], CATALOG_VERSION)
        Store(self.path)
        self.assertEqual(len(list(backup.parent.glob('*.sqlite3'))), 1)

    def test_invalid_bundle_leaves_database_untouched(self):
        before = self.path.read_bytes()
        with patch('zizai.reference.recipes', side_effect=ValueError('bad components')):
            with self.assertRaises(ValueError):
                Store(self.path)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
