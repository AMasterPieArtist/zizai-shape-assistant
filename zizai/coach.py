"""Truthful local companion cards; no model calls or inferred health outcomes."""
import datetime as dt
import hashlib
import json


def profile_scope(profile):
    # There is no account identity in this single-user prototype. Match all
    # saved profile fields conservatively, except the transport consent flag.
    data = {k: v for k, v in profile.items() if k != 'ai_consent'}
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def history_window(day, today=None):
    selected = dt.date.fromisoformat(day)
    end = min(selected, today or dt.date.today())
    return (end - dt.timedelta(days=6)).isoformat(), end.isoformat()


def companion_card(profile, plan, history, day, collapsed=False, today=None):
    """History items have date, profile_snapshot, data; never count future plans."""
    start, end = history_window(day, today)
    scope = profile_scope(profile['data'])
    matched = [r for r in history if start <= r['date'] <= end
               and profile_scope(r['profile_snapshot']) == scope]
    completed_days = 0
    completed_meals = 0
    for row in matched:
        count = sum(1 for m in row['data'].get('meals', {}).values()
                    if m.get('enabled', True) and m.get('completed') is True)
        completed_days += int(count > 0)
        completed_meals += count
    stats = {'planned_days': len({r['date'] for r in matched}),
             'completed_days': completed_days, 'completed_meals': completed_meals}
    stale = bool(plan and plan['profile_version'] != profile['version'])
    if stale:
        kind, message = 'profile_changed', '你的画像更新了。先把计划也更新一下，再一起选一份更适合现在生活的安排。'
        cta = {'label': '更新这一天的计划', 'action': 'generate'}
    elif not plan:
        kind, message = 'start', '我是小自在。先从一顿方便、喜欢的饭开始吧，计划可以随着你的生活慢慢调整。'
        cta = {'label': '安排这一天', 'action': 'generate'}
    elif plan['meals'].get('snack', {}).get('enabled', True) is False:
        kind, message = 'optional_rest', '今天不安排下午茶，也可以按自己的节奏来。三餐仍然保留；如果想加一份饮品或小食，可以自己选择。'
        cta = {'label': '看看饮品与小食', 'route': 'snacks'}
    elif profile['data'].get('work_intensity') == 'busy':
        kind, message = 'busy', '工作节奏忙的时候，照顾自己也可以简单一点。先选一份方便的饭，运动安排再按今天的状态调整。'
        cta = {'label': '和小自在调整计划', 'route': 'adjust'}
    elif completed_days:
        kind, message = 'recorded', '看到你留下了餐次完成记录。谢谢你愿意照顾自己的日常，接下来也可以保留一点弹性。'
        cta = {'label': '看看下一餐的选择', 'route': 'lunch'}
    else:
        kind, message = 'everyday', '今天的安排已经准备好了。遇到不喜欢的菜、临时聚餐或想休息，都可以再调一调，不需要把一天安排得完美。'
        cta = {'label': '和小自在调整计划', 'route': 'adjust'}
    if completed_days >= 3:
        progress = f'最近这段记录里，你在 {completed_days} 天标记过餐次完成。愿意一步步照顾自己，值得给自己一点肯定。'
    elif stats['planned_days'] >= 3:
        progress = f'这段时间，你已经为 {stats["planned_days"]} 天保存过饮食安排。给日常留一点准备，也是照顾自己的一种方式。'
    elif completed_days:
        progress = f'这段时间有 {completed_days} 天留下了餐次完成记录。每一次主动照顾自己，都值得被看见。'
    elif stats['planned_days']:
        progress = '已经有了保存的安排，接下来可以从容易实现的一餐开始。'
    else:
        progress = '还没有可用于回顾的历史记录。我们可以从这一天开始。'
    return {'name': '小自在', 'role': '温暖、务实的日常陪伴教练', 'source': 'local_records',
            'source_label': '本地记录反馈 · 非 AI 生成', 'collapsed': bool(collapsed),
            'profile_version': profile['version'], 'kind': kind, 'message': message, 'cta': cta, 'progress': progress, 'stats': stats,
            'window': {'start': start, 'end': end}, 'view_date': day,
            'record_note': '仅统计与当前画像匹配的最近7天记录；以所选日期为截止，未来日期不计入。保存计划不代表执行，完成状态由你主动标记，不推断实际摄入、运动或减重效果。'}
