import copy
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import Application, Server
from zizai import deepseek
from zizai.core import (MEALS, Problem, adjusted_plan, energy_reference, make_plan,
                        pools_for, profile_value, safe_request, seed_foods,
                        validate_plan)

DAY = "2026-10-08"


def profile(**changes):
    raw = dict(nickname="小林", age=29, sex="female", height_cm=165,
               current_weight_kg=60, target_weight_kg=57, target_weeks=12,
               work_intensity="busy", exercise_frequency="rare", health_status="general",
               meal_sources=["canteen", "delivery"], preferences="奶茶、面食",
               exclusions=[], exclusions_note="", main_difficulty="加班时不知道吃什么", ai_consent=False)
    raw.update(changes)
    return profile_value(raw)


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.foods = {f["id"]: f for f in seed_foods()}
        self.p = profile()

    def test_profile_type_and_range_validation(self):
        for changes in ({"age": True}, {"height_cm": float("nan")}, {"nickname": ""},
                        {"meal_sources": []}, {"exclusions": ["未识别过敏原"]}, {"ai_consent": "yes"}):
            with self.subTest(changes=changes), self.assertRaises(Problem):
                profile(**changes)

    def test_four_meals_with_three_options_and_reference(self):
        plan = make_plan(self.p, self.foods, DAY, "demo")
        self.assertEqual(set(plan["meals"]), set(MEALS))
        self.assertEqual(energy_reference(self.p)["bmr_estimate"], 1325)
        for meal in plan["meals"].values():
            self.assertEqual(len(meal["candidates"]), 3)
            self.assertTrue(meal["selected"]["ingredients"])
        self.assertTrue(all(c["passed"] for c in plan["checks"]))

    def test_supported_allergy_is_excluded_from_all_candidates(self):
        p = profile(exclusions=["乳制品"])
        _, pools = pools_for(p, self.foods)
        for options in pools.values():
            for option in options:
                for ingredient in option["ingredients"]:
                    self.assertNotIn("乳制品", self.foods[ingredient["food_id"]]["tags"])

    def test_unknown_exclusions_and_candidate_shortage_fail_closed(self):
        for p in (profile(exclusions_note="芹菜"), profile(exclusions=["乳制品", "大豆", "鸡蛋", "肉类"])):
            with self.subTest(p=p), self.assertRaises(Problem):
                pools_for(p, self.foods)

    def test_special_populations_and_unsafe_goals_are_blocked(self):
        for changes in ({"age": 17}, {"health_status": "pregnant"}, {"health_status": "condition"},
                        {"health_status": "eating_concern"}, {"target_weight_kg": 45},
                        {"target_weight_kg": 54, "target_weeks": 2}):
            with self.subTest(changes=changes), self.assertRaises(Problem):
                pools_for(profile(**changes), self.foods)

    def test_low_energy_plan_is_rejected(self):
        plan = make_plan(self.p, self.foods, DAY, "demo")
        for meal in plan["meals"].values():
            meal["selected"]["nutrition"]["kcal"] = 100
        with self.assertRaises(Problem) as caught:
            validate_plan(plan, self.p)
        self.assertEqual(caught.exception.code, "rule_failed")

    def test_tea_dinner_and_busy_day_adjustment_cases(self):
        plan = make_plan(self.p, self.foods, DAY, "demo")
        for request, expected in [("我想喝奶茶", "下午茶"), ("今晚聚餐吃火锅", "晚餐"), ("今晚加班，不想运动", "运动建议")]:
            with self.subTest(request=request):
                candidate, _, changes = adjusted_plan(plan, self.p, self.foods, request, "demo")
                self.assertIn(expected, changes)
                self.assertNotEqual(candidate, plan)
                self.assertNotIn("adjustment_note", plan)

    def test_completed_meals_are_not_modified_by_adjustment(self):
        plan = make_plan(self.p, self.foods, DAY, "demo")
        plan["meals"]["dinner"]["completed"] = True
        candidate, _, changes = adjusted_plan(plan, self.p, self.foods, "加班不想运动", "demo")
        self.assertEqual(candidate["meals"]["dinner"], plan["meals"]["dinner"])
        self.assertEqual(changes, ["运动建议"])

    def test_red_flag_requests_are_blocked(self):
        for request in ("我要绝食", "每天500大卡", "我怀孕了", "糖尿病可以这样吃吗", "我想催吐", "我头晕了"):
            with self.subTest(request=request), self.assertRaises(Problem):
                safe_request(request)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite3"
        self.app = Application(self.path)
        self.app.mutate("PUT", "/api/profile", {"profile": profile(), "expected_version": 0})
        self.plan = self.app.mutate("POST", "/api/plans/generate", {"date": DAY, "mode": "demo"})["plan"]

    def tearDown(self):
        self.temp.cleanup()

    def draft(self, request="今晚加班，不想运动"):
        return self.app.mutate("POST", "/api/adjustments", {"date": DAY, "expected_version": self.plan["version"], "mode": "demo", "request": request})["adjustment"]

    def test_restart_preserves_profile_plan_and_draft(self):
        draft = self.draft()
        restarted = Application(self.path)
        self.assertEqual(restarted.store.plan(DAY), self.plan)
        self.assertEqual(restarted.store.profile()["data"]["nickname"], "小林")
        self.assertEqual(restarted.store.adjustments(DAY)[0]["id"], draft["id"])

    def test_only_confirmation_updates_plan_and_is_one_shot(self):
        draft = self.draft()
        self.assertEqual(self.app.store.plan(DAY), self.plan)
        result = self.app.mutate("POST", f"/api/adjustments/{draft['id']}/confirm", {})["plan"]
        self.assertEqual(result["version"], self.plan["version"] + 1)
        self.assertIn("休息", result["movement"])
        with self.assertRaises(Problem):
            self.app.mutate("POST", f"/api/adjustments/{draft['id']}/confirm", {})

    def test_discard_does_not_change_plan(self):
        draft = self.draft()
        self.app.mutate("POST", f"/api/adjustments/{draft['id']}/discard", {})
        self.assertEqual(self.app.store.plan(DAY), self.plan)
        self.assertEqual(self.app.store.adjustments(DAY)[0]["status"], "discarded")

    def test_new_plan_supersedes_draft(self):
        draft = self.draft()
        self.app.mutate("POST", "/api/meals/complete", {"date": DAY, "expected_version": 1, "meal": "lunch", "completed": True})
        with self.assertRaises(Problem) as caught:
            self.app.mutate("POST", f"/api/adjustments/{draft['id']}/confirm", {})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.app.store.adjustments(DAY)[0]["status"], "superseded")

    def test_profile_change_invalidates_draft_and_selection(self):
        draft = self.draft()
        self.app.mutate("PUT", "/api/profile", {"profile": profile(exclusions=["乳制品"]), "expected_version": 1})
        with self.assertRaises(Problem) as caught:
            self.app.mutate("POST", f"/api/adjustments/{draft['id']}/confirm", {})
        self.assertEqual(caught.exception.code, "profile_changed")
        with self.assertRaises(Problem):
            self.app.mutate("POST", "/api/meals/complete", {"date": DAY, "expected_version": 1, "meal": "lunch", "completed": True})

    def test_candidate_refresh_does_not_adopt_or_repeat_old_batch(self):
        old = self.plan["meals"]["lunch"]
        result = self.app.mutate("POST", "/api/meals/refresh", {"date": DAY, "expected_version": 1, "meal": "lunch", "reason": "unavailable"})["plan"]
        new = result["meals"]["lunch"]
        self.assertFalse({x["id"] for x in old["candidates"]} & {x["id"] for x in new["candidates"]})
        self.assertEqual(old["selected"], new["selected"])
        self.assertEqual(len(new["candidates"]), 3)
        chosen = new["candidates"][0]
        result = self.app.mutate("POST", "/api/meals/select", {"date": DAY, "expected_version": 2, "meal": "lunch", "option_id": chosen["id"]})["plan"]
        self.assertEqual(result["meals"]["lunch"]["selected"]["id"], chosen["id"])

    def test_stale_write_and_unknown_candidate_are_rejected(self):
        for body in ({"expected_version": 99, "option_id": "lunch-1"}, {"expected_version": 1, "option_id": "injected-food"}):
            with self.subTest(body=body), self.assertRaises(Problem):
                self.app.mutate("POST", "/api/meals/select", dict(date=DAY, meal="lunch", **body))
        self.assertEqual(self.app.store.plan(DAY), self.plan)

    def test_completed_meal_requires_explicit_reset_for_regeneration(self):
        self.app.mutate("POST", "/api/meals/complete", {"date": DAY, "expected_version": 1, "meal": "lunch", "completed": True})
        with self.assertRaises(Problem) as caught:
            self.app.mutate("POST", "/api/plans/generate", {"date": DAY, "expected_version": 2, "mode": "demo"})
        self.assertEqual(caught.exception.code, "completed_reset_required")

    def test_only_one_concurrent_confirmation_succeeds(self):
        drafts = [self.draft(), self.draft("我想喝奶茶")]
        def confirm(draft):
            try:
                self.app.mutate("POST", f"/api/adjustments/{draft['id']}/confirm", {})
                return 200
            except Problem as exc:
                return exc.status
        with ThreadPoolExecutor(2) as pool:
            codes = list(pool.map(confirm, drafts))
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(self.app.store.plan(DAY)["version"], 2)

    def test_export_and_delete_preserve_food_knowledge(self):
        self.draft()
        data = self.app.get("/api/export", {})
        self.assertEqual(len(data["plans"]), 1)
        self.assertEqual(len(data["adjustments"]), 1)
        with self.assertRaises(Problem):
            self.app.mutate("POST", "/api/data/delete", {"confirmation": "yes"})
        self.app.mutate("POST", "/api/data/delete", {"confirmation": "删除我的本地数据"})
        self.assertIsNone(self.app.store.profile())
        self.assertIsNone(self.app.store.plan(DAY))
        self.assertEqual(len(self.app.store.foods()), len(seed_foods()))

    def test_snacks_and_activities_survive_restart(self):
        result = self.app.mutate("POST", "/api/snacks/add", {"date": DAY, "expected_version": 1, "snack_id": "milk_tea"})["plan"]
        self.assertIsNone(result["snacks"][0]["nutrition"])
        result = self.app.mutate("POST", "/api/activities/add", {"date": DAY, "expected_version": 2, "kind": "swim", "minutes": 30})["plan"]
        self.assertEqual(result["activities"][0]["kcal"], 180)
        self.assertEqual(result["totals"], self.plan["totals"])
        restarted = Application(self.path)
        self.assertEqual(restarted.store.plan(DAY)["snacks"], result["snacks"])
        self.assertEqual(restarted.store.plan(DAY)["activities"], result["activities"])
        result = self.app.mutate("POST", "/api/snacks/remove", {"date": DAY, "expected_version": 3, "entry_id": result["snacks"][0]["entry_id"]})["plan"]
        self.assertEqual(result["snacks"], [])
        result = self.app.mutate("POST", "/api/activities/rest", {"date": DAY, "expected_version": 4})["plan"]
        self.assertEqual(result["activities"], [])

    def test_snack_allergy_and_unknown_ingredients_are_blocked(self):
        self.app.mutate("PUT", "/api/profile", {"profile": profile(exclusions=["乳制品"]), "expected_version": 1})
        self.app.mutate("POST", "/api/plans/generate", {"date": DAY, "expected_version": 1, "mode": "demo"})
        for snack_id in ("yogurt", "milk_tea", "coffee"):
            with self.subTest(snack=snack_id), self.assertRaises(Problem) as caught:
                self.app.mutate("POST", "/api/snacks/add", {"date": DAY, "expected_version": 2, "snack_id": snack_id})
            self.assertEqual(caught.exception.code, "exclusion_conflict")

    def test_strategy_is_draft_until_confirmed(self):
        data = self.app.mutate("POST", "/api/strategy/draft", {"date": DAY, "expected_version": 1, "focus": "作息优先"})
        self.assertFalse(data["plan_changed"])
        self.assertEqual(self.app.store.plan(DAY), self.plan)
        self.app.mutate("POST", f"/api/adjustments/{data['adjustment']['id']}/confirm", {})
        self.assertEqual(self.app.store.plan(DAY)["strategy_focus"], "作息优先")

    def test_deepseek_failure_never_changes_formal_plan(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            with self.assertRaises(Problem):
                self.app.mutate("POST", "/api/adjustments", {"date": DAY, "expected_version": 1, "request": "今晚加班", "mode": "deepseek"})
        self.assertEqual(self.app.store.plan(DAY), self.plan)
        self.assertEqual(self.app.store.adjustments(DAY), [])

    def test_mocked_ai_generation_saves_model_version(self):
        self.app.mutate("PUT", "/api/profile", {"profile": profile(ai_consent=True), "expected_version": 1})
        _, pools = pools_for(profile(ai_consent=True), self.app.store.foods())
        content = {"blocked": False, "message": "照顾好今天的一餐，慢慢来。", "choices": {m: v[0]["id"] for m, v in pools.items()}}
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode())
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only", "DEEPSEEK_MODEL": "deepseek-chat"}), patch("urllib.request.urlopen", return_value=response):
            result = self.app.mutate("POST", "/api/plans/generate", {"date": DAY, "expected_version": 1, "mode": "deepseek"})["plan"]
        self.assertEqual(result["source"], "deepseek")
        self.assertEqual(result["versions"]["model"], "deepseek-chat")
        self.assertEqual(result["version"], 2)


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.p = profile(ai_consent=True)
        self.foods = {f["id"]: f for f in seed_foods()}
        self.reference, self.pools = pools_for(self.p, self.foods)
        self.valid = {"blocked": False, "message": "今天从容易买到的一餐开始，给生活留一点弹性。", "choices": {m: v[0]["id"] for m, v in self.pools.items()}, "rest": False}

    def response(self, data):
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(data)}}]}).encode())

    def test_missing_key_and_consent_fail_before_network(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}), patch("urllib.request.urlopen") as network:
            with self.assertRaises(Problem) as caught:
                deepseek.recommend(self.p, self.pools, self.reference)
            self.assertEqual(caught.exception.code, "missing_api_key")
            network.assert_not_called()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch("urllib.request.urlopen") as network:
            with self.assertRaises(Problem) as caught:
                deepseek.recommend(profile(ai_consent=False), self.pools, self.reference)
            self.assertEqual(caught.exception.code, "consent_required")
            network.assert_not_called()

    def test_request_minimizes_personal_data_and_valid_response(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch("urllib.request.urlopen", return_value=self.response(self.valid)) as network:
            result = deepseek.recommend(self.p, self.pools, self.reference)
        self.assertEqual(result["choices"], self.valid["choices"])
        req = network.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.deepseek.com/chat/completions")
        payload = json.loads(req.data)
        context = json.loads(payload["messages"][1]["content"])
        for field in ("nickname", "age", "sex", "height_cm", "current_weight_kg", "target_weight_kg", "health_status"):
            self.assertNotIn(field, context["profile"])
        self.assertIn("exclusions", context["profile"])

    def test_invalid_id_retries_once_and_does_not_escape_knowledge_base(self):
        invalid = copy.deepcopy(self.valid)
        invalid["choices"]["lunch"] = "anything-the-model-invents"
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch("urllib.request.urlopen", side_effect=[self.response(invalid), self.response(invalid)]) as network:
            with self.assertRaises(Problem) as caught:
                deepseek.recommend(self.p, self.pools, self.reference)
            self.assertEqual(network.call_count, 2)
            self.assertEqual(caught.exception.code, "invalid_model_output")

    def test_repaired_second_response_is_accepted(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch("urllib.request.urlopen", side_effect=[io.BytesIO(b"invalid json"), self.response(self.valid)]) as network:
            result = deepseek.recommend(self.p, self.pools, self.reference)
            self.assertEqual(network.call_count, 2)
            self.assertEqual(result["choices"], self.valid["choices"])

    def test_auth_quota_timeout_and_model_refusal_are_actionable(self):
        errors = [(urllib.error.HTTPError("https://api.deepseek.com", 401, "secret-upstream-message", {}, None), "upstream_auth"),
                  (urllib.error.HTTPError("https://api.deepseek.com", 429, "quota", {}, None), "upstream_quota"),
                  (TimeoutError(), "upstream_network")]
        for failure, code in errors:
            with self.subTest(code=code), patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch("urllib.request.urlopen", side_effect=failure):
                with self.assertRaises(Problem) as caught:
                    deepseek.recommend(self.p, self.pools, self.reference)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("secret-upstream-message", str(caught.exception))
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only"}), patch("urllib.request.urlopen", return_value=self.response({"blocked": True})):
            with self.assertRaises(Problem) as caught:
                deepseek.recommend(self.p, self.pools, self.reference)
            self.assertEqual(caught.exception.code, "safety_boundary")


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.app = Application(Path(cls.temp.name) / "http.sqlite3")
        cls.server = Server(("127.0.0.1", 0), cls.app)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def request(self, path, method="GET", body=None, headers=None):
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=h, method=method)
        try:
            with self.opener.open(req, timeout=5) as response:
                return response.status, json.loads(response.read()), response.headers
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read()), exc.headers

    def test_http_round_trip(self):
        status, data, headers = self.request("/api/status")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, data, _ = self.request("/api/profile", "PUT", {"profile": profile(), "expected_version": 0})
        self.assertEqual(status, 200)
        self.assertEqual(data["profile"]["version"], 1)
        status, data, _ = self.request("/api/plans/generate", "POST", {"date": DAY, "mode": "demo"})
        self.assertEqual(status, 200)
        self.assertEqual(data["plan"]["version"], 1)
        status, data, _ = self.request("/api/plans?date=" + DAY)
        self.assertEqual(status, 200)
        self.assertEqual(len(data["plan"]["meals"]), 4)

    def test_cross_site_and_rebinding_hosts_are_rejected(self):
        for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/status", headers=headers)[0], 403)

    def test_private_files_and_path_traversal_are_not_served(self):
        for path in ("/.env", "/data/zizai.sqlite3", "/../.env", "/%2e%2e/.env", "/app.py"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_invalid_content_type_and_json_and_date(self):
        self.assertEqual(self.request("/api/profile", "PUT", {}, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/profile", "PUT", [1, 2])[0], 400)
        self.assertEqual(self.request("/api/plans?date=2026-99-88")[0], 400)
        self.assertEqual(self.request("/api/plans")[0], 400)


class ProcessRestartTests(unittest.TestCase):
    def test_actual_server_restart_preserves_database(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "restart.sqlite3"
            saved = None
            for iteration in range(2):
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                process = subprocess.Popen([sys.executable, str(root / "app.py"), "--port", str(port), "--db", str(database)], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def request(path, body=None, method=None):
                    data = json.dumps(body).encode() if body is not None else None
                    req = urllib.request.Request(f"http://127.0.0.1:{port}" + path, data=data,
                        headers={"Content-Type": "application/json"}, method=method or ("POST" if body is not None else "GET"))
                    with opener.open(req, timeout=3) as response:
                        return json.loads(response.read())
                try:
                    for _ in range(100):
                        if process.poll() is not None:
                            self.fail("Test server exited before becoming ready")
                        try:
                            request("/api/status")
                            break
                        except (urllib.error.URLError, ConnectionError):
                            time.sleep(.05)
                    else:
                        self.fail("Test server readiness timeout")
                    if iteration == 0:
                        request("/api/profile", {"profile": profile(), "expected_version": 0}, "PUT")
                        saved = request("/api/plans/generate", {"date": DAY, "mode": "demo"})["plan"]
                    else:
                        self.assertEqual(request("/api/plans?date=" + DAY)["plan"], saved)
                        self.assertEqual(request("/api/profile")["profile"]["data"]["nickname"], "小林")
                finally:
                    process.terminate()
                    process.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
