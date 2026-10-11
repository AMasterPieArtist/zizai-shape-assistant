"""Optional browser smoke test. Needs Playwright and Chromium; not runtime deps.

    python tests/browser_smoke.py http://127.0.0.1:8765

Run against an EMPTY throwaway database, never a personal database.
"""
import json
import re
import shutil
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
out = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
out.mkdir(exist_ok=True)

with sync_playwright() as pw:
    executable = shutil.which("chromium") or shutil.which("google-chrome")
    browser = pw.chromium.launch(executable_path=executable, headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1100})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base)
    expect(page.get_by_role("heading", name=re.compile("好好吃，.*慢慢来。"))).to_be_visible()
    page.get_by_role("link", name="开始定制", exact=True).click()
    page.get_by_label("怎么称呼你", exact=True).fill("测试小满")
    page.get_by_label("健康情况（请选择）", exact=True).select_option("general")
    page.get_by_role("button", name="下一步", exact=True).click()
    page.get_by_role("button", name="下一步", exact=True).click()
    page.get_by_role("button", name="保存画像，查看策略", exact=True).click()
    expect(page.get_by_role("heading", name="适合你的，比标准答案更重要")).to_be_visible()
    page.get_by_role("button", name="生成今日计划", exact=True).click()
    expect(page.get_by_role("heading", name="测试小满，今天也好好吃饭")).to_be_visible(timeout=15000)
    page.wait_for_function("() => !state.busy")
    original = page.evaluate("state.plan.version")
    page.locator('[data-action="meal-route"][data-meal="lunch"]').click()
    expect(page.locator(".option")).to_have_count(3)
    old_ids = page.locator('[data-action="choose"]').evaluate_all("(els)=>els.map(e=>e.dataset.id)")
    page.get_by_role("button", name="没有这些菜", exact=True).click()
    page.wait_for_function("() => !state.busy")
    new_ids = page.locator('[data-action="choose"]').evaluate_all("(els)=>els.map(e=>e.dataset.id)")
    assert not set(old_ids) & set(new_ids), (old_ids, new_ids)
    page.get_by_role("button", name="选择这个", exact=True).first.click()
    page.wait_for_function("() => !state.busy")
    selected = page.evaluate("state.plan.meals.lunch.selected.id")
    page.reload()
    page.wait_for_function("() => state.initialized")
    assert page.evaluate("state.plan.meals.lunch.selected.id") == selected
    page.locator('#nav a[href="#snacks"]').click()
    page.locator('[data-action="add-snack"][data-id="yogurt"]').click()
    page.wait_for_function("() => !state.busy")
    assert page.evaluate("state.plan.snacks.length") == 1
    page.locator('#nav a[href="#activity"]').click()
    page.get_by_role("button", name="添加运动", exact=True).click()
    page.wait_for_function("() => !state.busy")
    assert page.evaluate("state.plan.activities.length") == 1
    page.locator('#nav a[href="#adjust"]').click()
    version = page.evaluate("state.plan.version")
    page.get_by_role("button", name="今晚和朋友吃火锅", exact=True).click()
    page.get_by_role("button", name="查看演示调整草案", exact=True).click()
    page.wait_for_function("() => !state.busy")
    expect(page.get_by_role("button", name="确认并应用调整", exact=True)).to_be_visible()
    assert page.evaluate("state.plan.version") == version
    page.screenshot(path=str(out / "adjustment.png"), full_page=True)
    page.get_by_role("button", name="确认并应用调整", exact=True).click()
    page.wait_for_function("() => !state.busy")
    assert page.evaluate("state.plan.version") == version + 1
    page.reload()
    page.wait_for_function("() => state.initialized")
    assert page.evaluate("state.plan.snacks.length") == 1
    assert page.evaluate("state.plan.activities.length") == 1
    page.locator('#nav a[href="#home"]').click()
    expect(page.get_by_role("heading", name="测试小满，今天也好好吃饭")).to_be_visible()
    page.screenshot(path=str(out / "desktop.png"), full_page=True, animations="disabled")
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(out / "mobile.png"), full_page=True, animations="disabled")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), page.evaluate("[document.documentElement.scrollWidth,innerWidth]")
    assert not errors, errors
    print(json.dumps({"browser": "Chromium", "flow": "onboarding, generation, candidates, adopt, reload, snack, activity, draft, confirm, reload", "versions": [original, version + 1], "console_errors": errors, "mobile_overflow": False}, ensure_ascii=False))
    browser.close()
