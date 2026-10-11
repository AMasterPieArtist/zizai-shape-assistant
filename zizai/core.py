"""Deterministic profile validation, retrieval, portions, and prototype rules.

Nutrition comes from a versioned source bundle, not restaurant measurements.
No LLM-provided calories or food names enter a saved plan.
"""
import copy
import datetime as dt
import math
import re

VERSIONS = {"prompt": "1.5-xiaozizai", "kb": "food-catalog-v2.0-20261011", "rules": "prototype-v1.1-optional"}
MEALS = ("breakfast", "lunch", "snack", "dinner")
LABELS = dict(zip(MEALS, ("早餐", "午餐", "下午茶", "晚餐")))
SHARES = dict(zip(MEALS, (.25, .35, .10, .30)))
EXCLUSIONS = ["乳制品", "鸡蛋", "小麦", "大豆", "花生", "坚果", "鱼", "虾蟹", "牛肉", "猪肉", "肉类", "辣"]


class Problem(Exception):
    def __init__(self, message, status=400, code="invalid_request"):
        super().__init__(message)
        self.status, self.code = status, code


def text(value, name, maximum=200, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise Problem(f"请检查{name}，最多 {maximum} 个字符。")
    return value.strip()


def number(value, name, low, high, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise Problem(f"{name}需要填写数字。")
    if not low <= value <= high or (integer and int(value) != value):
        raise Problem(f"{name}须在 {low}–{high} 之间。")
    return value


def choice(value, name, choices):
    if value not in choices:
        raise Problem(f"请选择有效的{name}。")
    return value


def date_value(value):
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError()
        return dt.date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise Problem("日期格式应为 YYYY-MM-DD。")


def profile_value(raw):
    if not isinstance(raw, dict):
        raise Problem("画像必须是对象。")
    p = {"nickname": text(raw.get("nickname"), "昵称", 30, True),
         "age": number(raw.get("age"), "年龄", 10, 100, True),
         "sex": choice(raw.get("sex"), "生理性别", ["female", "male"]),
         "height_cm": number(raw.get("height_cm"), "身高", 120, 220),
         "current_weight_kg": number(raw.get("current_weight_kg"), "当前体重", 30, 250),
         "target_weight_kg": number(raw.get("target_weight_kg"), "目标体重", 30, 250),
         "target_weeks": number(raw.get("target_weeks"), "目标周期", 1, 104, True),
         "work_intensity": choice(raw.get("work_intensity"), "工作节奏", ["normal", "busy"]),
         "exercise_frequency": choice(raw.get("exercise_frequency"), "运动频率", ["rare", "some", "often"]),
         "health_status": choice(raw.get("health_status"), "健康情况", ["general", "pregnant", "condition", "eating_concern"]),
         "preferences": text(raw.get("preferences", ""), "饮食偏好", 200),
         "exclusions_note": text(raw.get("exclusions_note", ""), "其他忌口", 100),
         "main_difficulty": text(raw.get("main_difficulty", ""), "主要困难", 200)}
    sources = raw.get("meal_sources")
    if not isinstance(sources, list) or not sources or any(x not in ["canteen", "delivery", "home"] for x in sources):
        raise Problem("请至少选择一种饮食来源。")
    exclusions = raw.get("exclusions", [])
    if not isinstance(exclusions, list) or any(x not in EXCLUSIONS for x in exclusions):
        raise Problem("忌口选项无效。")
    if not isinstance(raw.get("ai_consent", False), bool):
        raise Problem("数据授权格式无效。")
    p.update(meal_sources=list(dict.fromkeys(sources)), exclusions=list(dict.fromkeys(exclusions)),
             ai_consent=raw.get("ai_consent", False))
    p.update(goal=choice(raw.get("goal", "规律饮食"), "日常目标", ["规律饮食", "保持状态", "温和管理体重"]),
             sleep=choice(raw.get("sleep", "偶尔晚睡"), "作息", ["偶尔晚睡", "经常晚睡", "作息稳定"]),
             available_time=choice(raw.get("available_time", "10–20 分钟"), "活动时间", ["不足 10 分钟", "10–20 分钟", "20 分钟以上"]))
    return p


SNACKS = [
    {"id": "milk_tea", "name": "原味奶茶", "unit": "中杯 400 ml · 标准糖 · 不加料", "group": "奶茶", "tags": ["乳制品"], "ingredients": [], "note": "门店配方、糖量未知，不编造热量；需核对配料与咖啡因。"},
    {"id": "coffee", "name": "美式咖啡", "unit": "中杯 350 ml · 不加糖奶", "group": "咖啡", "tags": [], "ingredients": [], "note": "未接入品牌营养数据；含咖啡因，实际含量未知。"},
    {"id": "latte", "name": "拿铁咖啡", "unit": "纯咖啡 + 全脂奶 200 g · 不加糖", "group": "咖啡", "tags": ["乳制品"], "ingredients": [{"food_id": "milk", "grams": 200}], "note": "仅估算牛奶部分，咖啡未计入；门店配方可能不同。"},
    {"id": "cake", "name": "芝士蛋糕", "unit": "小块约 80 g", "group": "甜点", "tags": ["乳制品", "鸡蛋", "小麦"], "ingredients": [], "note": "品牌、配方未核验，不给出虚构营养数字；配料需另行核对。"},
    {"id": "nuts", "name": "原味核桃仁", "unit": "小包 20 g", "group": "零食", "tags": ["坚果"], "ingredients": [{"food_id": "walnut", "grams": 20}], "note": "以基础核桃仁估算，需留意混装坚果和交叉接触。"},
    {"id": "yogurt", "name": "原味酸奶", "unit": "1 杯 150 g", "group": "零食", "tags": ["乳制品"], "ingredients": [{"food_id": "yogurt", "grams": 150}], "note": "以基础原味酸奶估算，实际糖与脂肪随品牌变化。"},
]


def snack_catalog(foods, products=None, recipes=None):
    result = [dict(copy.deepcopy(item), nutrition=nutrition(item["ingredients"], foods) if item["ingredients"] else None,
                 source="基础食品参考估算" if item["ingredients"] else "营养数据待补充", updated_at="2026-10-08") for item in SNACKS]
    from .reference import extra_snacks
    return result + extra_snacks(foods, products or [], recipes or [], nutrition)



FOCUSES = ["饮食优先", "运动优先", "作息优先", "平衡维持", "自动匹配"]


def strategy_for(p, focus="自动匹配"):
    if focus == "自动匹配":
        focus = "作息优先" if p["sleep"] == "经常晚睡" or p["work_intensity"] == "busy" else "饮食优先" if "吃饭" in p["main_difficulty"] else "运动优先" if p["exercise_frequency"] == "rare" else "平衡维持"
    source = "/".join({"canteen": "食堂", "delivery": "外卖", "home": "家常"}[x] for x in p["meal_sources"])
    templates = {
        "饮食优先": ["先把三餐安排稳定", f"优先准备{source}中容易找到的两三种搭配，饮品小食也留位置。", "运动从容易坚持的短时活动开始。", "给用餐留一个相对固定的时间。"],
        "运动优先": ["先建立一个活动习惯", "保留正常三餐，按喜欢的口味选择食物。", f"从{p['available_time']}的可用时间出发，先安排熟悉的活动。", "把活动放到不挤占睡眠的时段。"],
        "作息优先": ["先让生活节奏缓下来", "忙碌时优先保证有饭可吃，准备方便的备选餐。", "疲劳日可以休息，有余力再安排短时散步。", "从减少一次不必要的熬夜开始，逐步稳定休息时间。"],
        "平衡维持": ["保留已经适合你的习惯", "维持喜欢且方便的三餐搭配，允许灵活替换。", "按已有习惯安排活动，忙碌日降低负担。", "延续稳定作息，给临时变化留余地。"]}
    return {"focus": focus, "items": templates[focus]}


def safe_profile(p):
    if p["age"] < 18 or p["health_status"] != "general":
        raise Problem("当前原型仅面向一般健康成年人。未成年人、孕哺期、慢性病或进食困扰等情况，请先咨询合格的医生或营养专业人士；画像可以保存，但不会自动生成饮食计划。", 422, "safety_boundary")
    height = p["height_cm"] / 100
    if min(p["current_weight_kg"], p["target_weight_kg"]) / height ** 2 < 18.5:
        raise Problem("当前体重或目标体重对应的 BMI 低于原型支持范围，暂不生成减重相关建议。请先与专业人士讨论适合你的目标。", 422, "safety_boundary")
    if (p["current_weight_kg"] - p["target_weight_kg"]) / p["target_weeks"] > 1:
        raise Problem("这个目标周期可能过于紧迫。请放缓目标或寻求专业支持；原型不会生成快速减重方案。", 422, "safety_boundary")
    if p["exclusions_note"]:
        raise Problem("你填写了其他忌口，当前小型知识库还不能可靠识别。请先核对并用已有忌口选项表达；无法覆盖时暂停自动规划，不要删除真实过敏信息来绕过检查。", 422, "unresolved_exclusion")


def safe_request(value):
    danger = r"催吐|泻药|绝食|不吃饭|不吃任何|饿死|自杀|自残|断食|孕|哺乳|糖尿病|肾病|进食障碍|暴食症|厌食症|头晕|晕倒|胸痛|过敏|胰岛素|减肥药|500\s*(大卡|卡)|800\s*(大卡|卡)|一周.{0,4}(瘦|减).{0,2}(5|10|五|十)"
    if re.search(danger, value, re.I):
        raise Problem("这涉及原型不能处理的健康或极端饮食情境。先照顾好自己，暂停自动调整，并咨询合格的医生或营养专业人士；严重不适时及时就医。", 422, "safety_boundary")


def energy_reference(p):
    """Mifflin–St Jeor resting estimate, illustrative activity multiplier.

    Not a calorie prescription: no automatic weight-loss deficit.
    Product thresholds here are provisional guards, not clinical standards.
    """
    bmr = 10 * p["current_weight_kg"] + 6.25 * p["height_cm"] - 5 * p["age"] + (5 if p["sex"] == "male" else -161)
    factor = {"rare": 1.4, "some": 1.5, "often": 1.6}[p["exercise_frequency"]]
    midpoint = round(max(1600, bmr * factor) / 50) * 50
    if midpoint > 3000:
        raise Problem("估算能量超出当前原型的小型食谱覆盖范围，请咨询专业人士定制。", 422, "unsupported_range")
    return {"midpoint": midpoint, "low": round(midpoint * .9), "high": round(midpoint * 1.1),
            "bmr_estimate": round(bmr), "activity_factor": factor,
            "label": "维持能量参考，不是减重处方", "status": "待专业复核",
            "source": "Mifflin–St Jeor (1990)，活动系数为原型假设",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/2305711/"}


def seed_foods():
    from .reference import foods
    return foods()


# title, ingredient weights, practical tip; a small transparent structured KB.
RECIPES = {
    "breakfast": [
        ("燕麦牛奶 · 鸡蛋与苹果", {"oats": 45, "milk": 220, "egg": 50, "apple": 120}, "即食燕麦用热牛奶泡软；通勤前约 5 分钟。"),
        ("全麦蛋三明治", {"bread": 95, "egg": 60, "tomato": 100, "milk": 180, "oil": 4}, "便利店买全麦面包、鸡蛋和牛奶即可组合，约 5 分钟。"),
        ("豆浆燕麦 · 香蕉核桃", {"oats": 55, "soy": 260, "banana": 100, "walnut": 12}, "选无糖豆浆，燕麦提前泡好；留意谷物交叉接触。"),
        ("饭团 · 鸡蛋与豆浆", {"rice": 170, "egg": 70, "soy": 220, "carrot": 70, "oil": 5}, "购买现成基础饭团和鸡蛋，配无糖豆浆，约 5 分钟。"),
        ("酸奶燕麦水果杯", {"oats": 50, "yogurt": 220, "banana": 100, "walnut": 10}, "前晚浸泡燕麦，早晨加入水果即可。"),
        ("鸡肉饭团 · 一份水果", {"rice": 180, "chicken": 70, "apple": 140, "oil": 10}, "选少酱饭团搭配水果；有预制食材时约 5 分钟。"),
    ],
    "main": [
        ("鸡肉双蔬饭", {"rice": 220, "chicken": 95, "broccoli": 160, "carrot": 70, "oil": 13}, "食堂选一份鸡肉、两样蔬菜；酱汁另放。"),
        ("番茄牛肉饭", {"rice": 235, "beef": 90, "tomato": 180, "spinach": 80, "oil": 7}, "外卖优先看得到食材的套餐，少浇浓汁。"),
        ("清汤豆腐蔬菜面", {"noodles": 220, "tofu": 110, "broccoli": 180, "carrot": 60, "oil": 8}, "麻辣烫或面馆可这样搭配：主食、豆腐、蔬菜都保留；选清汤。"),
        ("土豆鸡肉蔬菜碗", {"potato": 340, "chicken": 90, "broccoli": 150, "carrot": 80, "oil": 16}, "外卖或食堂的土豆可作为主食，不必额外去掉其他食材。"),
        ("双蔬豆腐盖饭", {"rice": 220, "tofu": 130, "spinach": 160, "carrot": 80, "oil": 8}, "选非油炸豆腐，蔬菜加一份；和商家确认配料。"),
        ("番茄鸡蛋鸡肉面", {"noodles": 230, "egg": 50, "chicken": 55, "tomato": 180, "spinach": 80, "oil": 10}, "可向面馆加一份蛋白质和青菜，汤不必喝完。"),
        ("清汤鸡肉蔬菜锅", {"rice": 230, "chicken": 105, "broccoli": 180, "carrot": 100, "oil": 13}, "聚餐时保留正常主食，按舒服的节奏吃，不用为这餐跳过下一餐。"),
        ("牛肉土豆暖碗", {"potato": 340, "beef": 95, "spinach": 160, "tomato": 100, "oil": 10}, "适合加班时点一份完整套餐，酱汁另放。"),
        ("鸡蛋豆腐饭", {"rice": 230, "egg": 60, "tofu": 70, "broccoli": 180, "tomato": 100, "oil": 7}, "食堂常见组合；没有同款菜时查看另一个候选。"),
    ],
    "snack": [
        ("苹果 · 原味酸奶", {"apple": 160, "yogurt": 180}, "饿了可以安心吃一份加餐，选择原味酸奶。"),
        ("香蕉 · 牛奶", {"banana": 110, "milk": 180}, "便利店容易找到的一组搭配。"),
        ("橙子 · 一小把核桃", {"orange": 180, "walnut": 18}, "用小袋分装更方便，不需要一颗颗计算。"),
        ("豆浆 · 一份香蕉", {"soy": 240, "banana": 120}, "无糖豆浆也可以作为下午饮品。"),
        ("苹果 · 花生", {"apple": 170, "peanut": 22}, "留意花生过敏；选择原味、少盐。"),
        ("鲜奶茶搭配水果（无额外糖）", {"milk": 220, "apple": 110}, "以纯茶加奶作参考；门店糖浆、奶精和小料未知，不套用品牌热量。"),
    ]}


def nutrition(ingredients, foods):
    result = {k: 0 for k in ("kcal", "protein", "carbs", "fat", "vegetables_g")}
    for item in ingredients:
        f = foods[item["food_id"]]
        for k in ("kcal", "protein", "carbs", "fat"):
            result[k] += f[k] * item["grams"] / 100
        if f["category"] == "蔬菜":
            result["vegetables_g"] += item["grams"]
    return {k: round(v, 1) for k, v in result.items()}


def portion(food, grams):
    units = {"rice": (150, "碗"), "egg": (50, "个"), "milk": (200, "杯"), "soy": (200, "杯"),
             "salt": (1, "克"), "soy_sauce": (1, "克"), "yogurt": (180, "杯"), "chicken": (90, "掌心"), "beef": (90, "掌心"), "oil": (5, "茶匙")}
    amount, unit = units.get(food, (100, "小份"))
    return f"约 {grams / amount:.1f} {unit}（参考 {grams:g}g）"


def diverse_candidates(options, count=3):
    """Prefer different meal types within a batch; only choose already-filtered options."""
    picked = []
    families = set()
    for option in options:
        family = option.get("meal_family", "其他")
        if family not in families:
            picked.append(option)
            families.add(family)
        if len(picked) == count:
            return picked
    return (picked + [x for x in options if x not in picked])[:count]


def meal_family(title):
    for word, family in [("米粉", "米粉米线"), ("意面", "意面"), ("面", "汤面"), ("锅", "自选汤锅"), ("土豆", "杂粮薯类")]:
        if word in title:
            return family
    return "米饭配餐"


def scaled_grams(food_id, grams, ratio, foods):
    # Small amounts of salt/sauce must not disappear under the meal's 5g rounding.
    return round(grams * ratio, 1) if foods[food_id]['category'] == '调味' else round(grams * ratio / 5) * 5


def option_pool(p, meal, foods, reference, recipe_templates=None, product_rows=None):
    from .reference import blocked_ingredients, recipes as reference_recipes
    recipes = [(f"{meal}-{i}", title, weights, tip, {}) for i, (title, weights, tip) in
               enumerate(RECIPES[meal if meal in ("breakfast", "snack") else "main"])]
    category = {"breakfast": "早餐", "snack": "加餐"}.get(meal, "正餐")
    for row in reference_recipes() if recipe_templates is None else recipe_templates:
        if row["category"] == category and set(row.get('meal_sources', p['meal_sources'])) & set(p['meal_sources']):
            recipes.append((f"{meal}-ref-{row['recipe_id']}", row['name_cn'],
                            {i['food_id']: i['grams'] for i in row['ingredients']},
                            row.get('order_tip', "示例配方：按所列食材与生熟状态组合，份量随参考能量缩放；门店需核对实际配料。"), row))
    items = []
    for oid, title, weights, tip, metadata in recipes:
        if blocked_ingredients([{ "food_id": f } for f in weights], foods, p["exclusions"]):
            continue
        base = sum(foods[f]["kcal"] * w / 100 for f, w in weights.items())
        ratio = reference["midpoint"] * SHARES[meal] / base
        ingredients = [{"food_id": f, "name": foods[f]["name"], "grams": scaled_grams(f, w, ratio, foods),
                        "portion": portion(f, scaled_grams(f, w, ratio, foods))} for f, w in weights.items()]
        source = " / ".join({"canteen": "食堂", "delivery": "外卖", "home": "家常"}[x] for x in p["meal_sources"]
                            if x in metadata.get('meal_sources', p['meal_sources']))
        items.append({"id": oid, "title": title, "ingredients": ingredients,
                      "nutrition": nutrition(ingredients, foods), "tip": tip, "scene": source if meal in ("lunch", "dinner") else "便利店 / 轻准备",
                      "meal_family": metadata.get('meal_family', meal_family(title)), "source_type": "示例配方估算",
                      "source_url": metadata.get('source_url', 'https://fdc.nal.usda.gov/download-datasets/'),
                      "reason": f"按你的{source}场景组合；需确认门店供应、配料和实际份量。" if meal in ("lunch", "dinner") else "用容易找到的食材，减少临时做决定的负担。",
                      "catalog_version": VERSIONS["kb"], "estimate_note": "仅含列出食材与调味的估算；未核实的汤底、蘸料和实际用油不在示例内，不能当成已完整计算的门店餐。"})
    if meal in ("lunch", "dinner"):
        items.extend(brand_meal_options(p, foods, meal, reference, product_rows))
    if len(items) < 3:
        raise Problem(f"排除忌口后，知识库中可用的{LABELS[meal]}方案不足 3 个。为避免猜测食材，本次暂停生成；需要先补充适合你的食品数据。", 422, "insufficient_foods")
    return items


def brand_meal_options(p, foods, meal, reference, product_rows=None):
    from .reference import products
    # Brand component remains exactly ONE standard item: no fictitious gram weight or resizing.
    if p['exclusions'] or 'delivery' not in p['meal_sources']:
        return []
    items = []
    for row in products() if product_rows is None else product_rows:
        if row['category'] != '正餐产品' or row['calculation_use'] != 'exact_product_serving':
            continue
        target = reference['midpoint'] * SHARES[meal]
        veg = {'food_id': 'pakchoi', 'name': foods['pakchoi']['name'], 'grams': 200, 'portion': portion('pakchoi', 200)}
        remaining = target - row['kcal'] - nutrition([veg], foods)['kcal']
        grams = round(remaining / foods['potato']['kcal'] * 100 / 5) * 5
        if not 80 <= grams <= 450:
            continue  # Out-of-range combinations are unavailable, never resize a branded item.
        potato = {'food_id': 'potato', 'name': foods['potato']['name'], 'grams': grams, 'portion': portion('potato', grams)}
        n = nutrition([veg, potato], foods)
        for key, field in [('kcal','kcal'), ('protein','protein_g'), ('carbs','carbs_g'), ('fat','fat_g')]:
            n[key] = round(n[key]+row[field],1)
        slug = row['source_record_id'].split('#')[0].lower()
        items.append({'id': f'{meal}-brand-{slug}', 'title': row['name_cn']+' · 另备土豆青菜',
            'meal_family': '品牌汉堡配餐', 'scene': '外卖 + 自备配餐', 'source_type': '品牌官方标准份 + 自备食材估算',
            'source_url': row['source_url'], 'catalog_version': VERSIONS['kb'], 'nutrition': n,
            'ingredients': [{'product_id': row['record_id'], 'name': '麦当劳中国 · '+row['name_cn'],
                             'quantity': 1, 'unit': '个', 'portion': '1个（官方标准配方；克重未公布）'}, potato, veg],
            'reason': '汉堡使用中国内地官方每个营养；土豆与青菜为另行自备的搭配示例。',
            'tip': '先确认可以买到该汉堡，再另备列明的土豆与青菜；这不是品牌官方套餐。价格、门店库存、配送范围未接入。',
            'estimate_note': '品牌部件为2025年4月官方标准份；自备配餐按USDA参考估算。改配方或增减酱料后不适用。完整过敏原待核验。'})
    return items


def pools_for(p, foods, recipe_templates=None, product_rows=None):
    safe_profile(p)
    reference = energy_reference(p)
    return reference, {meal: option_pool(p, meal, foods, reference, recipe_templates, product_rows) for meal in MEALS}


def totals(plan, include_optional=False):
    return {k: round(sum(m["selected"]["nutrition"][k] for meal, m in plan["meals"].items()
                        if include_optional or meal != "snack" or m.get("enabled", True)), 1)
            for k in ("kcal", "protein", "carbs", "fat", "vegetables_g")}


def validate_plan(plan, p):
    safe_profile(p)
    n = totals(plan)
    ref = plan["reference"]
    def checks_for(n):
        energy = max(n["kcal"], 1)
        return [
        ("参考能量范围", ref["low"] <= n["kcal"] <= ref["high"]),
        ("原型最低能量护栏", n["kcal"] >= 1500),
        ("蛋白质基础覆盖", n["protein"] >= .8 * p["current_weight_kg"]),
        ("碳水保留", .40 <= n["carbs"] * 4 / energy <= .70),
        ("脂肪组合", .15 <= n["fat"] * 9 / energy <= .40),
        ("蔬菜覆盖", n["vegetables_g"] >= 300),
        ]
    checks = checks_for(n)
    optional_off = plan["meals"]["snack"].get("enabled", True) is False
    # User opt-out must be possible without forcing extra food. Retain and
    # validate the original optional composition for generation/substitution
    # guards, but report ACTUAL active-meal checks (including failures) below.
    guard_checks = checks_for(totals(plan, include_optional=True)) if optional_off else checks
    if not all(ok for _, ok in guard_checks):
        failed = "、".join(name for name, ok in guard_checks if not ok)
        raise Problem(f"方案未通过原型规则（{failed}），未保存。请换一组候选或调整画像；这些规则仍需专业复核。", 422, "rule_failed")
    plan["versions"]["rules"] = VERSIONS["rules"]
    plan["totals"] = n
    plan["checks"] = [{"name": name, "passed": ok} for name, ok in checks]
    plan["check_basis"] = "当前启用餐次，不含额外饮品小食"
    plan["optional_snack_note"] = ("下午茶未安排，未计入合计；三餐保持不变。" +
        ("当前启用餐次有未达到原型参考规则的项目，详见下方检查；不代表全天营养已充分。" if not all(ok for _, ok in checks) else "")) if optional_off else ""
    return plan


def make_plan(p, foods, day, mode, ai=None, offset=0, recipe_templates=None, product_rows=None):
    reference, pools = pools_for(p, foods, recipe_templates, product_rows)
    result = {"date": day, "reference": reference, "versions": dict(VERSIONS), "source": mode,
              "strategy": "不必让生活迁就一张食谱。先从一顿容易实现的饭开始，保留主食、蛋白质和蔬菜。",
              "movement": "忙的时候，饭后舒服地走一走或拉伸几分钟就好；休息也是可以的。" if p["work_intensity"] == "busy" else "如果身体感觉舒适，可以饭后散步 20 分钟，或安排 10 分钟轻柔拉伸。",
              "meals": {}, "snacks": [], "activities": [], "strategy_focus": "自动匹配"}
    for meal, options in pools.items():
        start = (offset + (3 if meal == "dinner" else 0)) % len(options)
        ordered = options[start:] + options[:start]
        result["meals"][meal] = {"candidates": copy.deepcopy(ordered[:3]), "selected": copy.deepcopy(ordered[0]), "completed": False, "batch": 1, "enabled": True}
    if ai:
        result["strategy"] = ai["message"]
        result["versions"]["model"] = ai["model"]
        for meal, oid in ai["choices"].items():
            selected = next(x for x in pools[meal] if x["id"] == oid)
            result["meals"][meal]["selected"] = copy.deepcopy(selected)
            result["meals"][meal]["candidates"] = [copy.deepcopy(selected)] + [copy.deepcopy(x) for x in pools[meal] if x["id"] != oid][:2]
    else:
        result["versions"]["model"] = "local-template-v1"
    return validate_plan(result, p)


def checked_activity_action(action, plan):
    """Only allow explicit removals of entries in this plan; rest is advice only."""
    if action is None:
        return {"type": "keep", "entry_ids": []}
    if not isinstance(action, dict) or set(action) != {"type", "entry_ids"}:
        raise ValueError("invalid activity action")
    kind, ids = action["type"], action["entry_ids"]
    if kind not in ("keep", "remove") or not isinstance(ids, list):
        raise ValueError("invalid activity action")
    if any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("invalid activity ids")
    available = {a["entry_id"] for a in (plan or {}).get("activities", [])}
    if not set(ids) <= available or (kind == "keep" and ids) or (kind == "remove" and not ids):
        raise ValueError("unknown or inconsistent activity ids")
    return {"type": kind, "entry_ids": list(ids)}


def demo_activity_action(request, plan):
    """Conservative local examples, not unrestricted language understanding."""
    targets = set()
    for clause in re.split(r"[，,。；;！!？?\n]", request):
        if re.search(r"不要取消|不取消|不想取消|不用取消|无需取消|别取消|保留|照常|继续", clause):
            continue
        kinds = [kind for word, kind in (("游泳", "swim"), ("步行", "walk"), ("散步", "walk")) if word in clause]
        cancel = bool(re.search(r"取消|不想|不去|不做|不运动|不游|不走|去不了|暂停", clause))
        all_cancel = bool(re.search(r"(?:取消|不想|不做|暂停).{0,8}运动|运动.{0,8}(?:取消|暂停)|不运动", clause))
        if cancel:
            for a in plan.get("activities", []):
                if (kinds and a["kind"] in kinds) or (not kinds and all_cancel):
                    targets.add(a["entry_id"])
    return {"type": "remove" if targets else "keep", "entry_ids": sorted(targets)}


def adjusted_plan(plan, p, foods, request, mode, ai=None, recipe_templates=None, product_rows=None):
    result = copy.deepcopy(plan)
    _, pools = pools_for(p, foods, recipe_templates, product_rows)
    messages = []
    try:
        activity_action = checked_activity_action(ai.get("activity_action") if ai else demo_activity_action(request, plan), plan)
    except ValueError:
        raise Problem("运动调整引用了无效项目，未保存。请刷新计划后重试。", 422, "invalid_activity_action")
    if ai:
        changes = ai["choices"]
        messages.append(ai["message"])
    else:
        changes = {}
        if re.search("奶茶|饮料|下午茶", request):
            if plan["meals"]["snack"].get("enabled", True) is False:
                raise Problem("今天未安排下午茶。想喝奶茶可在「饮品与小食」主动添加；不会自动恢复下午茶或改动正餐。", 409, "meal_disabled")
            preferred = next((x for x in pools["snack"] if x["id"] == "snack-5"), None)
            if not preferred:
                raise Problem("演示奶茶配方含乳制品，与你的忌口冲突，本次不会替换。", 422, "exclusion_conflict")
            changes["snack"] = preferred["id"]
            changes["dinner"] = pools["dinner"][0]["id"]
            messages.append("想喝奶茶也是日常的小满足，可以按自己的喜好选择。小自在准备的演示草案使用无额外糖的鲜奶茶参考组合，并给晚餐换一种搭配；正常加糖或小料的门店奶茶数据未知，不能据此精确抵扣，也不用跳过正餐。")
        elif re.search("聚餐|火锅", request):
            preferred = next((x for x in pools["dinner"] if x["id"] == "dinner-6"), pools["dinner"][0])
            changes["dinner"] = preferred["id"]
            messages.append("和朋友聚餐也是照顾生活的一部分，不用为计划变化责备自己。演示草案换成清汤鸡肉蔬菜锅的食材参考，保留正常主食；实际锅底和蘸料未知，热量仅作示意。")
        elif re.search("加班|忙|运动|游泳|步行|散步|累", request):
            preferred = next((x for x in pools["dinner"] if x["id"] == "dinner-7"), pools["dinner"][0])
            if re.search("加班|忙|晚餐|晚饭", request):
                changes["dinner"] = preferred["id"]
            messages.append("安排可以随着生活调整。先照顾好吃饭和休息，再看看今天适合保留哪些活动；不用靠运动补偿吃过的东西。")
            result["movement"] = "今晚可以休息；如果愿意，起身舒展 3–5 分钟即可，不用额外补偿运动。"
        else:
            raise Problem("演示模式仅支持奶茶、聚餐／火锅、加班／不想运动这三类示例。自由描述需要配置 DeepSeek 并开启数据授权。", 422, "demo_scope")
    actual_changes = []
    for meal, oid in changes.items():
        if meal == "snack" and result["meals"][meal].get("enabled", True) is False:
            if ai:
                raise Problem("今天已取消下午茶，不能由模型自动恢复或替换。请先在今日计划中恢复。", 422, "meal_disabled")
            messages.append("今天未安排下午茶，保留你的选择；如需奶茶，可以在饮品与小食中主动添加。")
            continue
        if result["meals"][meal]["completed"]:
            continue
        chosen = next(x for x in pools[meal] if x["id"] == oid)
        if chosen["id"] != result["meals"][meal]["selected"]["id"]:
            result["meals"][meal]["selected"] = copy.deepcopy(chosen)
            result["meals"][meal]["candidates"] = [copy.deepcopy(chosen)] + [copy.deepcopy(x) for x in pools[meal] if x["id"] != oid][:2]
            actual_changes.append(LABELS[meal])
    if ai and ai.get("rest"):
        result["movement"] = "今天可选择休息，或在身体舒适时起身伸展几分钟。不需要用运动补偿饮食。"
    if activity_action["type"] == "remove":
        removed = set(activity_action["entry_ids"])
        cancelled = [a for a in result.get("activities", []) if a["entry_id"] in removed]
        result["activities"] = [a for a in result.get("activities", []) if a["entry_id"] not in removed]
        remaining = result["activities"]
        result["movement"] = "已按你的要求取消指定运动。" + ("其他运动安排保留，可按实际状态选择是否继续。" if remaining else "今天没有已安排的运动，可以休息。")
        messages.append("待确认取消：" + "、".join(f"{a['name']} {a['minutes']} 分钟" for a in cancelled) + "。")
    changed_activities = result.get("activities", []) != plan.get("activities", [])
    changed_movement = result["movement"] != plan["movement"]
    if not actual_changes and not changed_movement and not changed_activities:
        raise Problem("当前可调整餐次已经完成，或建议与现有计划相同；没有生成重复草案。", 409, "no_change")
    result["source"] = mode
    result["versions"]["prompt"] = VERSIONS["prompt"]
    result["versions"]["model"] = ai["model"] if ai else "local-template-v1"
    result["adjustment_note"] = " ".join(messages)
    validate_plan(result, p)
    return result, " ".join(messages), actual_changes + (["运动安排"] if changed_activities else []) + (["运动建议"] if changed_movement else [])
