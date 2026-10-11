# 本地 API

同源路径 `/api`，JSON 请求和响应。仅绑定本机，不开放 CORS。浏览器从 Python 服务打开页面，不能直接使用 `file://`。

写请求需 `Content-Type: application/json`；上限32KB。错误结构：

```json
{"error":{"code":"conflict","message":"计划已变化，请刷新后重试。"}}
```

| 接口 | 方法 | 主要输入 / 返回 |
| --- | --- | --- |
| `/api/status` | GET | 可用性、版本、是否检测到Key，不返回Key |
| `/api/profile` | GET | `{profile:{data,version,updated_at}}` 或 null |
| `/api/profile` | PUT | `{profile:{…},expected_version:0}`，首次版本0 |
| `/api/plans?date=YYYY-MM-DD` | GET | `{plan:…}` 或 null |
| `/api/plans/generate` | POST | `{date,mode:"demo"或"deepseek",expected_version:0}` |
| `/api/meals/select` | POST | `{date,expected_version,meal,option_id}` |
| `/api/meals/refresh` | POST | `{date,expected_version,meal,reason:"refresh"或"unavailable"或"dislike"}` |
| `/api/meals/complete` | POST | `{date,expected_version,meal,completed:true或false}` |
| `/api/adjustments?date=YYYY-MM-DD` | GET | 当日草案和历史快照 |
| `/api/adjustments` | POST | `{date,expected_version,mode,request}`，返回草案，`plan_changed:false` |
| `/api/adjustments/{id}/confirm` | POST | `{}`，事务内检查版本并更新 |
| `/api/adjustments/{id}/discard` | POST | `{}`，保留正式计划 |
| `/api/strategy/draft` | POST | `{date,expected_version,focus}` 或 `request`，策略模板草案 |
| `/api/snacks` | GET | 小食目录，未知营养为null |
| `/api/snacks/add` | POST | `{date,expected_version,snack_id}` |
| `/api/snacks/remove` | POST | `{date,expected_version,entry_id}` |
| `/api/activities/add` | POST | `{date,expected_version,kind:"walk"或"swim",minutes}` |
| `/api/activities/remove` | POST | `{date,expected_version,entry_id}` |
| `/api/activities/rest` | POST | `{date,expected_version}`，明确休息并清空当日运动 |
| `/api/foods?q=米饭&category=主食` | GET | 基础食品、份量基准、参考营养与来源 |
| `/api/feedback` | POST | `{date,expected_version,score:1至5,comment:"可选"}` |
| `/api/export` | GET | 全部画像、计划、调整、事件；包含个人信息 |
| `/api/data/delete` | POST | `{confirmation:"删除我的本地数据"}`，保留食品库 |

`meal` 为 `breakfast / lunch / snack / dinner`。`focus` 为 `饮食优先 / 运动优先 / 作息优先 / 平衡维持 / 自动匹配`。

所有日期使用浏览器本地日期传入，不由 UTC 自动替换。UI内默认今天，可切换查询已有日期。

## 画像示例

```json
{
  "expected_version":0,
  "profile":{
    "nickname":"小满","age":28,"sex":"female",
    "height_cm":165,"current_weight_kg":60,"target_weight_kg":57,
    "target_weeks":12,"goal":"规律饮食",
    "work_intensity":"normal","meal_sources":["canteen","delivery"],
    "exercise_frequency":"rare","available_time":"10–20 分钟",
    "sleep":"偶尔晚睡","preferences":"清淡家常菜",
    "exclusions":[],"exclusions_note":"","main_difficulty":"吃饭不规律",
    "health_status":"general","ai_consent":false
  }
}
```

枚举：生理性别 `female/male`；工作 `normal/busy`；饮食 `canteen/delivery/home`；运动 `rare/some/often`；健康 `general/pregnant/condition/eating_concern`。其他可选字段的枚举见 `core.profile_value`。

## 计划语义

`meals[meal].selected` 是已采用方案，`candidates` 是当前待选批次。刷新候选不改变 selected。`completed` 只表示用户标记完成，不代表称重后的实际摄入。

`totals` 和 `checks` 描述基础四餐。`snacks` 是额外主动选择；UI加总已知营养、标注未知部分。不能把四餐的检查结论当作额外小食也通过了规则。`activities` 的估算单独显示。

普通修改需要当前 `expected_version`。版本不符返回409。画像改变也会要求重新生成。生成前有完成餐次时，必须经用户确认后传 `reset_completed:true`；UI重新生成还会确认重置小食和运动。

草案状态：`pending / confirmed / discarded / superseded`。确认使用 `BEGIN IMMEDIATE`，匹配正式计划版本和画像版本，确认成功后使同一计划其他旧草案过期。客户端不能直接提交任意候选JSON，只能选择服务端保存的候选ID。

## DeepSeek

