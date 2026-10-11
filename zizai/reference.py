"""Versioned, offline reference bundle. SQLite receives a validated copy at startup."""
import copy
import json
import math
from functools import lru_cache
from pathlib import Path

BUNDLE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'reference' / 'dataset-v1.json'
CATALOG_VERSION = 'food-catalog-v2.0-20261011'


def food_id(row):
    return {'usda_olive_oil': 'oil', 'usda_beef_cooked': 'beef'}.get(
        row['record_id'], row.get('compatible_app_id') or row['record_id'].removeprefix('usda_'))


def checked_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid reference nutrient: ' + name)
    return value


@lru_cache(maxsize=1)
def bundle():
    data = json.loads(BUNDLE_PATH.read_text(encoding='utf-8'))
    ids = set()
    for row in data['foods_generic']:
        fid = food_id(row)
        if fid in ids or row['basis_amount'] != 100 or row['basis_unit'] != 'g':
            raise ValueError('Invalid reference food identity/basis')
        ids.add(fid)
        for field in ('kcal', 'protein_g', 'carbs_g', 'fat_g'):
            checked_number(row[field], field)
        if not row['source_url'].startswith('https://fdc.nal.usda.gov/'):
            raise ValueError('Invalid food source')
    products = set()
    for row in data['products_cn']:
        if row['record_id'] in products or row['basis_amount'] != 1 or row['basis_unit'] != 'serving':
            raise ValueError('Invalid product identity/basis')
        products.add(row['record_id'])
        for field in ('kcal', 'protein_g', 'carbs_g', 'fat_g'):
            checked_number(row[field], field)
        if not row['source_url'].startswith('https://www.mcdonalds.com.cn/product/'):
            raise ValueError('Invalid product source')
    recipe_ids = [r['recipe_id'] for r in data['recipes_estimated']]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError('Duplicate recipe identity')
    record_ids = {r['record_id'] for r in data['foods_generic']}
    for row in data['recipe_components']:
        if row['recipe_id'] not in recipe_ids or row['food_record_id'] not in record_ids:
            raise ValueError('Unknown recipe component')
        if checked_number(row['amount_g'], 'amount_g') == 0:
            raise ValueError('Empty recipe component')
    if any(not any(c['recipe_id'] == r for c in data['recipe_components']) for r in recipe_ids):
        raise ValueError('Recipe has no ingredients')
    return data


def foods():
    tags_extra = {'chicken': ['肉类'], 'pork': ['猪肉', '肉类'],
                  'beef': ['牛肉', '肉类'], 'beef_raw': ['牛肉', '肉类'], 'chicken_thigh': ['肉类']}
    uncertain = {'bread', 'soy', 'popcorn', 'chips', 'milk_chocolate', 'dark_chocolate',
                 'cookie', 'cheesecake', 'spongecake', 'icecream', 'croissant', 'flour_tortilla', 'wonton_wrapper', 'soy_sauce'}
    result = []
    for row in bundle()['foods_generic']:
        fid = food_id(row)
        tags = [{'豆': '大豆', '甲壳类': '虾蟹'}.get(t, t) for t in row['allergen_tags']]
        tags = sorted(set(tags + tags_extra.get(fid, [])))
        result.append(dict(id=fid, name=row['name_cn'], category=row['category'],
            kcal=row['kcal'], protein=row['protein_g'], carbs=row['carbs_g'], fat=row['fat_g'],
            tags=tags, portion_basis='每100克可食部 · ' + row['food_state'],
            source='USDA SR Legacy · FDC ' + str(row['source_record_id']), source_url=row['source_url'],
            updated_at=row['retrieved_date'], confidence=row['verification_status'],
            source_record_id=row['source_record_id'], food_state=row['food_state'],
            catalog_version=CATALOG_VERSION, allergen_check_required=fid in uncertain,
            cross_contact_tags=['小麦'] if fid == 'oats' else [],
            nutrients={k: row.get(k) for k in ('total_sugars_g', 'fiber_g', 'sodium_mg', 'caffeine_mg')},
            notes=row['notes']))
    return result


def recipes():
    data = bundle()
    mapping = {r['record_id']: food_id(r) for r in data['foods_generic']}
    result = []
    for row in data['recipes_estimated']:
        components = [dict(food_id=mapping[c['food_record_id']], grams=c['amount_g'])
                      for c in data['recipe_components'] if c['recipe_id'] == row['recipe_id']]
        result.append(dict(copy.deepcopy(row), ingredients=components, catalog_version=CATALOG_VERSION))
    return result


def products():
    return copy.deepcopy(bundle()['products_cn'])


def blocked_ingredients(ingredients, foods, exclusions):
    restrictions = set(exclusions)
    return any((set(foods[i['food_id']]['tags']) | set(foods[i['food_id']].get('cross_contact_tags', []))) & restrictions
               or (restrictions and foods[i['food_id']].get('allergen_check_required', False)) for i in ingredients)


def extra_snacks(foods_map, product_rows, recipe_rows, calculate):
    result = []
    for row in product_rows:
        if row['calculation_use'] != 'exact_product_serving' or row['category'] == '正餐产品':
            continue  # Suspicious official rows are stored, but cannot be selected.
        result.append(dict(id=row['record_id'], name=row['brand'] + ' · ' + row['name_cn'],
            unit=row['portion_label'] + ' · 官方标准配方，每份', group=row['category'],
            tags=[], ingredients=[], allergen_check_required=True,
            nutrition={'kcal': row['kcal'], 'protein': row['protein_g'], 'carbs': row['carbs_g'],
                       'fat': row['fat_g'], **{k: row.get(k) for k in ('total_sugars_g', 'fiber_g', 'sodium_mg', 'caffeine_mg')}},
            source=row['source_name'], source_url=row['source_url'], updated_at=row['retrieved_date'],
            catalog_version=CATALOG_VERSION,
            note='仅适用中国内地该品牌与所列规格。糖、咖啡因未公布时为未知。完整配料与过敏原待核对；修改糖奶或加料后不适用此数字。'))
    for row in recipe_rows:
        if row['category'] != '自配饮品':
            continue
        ingredients = copy.deepcopy(row['ingredients'])
        tags = sorted({t for i in ingredients for t in foods_map[i['food_id']]['tags']})
        result.append(dict(id='recipe-' + row['recipe_id'], name=row['name_cn'],
            unit=row['composition_cn'], group='自配饮品', ingredients=ingredients, tags=tags,
            nutrition=calculate(ingredients, foods_map), source='示例配方按食材加总估算',
            source_url=row['source_url'], updated_at=bundle()['retrieved_date'],
            catalog_version=CATALOG_VERSION, note='按列出的食材重量自配，不能代表门店奶茶或拿铁。'))
    for fid, grams in [('cheesecake', 80), ('spongecake', 50), ('cookie', 30), ('icecream', 80),
                       ('croissant', 50), ('dark_chocolate', 20), ('chips', 30), ('popcorn', 20)]:
        f = foods_map[fid]
        ingredients = [dict(food_id=fid, grams=grams)]
        result.append(dict(id='generic-' + fid, name=f['name'], unit=f'示例份量 {grams}g',
            group='通用甜点零食', tags=f['tags'], ingredients=ingredients, allergen_check_required=True,
            nutrition=calculate(ingredients, foods_map), source='USDA 通用食物参考，非具体品牌',
            source_url=f['source_url'], updated_at=f['updated_at'], catalog_version=CATALOG_VERSION,
            note='实际品牌配方与份量可能不同。示例份量仅便于记录；完整过敏原待核对。'))
    return result
