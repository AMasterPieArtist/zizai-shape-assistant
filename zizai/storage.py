import contextlib
import datetime as dt
import json
import hashlib
import sqlite3
from pathlib import Path

from .core import Problem


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        from .reference import BUNDLE_PATH, CATALOG_VERSION, foods, products, recipes
        # Validate every reference row before touching the database.
        food_rows, product_rows, recipe_rows = foods(), products(), recipes()
        fingerprint = hashlib.sha256(BUNDLE_PATH.read_bytes()).hexdigest()
        self.path = Path(path)
        existing = self.path.exists() and self.path.stat().st_size > 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            has_meta = db.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_meta'").fetchone()
            previous = db.execute("SELECT value FROM catalog_meta WHERE key='fingerprint'").fetchone() if has_meta else None
            needs_import = not previous or previous['value'] != fingerprint
            backup_path = None
            if existing and needs_import:
                backup_dir = self.path.parent / 'backups'
                backup_dir.mkdir(exist_ok=True)
                stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                backup_path = backup_dir / (self.path.stem + '-before-catalog-' + stamp + '.sqlite3')
                with contextlib.closing(sqlite3.connect(backup_path)) as target:
                    db.backup(target)  # Consistent snapshot, including any committed WAL records.
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL,
                    version INTEGER NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plans (
                    id INTEGER PRIMARY KEY, date TEXT NOT NULL UNIQUE,
                    data TEXT NOT NULL, profile_version INTEGER NOT NULL,
                    profile_snapshot TEXT NOT NULL, version INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS adjustments (
                    id INTEGER PRIMARY KEY, plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
                    base_version INTEGER NOT NULL, request TEXT NOT NULL,
                    before_data TEXT NOT NULL, candidate TEXT NOT NULL,
                    message TEXT NOT NULL, changes TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','discarded','superseded')),
                    source TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT);
                CREATE TABLE IF NOT EXISTS foods (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, event TEXT NOT NULL, date TEXT,
                    metadata TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reference_products (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS recipe_templates (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS coach_preferences (
                    scope TEXT PRIMARY KEY, collapsed INTEGER NOT NULL CHECK(collapsed IN (0,1)),
                    updated_at TEXT NOT NULL);
                PRAGMA user_version=3;
            """)
            if needs_import:
                db.execute("BEGIN IMMEDIATE")
                for food in food_rows:
                    db.execute("INSERT INTO foods(id,data) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (food['id'], dumps(food)))
                db.execute("DELETE FROM reference_products")
                db.execute("DELETE FROM recipe_templates")
                db.executemany("INSERT INTO reference_products VALUES (?,?)", [(r['record_id'], dumps(r)) for r in product_rows])
                db.executemany("INSERT INTO recipe_templates VALUES (?,?)", [(r['recipe_id'], dumps(r)) for r in recipe_rows])
                meta = {'version': CATALOG_VERSION, 'fingerprint': fingerprint, 'imported_at': now(),
                        'backup_path': str(backup_path) if backup_path else ''}
                for key, value in meta.items():
                    db.execute("INSERT INTO catalog_meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    @contextlib.contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def foods(self):
        with self.connect() as db:
            return {r["id"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM foods ORDER BY id")}

    def products(self):
        with self.connect() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM reference_products ORDER BY id')]

    def recipes(self):
        with self.connect() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM recipe_templates ORDER BY id')]

    def catalog_info(self):
        with self.connect() as db:
            meta = {r['key']: r['value'] for r in db.execute('SELECT * FROM catalog_meta')}
            counts = {name: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                      for name, table in [('foods', 'foods'), ('products', 'reference_products'), ('recipes', 'recipe_templates')]}
        counts['available_products'] = sum(r['calculation_use'] == 'exact_product_serving' for r in self.products())
        counts['main_templates'] = sum(r['category'] == '正餐' for r in self.recipes())
        counts['main_products'] = sum(r['category'] == '正餐产品' for r in self.products())
        counts['meal_templates'] = sum(r['category'] != '自配饮品' for r in self.recipes())
        return dict(meta, **counts)

    def profile(self, db=None):
        if db is None:
            with self.connect() as con:
                return self.profile(con)
        row = db.execute("SELECT * FROM profiles WHERE id=1").fetchone()
        return {"data": json.loads(row["data"]), "version": row["version"], "updated_at": row["updated_at"]} if row else None

    def save_profile(self, p, expected):
        with self.connect(True) as db:
            old = self.profile(db)
            if (old["version"] if old else 0) != expected:
                raise Problem("画像已在其他页面更新，请刷新后重试。", 409, "conflict")
            db.execute("INSERT INTO profiles VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data,version=excluded.version,updated_at=excluded.updated_at", (dumps(p), expected + 1, now()))
            self.event("profile_saved", None, {"version": expected + 1}, db)
            return self.profile(db)

    def plan(self, day, db=None):
        if db is None:
            with self.connect() as con:
                return self.plan(day, con)
        row = db.execute("SELECT * FROM plans WHERE date=?", (day,)).fetchone()
        if not row:
            return None
        data = json.loads(row["data"])
        data.update(id=row["id"], version=row["version"], profile_version=row["profile_version"], updated_at=row["updated_at"])
        return data

    def check_versions(self, db, day, expected, profile_version=None):
        plan = self.plan(day, db)
        if (plan["version"] if plan else 0) != expected:
            raise Problem("计划已变化，请刷新后重试，避免覆盖新的选择。", 409, "conflict")
        if profile_version is not None:
            profile = self.profile(db)
            if not profile or profile["version"] != profile_version:
                raise Problem("画像已经变化，请基于新画像重新生成计划。", 409, "profile_changed")
        return plan

    def save_plan(self, data, expected, profile, event="plan_generated", metadata=None):
        with self.connect(True) as db:
            old = self.check_versions(db, data["date"], expected, profile["version"])
            stamp = now()
            db.execute("""INSERT INTO plans(date,data,profile_version,profile_snapshot,version,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET data=excluded.data,
                profile_version=excluded.profile_version,profile_snapshot=excluded.profile_snapshot,
                version=excluded.version,updated_at=excluded.updated_at""",
                (data["date"], dumps(data), profile["version"], dumps(profile["data"]), expected + 1, stamp, stamp))
            if old:
                db.execute("UPDATE adjustments SET status='superseded',resolved_at=? WHERE plan_id=? AND status='pending'", (stamp, old["id"]))
            self.event(event, data["date"], metadata or {"source": data["source"], "versions": data["versions"]}, db)
            return self.plan(data["date"], db)

    def adjustments(self, day, db=None):
        if db is None:
            with self.connect() as con:
                return self.adjustments(day, con)
        rows = db.execute("SELECT a.* FROM adjustments a JOIN plans p ON a.plan_id=p.id WHERE p.date=? ORDER BY a.id DESC", (day,)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for key in ("before_data", "candidate", "changes"):
                item[key] = json.loads(item[key])
            result.append(item)
        return result

    def save_draft(self, plan, candidate, request, message, changes, source, profile):
        with self.connect(True) as db:
            self.check_versions(db, plan["date"], plan["version"], profile["version"])
            db.execute("""INSERT INTO adjustments(plan_id,base_version,request,before_data,candidate,message,changes,status,source,created_at)
                VALUES (?,?,?,?,?,?,?,'pending',?,?)""", (plan["id"], plan["version"], request, dumps(plan), dumps(candidate), message, dumps(changes), source, now()))
            self.event("adjustment_requested", plan["date"], {"source": source, "changed_meals": changes}, db)
            return self.adjustments(plan["date"], db)[0]

    def resolve_draft(self, draft_id, action):
        with self.connect(True) as db:
            row = db.execute("SELECT * FROM adjustments WHERE id=?", (draft_id,)).fetchone()
            if not row:
                raise Problem("找不到该调整记录。", 404)
            if row["status"] != "pending":
                raise Problem("草案已经处理或过期，请刷新记录。", 409, "conflict")
            candidate = json.loads(row["candidate"])
            if action == "confirm":
                self.check_versions(db, candidate["date"], row["base_version"], candidate["profile_version"])
                db.execute("UPDATE plans SET data=?,version=version+1,updated_at=? WHERE id=?", (dumps(candidate), now(), row["plan_id"]))
                db.execute("UPDATE adjustments SET status='superseded',resolved_at=? WHERE plan_id=? AND status='pending' AND id!=?", (now(), row["plan_id"], draft_id))
            db.execute("UPDATE adjustments SET status=?,resolved_at=? WHERE id=?", ("confirmed" if action == "confirm" else "discarded", now(), draft_id))
            self.event("adjustment_resolved", candidate["date"], {"action": action, "draft_id": draft_id}, db)
            return self.plan(candidate["date"], db)

    def excluded_ids(self, day, meal):
        with self.connect() as db:
            records = db.execute("""SELECT metadata FROM events WHERE date=?
                AND id > COALESCE((SELECT MAX(id) FROM events WHERE date=? AND event='plan_generated'),0)
                AND event IN ('options_refreshed','option_unavailable','option_disliked')""", (day, day)).fetchall()
        result = set()
        for row in records:
            data = json.loads(row["metadata"])
            if data.get("meal") == meal:
                result.update(data.get("excluded", []))
        return result

    def event(self, event, day, metadata, db=None):
        if db is None:
            with self.connect(True) as con:
                return self.event(event, day, metadata, con)
        db.execute("INSERT INTO events(event,date,metadata,created_at) VALUES (?,?,?,?)", (event, day, dumps(metadata), now()))

    def companion(self, day):
        from .coach import companion_card, history_window, profile_scope
        with self.connect() as db:
            # One read transaction prevents mixing a profile with a concurrently
            # edited profile's plan or preferences.
            db.execute('BEGIN')
            p = self.profile(db)
            if not p:
                return None
            start, end = history_window(day)
            rows = db.execute('SELECT date,profile_snapshot,data FROM plans WHERE date BETWEEN ? AND ? ORDER BY date', (start, end)).fetchall()
            history = [{'date': r['date'], 'profile_snapshot': json.loads(r['profile_snapshot']), 'data': json.loads(r['data'])} for r in rows]
            pref = db.execute('SELECT collapsed FROM coach_preferences WHERE scope=?', (profile_scope(p['data']),)).fetchone()
            return companion_card(p, self.plan(day, db), history, day, bool(pref['collapsed']) if pref else False)

    def save_coach_preference(self, collapsed, expected_profile_version):
        from .coach import profile_scope
        with self.connect(True) as db:
            p = self.profile(db)
            if not p or p['version'] != expected_profile_version:
                raise Problem('画像已变化，请刷新后再设置陪伴卡片。', 409, 'profile_changed')
            db.execute('INSERT INTO coach_preferences VALUES (?,?,?) ON CONFLICT(scope) DO UPDATE SET collapsed=excluded.collapsed,updated_at=excluded.updated_at',
                       (profile_scope(p['data']), int(collapsed), now()))

    def export(self):
        with self.connect() as db:
            days = [r[0] for r in db.execute("SELECT date FROM plans ORDER BY date DESC")]
            return {"format_version": 1, "exported_at": now(), "profile": self.profile(db),
                    "plans": [self.plan(day, db) for day in days],
                    "adjustments": [a for day in days for a in self.adjustments(day, db)],
                    "events": [dict(r) | {"metadata": json.loads(r["metadata"])} for r in db.execute("SELECT * FROM events ORDER BY id")],
                    "coach_preferences": [dict(r) | {"collapsed": bool(r['collapsed'])} for r in db.execute('SELECT * FROM coach_preferences ORDER BY scope')]}

    def delete_personal(self):
        with self.connect(True) as db:
            for table in ("adjustments", "plans", "profiles", "events", "coach_preferences"):
                db.execute(f"DELETE FROM {table}")
        with self.connect() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