运动调整支持结构化 `activity_action`：`{"type":"keep","entry_ids":[]}` 保留安排，或 `{"type":"remove","entry_ids":["当前运动记录ID"]}` 取消指定项目。模型上下文含当天运动的 `entry_id/kind/name/minutes`。未知、重复或不一致的ID拒绝保存。`rest=true` 仅表示休息建议，不自动删除项目。调整任务允许 `choices:{}`，仅修改运动；首次生成仍需完整四餐。

草案同时保存调整前后的运动列表，前端展示具体取消项目。只有确认后更新数据库；放弃、失败或版本冲突时保留正式计划。旧草案不会自动补齐新的运动操作，应放弃旧草案并重新生成。

Key 从进程环境或项目 `.env` 读取，前端不接收。仅授权后发送最小必要上下文，固定 HTTPS 目的地。模拟测试覆盖成功、无效JSON、未知候选、鉴权、配额、超时和风险拒绝，不代表真实账号调用已验证。


## 餐食库 V2（2026-10-11）

`GET /api/recipes` 返回带食材克重、生熟依据、餐食类型、点餐提示及来源的示例配方，以及当前目录版本。`GET /api/status` 的 catalog 包含食品、品牌规格、配方、正餐模板与品牌主食数量。

`POST /api/meals/refresh` 可选 `family` 字符串，例如 `米粉米线`；只在该类型内选未看过且符合画像约束的候选。空字符串不限类型，优先提供不同类型的候选。没有可用候选返回422，计划保持不变。换批仍不采纳方案，须通过 `/api/meals/select` 确认。

品牌部件使用 `product_id/quantity/unit/portion`，例如1个汉堡；没有公布克重就不提供grams。食材部件仍使用food_id和grams。品牌配餐的nutrition由品牌标准份与自备配餐相加，不能对汉堡做任意比例缩放。


## 0.2.0：搜索、外卖和可选下午茶

`POST /api/meals/search`：只读检索，用 POST 传递计划版本；与其他同源接口相同的来源和请求体检查。字段：date、expected_version、meal、scene（profile/delivery，默认 profile）、query（最多60字，空白分词并且匹配）、family（可空）、offset（默认0）、limit（1–12，默认6）、exclude_ids（最多200个）。delivery 限午餐/晚餐。返回 options、total、offset、has_more、scene、plan_version。检索范围为当前画像过滤后的候选；delivery 仅在本次检索中覆盖饮食来源，忌口和其他限制保留。未找到返回空数组，不更新计划/事件/草案。

`POST /api/meals/select`：增加 selection_source=batch/catalog（默认 batch）及 scene=profile/delivery。batch 仍限当前候选批次；catalog 在服务端重新构建该画像、场景的允许池，按 option_id 查找，不能提交自定义营养数据或绕过忌口。沿用完成状态、计划版本、画像版本检查。采纳后才递增版本并使旧草案失效。

`POST /api/meals/optional`：date、expected_version、meal（只能 snack）、enabled（布尔）。取消/恢复下午茶，保留选中方案用于恢复；已完成餐次禁止取消。disabled 下午茶禁止 select/refresh/complete。使用同样的保存事务、版本和草案失效机制。

计划 meals.snack.enabled 默认 true（旧记录缺省也按 true）；totals 不含 enabled=false 的下午茶。checks 按启用餐次计算，可能有 passed=false。check_basis 说明统计范围，optional_snack_note 说明未安排和未达项。额外 snacks 和 activities 统计方式不变，不以运动抵扣饮食。

每日生成仍校验完整参考搭配；用户取消下午茶时，保留该参考搭配用于生成/换餐护栏，展示的总量及检查采用实际启用餐次。此设计允许自愿取消，不把取消造成的未达项误报为通过，不声称取消后的三餐已满足营养需求。没有新增营养阈值。


## 0.3.0：小自在本地陪伴反馈

- `GET /api/coach?date=YYYY-MM-DD`：返回 coach（无画像返回 null），含 name、role、source、profile_version、collapsed、kind、message、cta、progress、stats、window、view_date、record_note。只读，本地计算，无模型请求。
- `POST /api/coach/preferences`：date、expected_profile_version、collapsed（严格布尔）。按当前画像保守归属保存收起偏好，验证画像版本，不修改计划或使草案过期。返回该日期的 coach。
- 新增 SQLite coach_preferences 表（scope、collapsed、updated_at），user_version=3；保留原表数据。导出包含 coach_preferences，删除个人数据会清除该表中的偏好。
- 最近7天截至 min(查看日期,本机今天)。从每天最新正式计划计算一次，未完成不算完成、取消的下午茶不计完成，未来安排不计历史。画像快照完整匹配（ai_consent 除外）；这是本地单用户原型的保守隔离，并非多用户账号系统。
- 首页反馈的聚合历史不发送给 DeepSeek；现有动态调整发送字段不扩展，统一人设仅修改系统规则。生成/调整失败与确认机制沿用原实现。
