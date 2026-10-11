#!/usr/bin/env python3
"""Run: python app.py. Python 3.10+; standard library only."""
import argparse
import copy
import json
import mimetypes
import os
import sqlite3
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from zizai import deepseek
from zizai.core import (FOCUSES, LABELS, MEALS, VERSIONS, Problem, adjusted_plan, choice,
                        date_value, make_plan, number, pools_for, profile_value,
                        safe_request, snack_catalog, strategy_for, text, validate_plan, diverse_candidates)
from zizai.storage import Store, dumps

ROOT = Path(__file__).resolve().parent


class Application:
    def __init__(self, database):
        self.store = Store(database)

    def profile_required(self):
        p = self.store.profile()
        if not p:
            raise Problem("请先完成并保存用户画像。", 409, "profile_required")
        return p

    def plan_required(self, body):
        day = date_value(body.get("date"))
        plan = self.store.plan(day)
        if not plan:
            raise Problem("这一天还没有计划，请先生成。", 404, "plan_required")
        expected = number(body.get("expected_version"), "计划版本", 1, 1000000, True)
        if expected != plan["version"]:
            raise Problem("计划已经变化，请刷新后重试。", 409, "conflict")
        p = self.profile_required()
        if p["version"] != plan["profile_version"]:
            raise Problem("画像已经修改。请先重新生成计划，以确保新忌口和偏好生效。", 409, "profile_changed")
        return plan, p

    def get(self, path, query):
        if path == "/api/status":
            return {"ok": True, "app": "自在身材", "version": "0.3.0", "deepseek_configured": deepseek.configured(),
                    "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"), "versions": VERSIONS,
                    "catalog": self.store.catalog_info(), "frontend_available": (ROOT / "web" / "index.html").is_file(),
                    "scope": "本地单用户原型；营养数据与规则待专业复核"}
        if path == "/api/profile":
            return {"profile": self.store.profile()}
        if path == "/api/coach":
            return {"coach": self.store.companion(date_value(query.get('date', [None])[0]))}
        if path == "/api/plans":
            day = date_value(query.get("date", [None])[0])
            return {"plan": self.store.plan(day)}
        if path == "/api/adjustments":
            day = date_value(query.get("date", [None])[0])
            return {"adjustments": self.store.adjustments(day)}
        if path == "/api/foods":
            term = text(query.get("q", [""])[0], "食品关键词", 60)
            category = text(query.get("category", [""])[0], "分类", 20)
            foods = list(self.store.foods().values())
            return {"foods": [f for f in foods if (not term or term in f["name"] or term in f["category"]) and (not category or f["category"] == category)],
                    "note": "营养为每100克基础食品参考估算；未完成逐条专业复核，不代表具体餐厅或品牌数据。"}
        if path == "/api/recipes":
            return {"recipes": self.store.recipes(), "catalog": self.store.catalog_info()}
        if path == "/api/snacks":
            return {"snacks": snack_catalog(self.store.foods(), self.store.products(), self.store.recipes())}
        if path == "/api/export":
            return self.store.export()
        raise Problem("接口不存在。", 404, "not_found")

    def meal_options(self, p, meal, scene):
        # An explicit takeout choice changes this search's scene, not the profile.
        context = copy.deepcopy(p["data"])
        if scene == "delivery":
            context["meal_sources"] = ["delivery"]
        _, pools = pools_for(context, self.store.foods(), self.store.recipes(), self.store.products())
        return pools[meal]

    def mutate(self, method, path, body):
        if method == 'POST' and path == '/api/coach/preferences':
            collapsed = body.get('collapsed')
            if not isinstance(collapsed, bool):
                raise Problem('收起状态必须为 true 或 false。')
            expected = number(body.get('expected_profile_version'), '画像版本', 1, 1000000, True)
            day = date_value(body.get('date'))
            self.store.save_coach_preference(collapsed, expected)
            return {'coach': self.store.companion(day)}
        if method == "PUT" and path == "/api/profile":
            expected = number(body.get("expected_version", 0), "画像版本", 0, 1000000, True)
            p = profile_value(body.get("profile"))
            return {"profile": self.store.save_profile(p, expected)}
        if method == "POST" and path == "/api/plans/generate":
            day = date_value(body.get("date"))
            mode = choice(body.get("mode", "demo"), "生成方式", ["demo", "deepseek"])
            expected = number(body.get("expected_version", 0), "计划版本", 0, 1000000, True)
            p = self.profile_required()
            old = self.store.plan(day)
            if (old["version"] if old else 0) != expected:
                raise Problem("计划已变化，请刷新后重试。", 409, "conflict")
            if old and any(m["completed"] for m in old["meals"].values()) and body.get("reset_completed") is not True:
                raise Problem("这一天已有完成的餐次。重新生成会重置完成状态，请明确确认后再提交。", 409, "completed_reset_required")
            reference, pools = pools_for(p["data"], self.store.foods(), self.store.recipes(), self.store.products())
            try:
                ai = deepseek.recommend(p["data"], pools, reference) if mode == "deepseek" else None
                plan = make_plan(p["data"], self.store.foods(), day, mode, ai, offset=expected, recipe_templates=self.store.recipes(), product_rows=self.store.products())
                return {"plan": self.store.save_plan(plan, expected, p)}
            except Problem as exc:
                self.store.event("plan_failed", day, {"code": exc.code, "source": mode, "versions": VERSIONS})
                raise
        if method == "POST" and path == "/api/meals/search":
            plan, p = self.plan_required(body)
            meal = choice(body.get("meal"), "餐次", MEALS)
            scene = choice(body.get("scene", "profile"), "选餐场景", ["profile", "delivery"])
            if scene == "delivery" and meal not in ("lunch", "dinner"):
                raise Problem("外卖入口支持午餐和晚餐。")
            query = text(body.get("query", ""), "餐食关键词", 60).casefold()
            family = text(body.get("family", ""), "餐食类型", 30)
            offset = number(body.get("offset", 0), "结果起点", 0, 10000, True)
            limit = number(body.get("limit", 6), "每页数量", 1, 12, True)
            excluded = body.get("exclude_ids", [])
            if not isinstance(excluded, list) or len(excluded) > 200 or any(not isinstance(x, str) or len(x) > 40 for x in excluded):
                raise Problem("已查看的方案编号格式错误。")
            options = self.meal_options(p, meal, scene)
            matches = []
            for o in options:
                searchable = " ".join([o["title"], o.get("meal_family", ""), *[i["name"] for i in o["ingredients"]]]).casefold()
                if o["id"] not in excluded and (not family or o.get("meal_family") == family) and all(t in searchable for t in query.split()):
                    matches.append(o)
            ordered = diverse_candidates(matches, len(matches))
            return {"options": ordered[offset:offset + limit], "total": len(ordered), "offset": offset,
                    "has_more": offset + limit < len(ordered), "scene": scene,
                    "plan_version": plan["version"], "note": "符合当前画像限制的示例配餐；未连接实时门店。"}
        if method == "POST" and path == "/api/meals/optional":
            plan, p = self.plan_required(body)
            if body.get("meal") != "snack" or not isinstance(body.get("enabled"), bool):
                raise Problem("只有下午茶可以设为可选，enabled 必须为 true 或 false。")
            if plan["meals"]["snack"]["completed"]:
                raise Problem("下午茶已标记完成。请先取消完成标记，再取消安排。", 409, "meal_completed")
            if plan["meals"]["snack"].get("enabled", True) == body["enabled"]:
                return {"plan": plan}
            updated = copy.deepcopy(plan)
            updated["meals"]["snack"]["enabled"] = body["enabled"]
            validate_plan(updated, p["data"])
            return {"plan": self.store.save_plan(updated, plan["version"], p, "optional_snack_changed", {"enabled": body["enabled"]})}
        if method == "POST" and path in ("/api/meals/select", "/api/meals/complete", "/api/meals/refresh"):
            plan, p = self.plan_required(body)
            meal = choice(body.get("meal"), "餐次", MEALS)
            state = plan["meals"][meal]
            if meal == "snack" and state.get("enabled", True) is False:
                raise Problem("今天未安排下午茶。请先恢复安排，再选餐或标记完成。", 409, "meal_disabled")
            updated = copy.deepcopy(plan)
            target = updated["meals"][meal]
            metadata = {"meal": meal}
            if path.endswith("/complete"):
                completed = body.get("completed")
                if not isinstance(completed, bool):
                    raise Problem("完成状态必须为 true 或 false。")
                target["completed"] = completed
                event = "meal_completed" if completed else "meal_reopened"
                metadata["option_id"] = target["selected"]["id"]
            else:
                if state["completed"]:
                    raise Problem("这餐已完成，暂不替换。需要修改时请先取消完成标记。", 409, "meal_completed")
                if path.endswith("/select"):
                    oid = text(body.get("option_id"), "方案编号", 40, True)
                    selection_source = choice(body.get("selection_source", "batch"), "选择来源", ["batch", "catalog"])
                    scene = choice(body.get("scene", "profile"), "选餐场景", ["profile", "delivery"])
                    if scene == "delivery" and meal not in ("lunch", "dinner"):
                        raise Problem("外卖入口支持午餐和晚餐。")
                    allowed = self.meal_options(p, meal, scene) if selection_source == "catalog" else state["candidates"]
                    selected = next((x for x in allowed if x["id"] == oid), None)
                    if selected is None:
                        raise Problem("该方案不在当前可选范围中，请重新搜索或刷新后选择。", 409, "unknown_option")
                    target["selected"] = copy.deepcopy(selected)
                    event, metadata["option_id"] = "option_adopted", oid
                    metadata.update(selection_source=selection_source, scene=scene)
                else:
                    reason = choice(body.get("reason", "refresh"), "换一批原因", ["refresh", "unavailable", "dislike"])
                    excluded = self.store.excluded_ids(plan["date"], meal)
                    current_ids = [x["id"] for x in state["candidates"]]
                    excluded.update(current_ids)
                    _, pools = pools_for(p["data"], self.store.foods(), self.store.recipes(), self.store.products())
                    family = text(body.get("family", ""), "餐食类型", 30)
                    choices = [x for x in pools[meal] if x["id"] not in excluded and (not family or x.get("meal_family") == family)]
                    if not choices:
                        raise Problem("当前类型没有更多满足条件的新候选，本次未替换。可以选择其他餐食类型，或采用已显示的方案；当前计划保持不变。", 422, "candidates_exhausted")
                    target["candidates"] = diverse_candidates(choices)
                    target["batch"] += 1
                    event = {"refresh": "options_refreshed", "unavailable": "option_unavailable", "dislike": "option_disliked"}[reason]
                    metadata.update(reason=reason, excluded=current_ids, batch=target["batch"], family=family)
            validate_plan(updated, p["data"])
            return {"plan": self.store.save_plan(updated, plan["version"], p, event, metadata)}
        if method == "POST" and path == "/api/adjustments":
            plan, p = self.plan_required(body)
            request = text(body.get("request"), "调整内容", 600, True)
            safe_request(request)
            mode = choice(body.get("mode", "demo"), "调整方式", ["demo", "deepseek"])
            reference, pools = pools_for(p["data"], self.store.foods(), self.store.recipes(), self.store.products())
            try:
                ai = deepseek.recommend(p["data"], pools, reference, request, plan) if mode == "deepseek" else None
                candidate, message, changes = adjusted_plan(plan, p["data"], self.store.foods(), request, mode, ai, recipe_templates=self.store.recipes(), product_rows=self.store.products())
                draft = self.store.save_draft(plan, candidate, request, message, changes, mode, p)
                return {"adjustment": draft, "plan_changed": False}
            except Problem as exc:
                self.store.event("adjustment_failed", plan["date"], {"code": exc.code, "source": mode})
                raise
        if method == "POST" and path.startswith("/api/adjustments/"):
            parts = path.strip("/").split("/")
            if len(parts) != 4 or not parts[2].isdigit() or parts[3] not in ("confirm", "discard"):
                raise Problem("调整操作不存在。", 404)
            return {"plan": self.store.resolve_draft(int(parts[2]), parts[3])}
        if method == "POST" and path == "/api/feedback":
            plan, _ = self.plan_required(body)
            score = number(body.get("score"), "生活适配评分", 1, 5, True)
            comment = text(body.get("comment", ""), "反馈", 300)
            self.store.event("life_fit_rated", plan["date"], {"score": score, "comment": comment})
            return {"saved": True}
        if method == "POST" and path in ("/api/snacks/add", "/api/snacks/remove", "/api/activities/add", "/api/activities/remove", "/api/activities/rest"):
            plan, p = self.plan_required(body)
            updated = copy.deepcopy(plan)
            updated.setdefault("snacks", [])
            updated.setdefault("activities", [])
            metadata = {}
            if path == "/api/snacks/add":
                item = next((x for x in snack_catalog(self.store.foods(), self.store.products(), self.store.recipes()) if x["id"] == body.get("snack_id")), None)
                if not item:
                    raise Problem("食品不在当前知识库中。")
                from zizai.reference import blocked_ingredients
                if blocked_ingredients(item["ingredients"], self.store.foods(), p["data"]["exclusions"]) or set(item["tags"]) & set(p["data"]["exclusions"]) or (p["data"]["exclusions"] and (not item["ingredients"] or item.get("allergen_check_required"))):
                    raise Problem("该小食与忌口冲突，或未知配料无法可靠排除你的忌口。本次未添加。", 422, "exclusion_conflict")
                if len(updated["snacks"]) >= 12:
                    raise Problem("当天附加小食已达原型记录上限，请先核对或移除重复项。", 422)
                item["entry_id"] = uuid.uuid4().hex
                updated["snacks"].append(item)
                metadata = {"food_id": item["id"], "nutrition_known": item["nutrition"] is not None}
            elif path.endswith("/remove"):
                field = "snacks" if "/snacks/" in path else "activities"
                entry = text(body.get("entry_id"), "记录编号", 40, True)
                found = [x for x in updated[field] if x["entry_id"] != entry]
                if len(found) == len(updated[field]):
                    raise Problem("这条记录已经移除，请刷新。", 409, "conflict")
                updated[field] = found
            elif path == "/api/activities/rest":
                updated["movement"] = "今天先休息，给身体一点恢复的时间。不需要通过运动补偿饮食。"
                updated["activities"] = []
            else:
                kind = choice(body.get("kind"), "运动类型", ["walk", "swim"])
                minutes = number(body.get("minutes"), "运动时长", 5, 180, True)
                if len(updated["activities"]) >= 8:
                    raise Problem("今日运动记录已达原型上限，请先检查是否重复添加。", 422)
                met = 3.8 if kind == "walk" else 6
                energy = round(met * p["data"]["current_weight_kg"] * minutes / 60) if 19 <= p["data"]["age"] <= 59 else None
                updated["activities"].append({"entry_id": uuid.uuid4().hex, "kind": kind, "name": "中速步行" if kind == "walk" else "休闲游泳",
                    "minutes": minutes, "met": met, "kcal": energy, "weight_kg": p["data"]["current_weight_kg"],
                    "source": "2024 身体活动汇编；原型采用的示例 MET，待专业复核", "source_url": "https://pacompendium.com/",
                    "note": "MET × kg × 小时，包含静息消耗，不从饮食能量中抵扣。"})
                metadata = {"kind": kind, "minutes": minutes}
            return {"plan": self.store.save_plan(updated, plan["version"], p, path.rsplit("/", 2)[-2] + "_" + path.rsplit("/", 1)[-1], metadata)}
        if method == "POST" and path == "/api/strategy/draft":
            plan, p = self.plan_required(body)
            request = text(body.get("request", ""), "策略想法", 300)
            safe_request(request)
            focus = body.get("focus")
            if focus is None:
                import re
                focus = "作息优先" if re.search("睡|累|加班|休息", request) else "运动优先" if re.search("运动|游泳|久坐", request) else "饮食优先" if re.search("饮食|吃|餐", request) else None
            if focus is None:
                raise Problem("策略重点使用本地模板，可识别饮食、运动、作息。请直接选择重点，或到动态调整使用 DeepSeek。", 422, "demo_scope")
            choice(focus, "策略重点", FOCUSES)
            candidate = copy.deepcopy(plan)
            candidate["strategy_focus"] = focus
            data = strategy_for(p["data"], focus)
            message = f"先把重点放在{data['focus']}。" + " ".join(data["items"])
            candidate["strategy"] = message
            return {"adjustment": self.store.save_draft(plan, candidate, request or focus, message, ["个人策略"], "demo", p), "plan_changed": False}
        if method == "POST" and path == "/api/data/delete":
            if body.get("confirmation") != "删除我的本地数据":
                raise Problem("请明确确认删除本地画像、计划、调整记录和反馈。")
            self.store.delete_personal()
            return {"deleted": True}
        raise Problem("接口或请求方式不存在。", 404, "not_found")


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app):
        self.app = app
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "ZizaiLocal/0.1"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Paths can contain user search text; omit request bodies, URLs and headers.
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        super().end_headers()

    def send_json(self, data, status=200):
        payload = dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def check_local(self):
        port = self.server.server_address[1]
        hosts = {f"localhost:{port}", f"127.0.0.1:{port}"}
        if self.headers.get("Host") not in hosts:
            raise Problem("此服务仅接受本机访问。", 403, "local_only")
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + host for host in hosts}:
            raise Problem("不允许其他网站发起此请求。", 403, "origin_rejected")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise Problem("不允许跨站请求。", 403, "origin_rejected")

    def read_body(self):
        if self.headers.get("Transfer-Encoding"):
            raise Problem("不支持此请求传输方式。", 400)
        if self.headers.get_content_type() != "application/json":
            raise Problem("请求应使用 application/json。", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise Problem("请求长度无效。")
        if not 0 < length <= 32768:
            raise Problem("请求为空或超过 32KB。", 413)
        try:
            body = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(body, dict):
                raise ValueError()
            return body
        except (ValueError, UnicodeDecodeError):
            raise Problem("请求不是有效的 JSON 对象。")

    def handle_request(self):
        self.connection.settimeout(100)
        try:
            self.check_local()
            url = urlsplit(self.path)
            if url.path.startswith("/api/"):
                if self.command == "GET":
                    data = self.server.app.get(url.path, parse_qs(url.query))
                else:
                    data = self.server.app.mutate(self.command, url.path, self.read_body())
                return self.send_json(data)
            if self.command != "GET":
                raise Problem("请求方式不支持。", 405)
            # Only serve explicit frontend files. Never expose .env or the database.
            static = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/extras.js": "extras.js", "/style.css": "style.css", "/food.jpg": "food.jpg", "/favicon.svg": "favicon.svg"}
            if url.path not in static:
                raise Problem("文件不存在。", 404)
            path = ROOT / "web" / static[url.path]
            if not path.is_file():
                raise Problem("后端已启动。现有交互页面的源码尚待导入；请先使用 /api/status 检查接口。", 503, "frontend_pending")
            data = path.read_bytes()
            self.send_response(200)
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else ""))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Problem as exc:
            self.send_json({"error": {"code": exc.code, "message": str(exc)}}, exc.status)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except sqlite3.Error:
            self.send_json({"error": {"code": "database_error", "message": "本地数据库暂时无法读写，请检查磁盘空间、文件权限或稍后重试。"}}, 503)
        except Exception:
            # No raw exception text: it might contain model output or sensitive profile data.
            self.send_json({"error": {"code": "internal_error", "message": "服务出现内部错误，请重试；如持续发生，请运行项目自测。"}}, 500)

    do_GET = handle_request
    do_POST = handle_request
    do_PUT = handle_request


def main():
    parser = argparse.ArgumentParser(description="自在身材，本地单用户后端")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "zizai.sqlite3")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1–65535 之间。")
    deepseek.load_env(ROOT / ".env")
    app = Application(args.db)
    try:
        server = Server(("127.0.0.1", args.port), app)
    except OSError:
        print("启动失败：端口可能已占用。可用 python app.py --port 8766 重试。", file=sys.stderr)
        return 1
    print(f"自在身材后端已启动：127.0.0.1:{args.port}（Ctrl+C 停止）", flush=True)
    print("DeepSeek：" + ("已配置；仍需画像授权" if deepseek.configured() else "未配置，可使用本地演示接口"), flush=True)
    if not (ROOT / "web" / "index.html").is_file():
        print("交互页面尚待导入，当前仅提供后端接口。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。已保存的数据将在下次启动时保留。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
