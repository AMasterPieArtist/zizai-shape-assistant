/* Additional screens from the supplied prototype: strategies, snacks and activity.
 * The original page classes and visual hierarchy are retained.
 */
'use strict';
function strategyData(focus=state.plan?.strategy_focus||'自动匹配'){
  const p=profile();
  if(focus==='自动匹配')focus=p.sleep==='经常晚睡'||p.work_intensity==='busy'?'作息优先':p.main_difficulty.includes('吃饭')?'饮食优先':p.exercise_frequency==='rare'?'运动优先':'平衡维持';
  const templates={
    '饮食优先':['先把三餐安排稳定',`优先准备${sourceText(p)}中方便找到的两三种搭配，饮品小食也提前留位置。`,'运动从容易坚持的短时活动开始。','给用餐留一个相对固定的时间。'],
    '运动优先':['先建立一个活动习惯','保留正常三餐，按喜欢的口味选择食物。',`从${p.available_time}的可用时间出发，先安排一次熟悉的活动。`,'把活动放到不挤占睡眠的时段。'],
    '作息优先':['先让生活节奏缓下来','忙碌时优先保证有饭可吃，准备方便的备选餐。','疲劳日可以休息，有余力再安排短时散步。','从减少一次不必要的熬夜开始，逐步稳定休息时间。'],
    '平衡维持':['保留已经适合你的习惯','维持喜欢且方便的三餐搭配，允许灵活替换。','按已有习惯安排活动，忙碌日降低安排负担。','延续稳定作息，给临时变化留余地。']};
  return {focus,items:templates[focus]};
}
function snackList(){return (state.plan?.snacks||[]).map(x=>`<div class="meal"><div class="content"><h3>${esc(x.name)}</h3><p>${esc(x.unit)} · ${x.nutrition?'约 '+numberText(x.nutrition.kcal)+' 千卡（'+esc(x.source)+'）':'营养数据待补充'}</p><p>${esc(x.note)}</p></div>${action('移除','remove-snack','secondary',`data-id="${esc(x.entry_id)}"`)}</div>`).join('')||'<p class="muted">一杯咖啡、一份甜点，也可以是计划的一部分。</p>';}
function activityList(){return (state.plan?.activities||[]).map(x=>`<div class="meal"><div class="content"><h3>${esc(x.name)} · ${x.minutes} 分钟</h3><p>${x.kcal===null?'该年龄不做运动消耗估算':'预计活动期间总消耗约 '+numberText(x.kcal)+' 千卡'} · 添加时体重 ${x.weight_kg} kg</p></div>${action('移除','remove-activity','secondary',`data-id="${esc(x.entry_id)}"`)}</div>`).join('')||'<p class="muted">还没有运动安排。今天也可以选择休息。</p>';}
function strategyPage(){
  if(!state.profile)return needProfile();
  const p=profile(),data=strategyData();
  return `<div class="adjust">${heading('适合你的，比标准答案更重要','饮食、运动、作息，各有不同的优先级。')}<div class="formcard"><span class="pill">当前重点 · ${data.focus}</span><h2 style="margin-top:20px">${data.items[0]}</h2><p class="muted">依据：${p.work_intensity==='busy'?'经常加班':'正常工作节奏'} · ${esc(p.sleep)} · ${esc(p.main_difficulty)}</p>${['饮食','运动','作息'].map((x,i)=>`<div class="strategy"><b>0${i+1}</b><div><h3>${x}</h3><p>${esc(data.items[i+1])}</p></div></div>`).join('')}${state.plan?`<p class="note">${esc(state.plan.strategy)}</p>`:''}<p class="note">策略重点为可解释的本地规则；AI 生成的个性化说明会明确标注来源。</p><div class="actions">${button('修改画像','basic','secondary')}${state.plan?button('查看今日计划','home'):action('生成今日计划','generate')}</div></div><div class="formcard" style="margin-top:20px"><span class="pill">沟通后调整 · 策略重点模板</span><h2 style="margin-top:18px">这份策略，哪里想改一改？</h2>${state.plan?`<form id="strategyform"><label>你的想法<textarea name="message" maxlength="300" placeholder="例如：最近加班很累，想先把作息调好" required></textarea></label><button class="button secondary">讨论调整</button></form><p class="note">这里使用本地策略模板；自由对话和餐次调整可前往「动态调整」并选择 DeepSeek。</p><div class="chiprow">${['饮食优先','运动优先','作息优先','平衡维持','自动匹配'].map(x=>`<button class="chip" data-action="strategy-focus" data-focus="${x}">${x}</button>`).join('')}</div>${state.draft?.changes.includes('个人策略')?draftView(state.draft):''}`:'<p class="muted">先生成当天计划，之后可以创建并确认策略调整草案。</p>'}</div></div>`;
}
function snacksPage(){
  if(!state.profile)return needProfile();if(!state.plan)return needPlan();
  const exclusions=profile().exclusions;
  const query=(state.snackQuery||'').toLowerCase(),group=state.snackGroup||'';
  const options=state.snackCatalog.filter(f=>(!group||f.group===group)&&(!query||(f.name+' '+f.group+' '+f.unit).toLowerCase().includes(query)));
  const filters=`<form id="snacksearch" class="searchbar"><label>搜索饮品或小食<input name="q" maxlength="60" placeholder="例如：拿铁、奶茶、蛋糕" value="${esc(state.snackQuery||'')}"></label><label>分类<select name="group"><option value="">全部分类</option>${[...new Set(state.snackCatalog.map(f=>f.group))].map(g=>`<option ${g===group?'selected':''}>${esc(g)}</option>`).join('')}</select></label><button class="button">查询</button></form><p class="note">可选 ${options.length} 项 · 参考库 ${esc(state.status?.catalog?.version||'')}。品牌标准份量、通用食物与自配饮品分别标注来源。</p>`;
  return heading('给今天，留一点喜欢','按固定规格选择；真实品牌与配方不同，数值会有变化。',button('返回今日','home','secondary'))+energyPanel()+filters+`<div class="listcards">${options.map(f=>{
    const blocked=f.tags.some(x=>exclusions.includes(x))||(exclusions.length&&(!f.ingredients.length||f.allergen_check_required));
    return `<article class="option"><span class="pill">${esc(f.group)}</span><h2>${esc(f.name)}</h2><p>${esc(f.unit)}</p><h3>${f.nutrition?'约 '+numberText(f.nutrition.kcal)+' 千卡':'营养数据待补充'}</h3><p>${f.tags.length?'配料标签：'+esc(f.tags.join('、')):'配料需向商家核对'}</p><p class="note">${esc(f.note)}</p>${f.source_url?`<p class="note"><a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source)}</a> · ${esc(f.updated_at)}</p>`:''}${action(blocked?'忌口冲突 / 配料待核对':'加入今日计划','add-snack','',`data-id="${esc(f.id)}" ${blocked?'disabled':''}`)}</article>`;
  }).join('')}</div><p class="note">这里记录你主动选择的额外小食，会单独加在四餐之外；不会自动扣减正餐。总量可能超过基础四餐参考范围。品牌奶茶、蛋糕数据不足时不编造数字；需要讨论变化时可去动态调整。</p><div class="section-head"><h2>已经选好的小满足</h2></div>${snackList()}`;
}
function activityPage(){
  if(!state.profile)return needProfile();if(!state.plan)return needPlan();
  return heading('运动安排，也听听身体的意见','自己安排，或先聊聊今天适合怎样活动。',button('返回今日','home','secondary'))+`<div class="compare"><section class="formcard"><h2>我有自己的安排</h2><form id="activityform"><label>运动类型<select name="kind"><option value="swim">休闲游泳</option><option value="walk">中速步行</option></select></label><label>计划时长（分钟）<input name="minutes" type="number" min="5" max="180" step="5" value="30" required></label><p id="estimate" class="success"></p><button class="button">添加运动</button></form><p class="note">MET × 体重(kg) × 时长(h)，估算活动期间总能耗（包含静息消耗），并非净消耗。MET 仍为原型示例值。当前参考年龄 19–59 岁，不从饮食安排中扣减。</p><a class="textbtn" href="https://pacompendium.com/" target="_blank" rel="noopener">来源：2024 身体活动汇编</a></section><section class="formcard"><span class="pill">沟通调整 · 本地规则</span><h2 style="margin-top:18px">今天的你，状态怎么样？</h2><form id="suggestform"><label>工作忙闲<select name="busy"><option>正常</option><option>很忙</option><option>比较空闲</option></select></label><label>身体感受<select name="feeling"><option>精力尚可</option><option>很疲惫</option><option>不舒服，想休息</option></select></label><button class="button secondary">看看适合的安排</button></form>${state.activitySuggestion?`<div class="success" style="margin-top:18px">${state.activitySuggestion.minutes?'建议中速步行 '+state.activitySuggestion.minutes+' 分钟':'今天先休息，不新增运动'}<p>${esc(state.activitySuggestion.reason)}</p>${action('确认安排','accept-activity')}</div>`:''}<p class="note">不依据饮食热量安排补偿运动。持续或严重不适时，暂停活动并及时就医。</p></section></div><div class="section-head"><h2>已安排</h2></div><p class="muted">${esc(state.plan.movement)}</p>${activityList()}`;
}
function foodsPage(){
  const foods=state.foods.filter(f=>!state.foodQuery||f.name.includes(state.foodQuery)||f.category.includes(state.foodQuery));
  return heading('让每一个估算，都有来处','小型结构化食品库 · 食材参考值不等于餐厅配方',button('返回今日','home','secondary'))+`<form id="foodsearch" class="searchbar"><label>搜索食品或分类<input name="q" maxlength="60" placeholder="例如：米饭、蔬菜、蛋白质" value="${esc(state.foodQuery)}"></label><button class="button">查询</button></form><div class="warning">基础食品 ${state.foods.length} 条 · ${esc(state.status?.catalog?.version||'')}。营养来自 USDA SR Legacy 数据包抽取，仍待专业复核。每100克可食部，注意下方生/熟状态；不代表门店成品。品牌资料请到「饮品与小食」按规格选择。</div><div class="table-wrap"><table><thead><tr><th>食品 / 分类</th><th>参考能量</th><th>蛋白质 / 碳水 / 脂肪</th><th>忌口标签</th><th>来源与更新</th></tr></thead><tbody>${foods.map(f=>`<tr><td><strong>${esc(f.name)}</strong><br>${esc(f.category)} · ${esc(f.food_state||'')}</td><td>${f.kcal} kcal</td><td>${f.protein} / ${f.carbs} / ${f.fat} g</td><td>${esc(f.tags.join('、')||'无已知标签；需核对配料')}</td><td><a href="${esc(f.source_url)}" target="_blank" rel="noopener">${esc(f.source)}</a><br>${esc(f.updated_at)}</td></tr>`).join('')||'<tr><td colspan="5">没有匹配的食品，当前不会用模型猜测缺失营养。</td></tr>'}</tbody></table></div>`;
}
function historyPage(){
  const status={pending:'待确认',confirmed:'已确认',discarded:'已保留原计划',superseded:'已过期（计划已变化）'};
  return heading('每一次调整，都有记录','草案保留原计划快照；确认后才更新正式安排。',button('返回今日','home','secondary'))+dayControls()+
    (state.adjustments.length?state.adjustments.map(d=>`<details class="formcard history-item" ${d.status==='pending'?'open':''}><summary><span class="pill">${status[d.status]}</span> ${esc(d.request)}<small>${new Date(d.created_at).toLocaleString('zh-CN')}</small></summary>${draftView(d)}</details>`).join(''):'<div class="formcard"><h3>还没有调整记录</h3><p class="muted">从一次聚餐、一杯奶茶或忙碌的一天开始，都可以先看看草案。</p>'+button('去动态调整','adjust')+'</div>');
}
function privacyPage(){
  return `<div class="adjust">${heading('你的数据，由你决定','本地单用户使用；不需要注册账号。')}<div class="formcard"><h2>画像与计划保存在哪里？</h2><p>保存在项目的 <code>data/zizai.sqlite3</code>。首次启动自动创建，刷新网页或重启程序都会保留。浏览器不保存 API Key。</p><p>小自在首页卡片根据本地保存的安排与完成标记整理，不会额外调用模型。最近7天的回顾按当前画像匹配，不推断实际摄入或减重效果；收起偏好也保存在本机。</p><p>这是明文的本地数据库，请使用你信任的电脑。导出文件也包含个人资料，分享前请检查。</p><div class="actions">${action('导出我的数据（JSON）','export','secondary')}${action('删除本地个人数据','delete-data','danger')}</div><p class="note">删除会清除画像、计划、草案和反馈，保留食品参考库。此前导出的副本不会被同步删除；本功能不保证磁盘级不可恢复。</p></div><div class="formcard" style="margin-top:20px"><h2>DeepSeek 数据授权</h2><span class="pill">${state.profile?.data.ai_consent?'已授权（仅在 AI 模式发送）':'未授权，默认不发送'}</span><p>AI 请求会发送：工作与作息、饮食来源、运动频率与可用时间、偏好和忌口、主要困难、计算后的能量参考、食品候选、已选与已完成餐次、小食和运动安排，以及你的调整文本。</p><p>不会主动发送昵称、年龄、性别、身高体重、目标体重或健康状态字段。自由文本中自行填写的信息仍会发送。</p><p>API Key 仅由 Python 后端读取本地 <code>.env</code>。DeepSeek 调用可能收费，按你的账号计费。</p>${button('修改画像与授权','preferences','secondary')} ${state.profile?.data.ai_consent?action('立即撤回授权','revoke-consent','light'):''}<p class="note">撤回后不会再发起新的 AI 请求；已经发送到外部服务的内容无法通过删除本地数据库撤回。</p></div><div class="formcard" style="margin-top:20px"><h2>当前版本的边界</h2><p>这是生活方式原型，营养数据、活动系数与规则阈值均待专业复核。适用于一般健康成年人的产品演示，不提供医疗、治疗或快速减重建议。没有账号隔离，不应直接开放到公网。</p><p>当前连接：${state.status?.deepseek_configured?'后端检测到 DeepSeek Key（未验证账号可用性）':'后端未配置 DeepSeek Key，可使用本地演示'}。</p></div></div>`;
}
function extraPage(route){return ({strategy:strategyPage,snacks:snacksPage,activity:activityPage,foods:foodsPage,history:historyPage,privacy:privacyPage}[route]||homePage)();}

function bindExtraForms(){
  const f=$('#activityform');
  if(f){const estimate=()=>{const minutes=Number(f.elements.minutes.value),met=f.elements.kind.value==='swim'?6:3.8,p=profile();$('#estimate').textContent=minutes>=5&&minutes<=180?(p.age>=19&&p.age<=59?`按添加时体重参考估算：约 ${Math.round(met*p.current_weight_kg*minutes/60)} 千卡`:'当前年龄不做运动消耗估算'):'请输入 5–180 分钟';};f.addEventListener('input',estimate);estimate();f.addEventListener('submit',event=>{event.preventDefault();const body={...requestBase(),kind:f.elements.kind.value,minutes:Number(f.elements.minutes.value)};run(async()=>setPlan(await api('/api/activities/add',body),'运动安排已保存'));});}
  const suggest=$('#suggestform');if(suggest)suggest.addEventListener('submit',event=>{event.preventDefault();const busy=suggest.elements.busy.value,feeling=suggest.elements.feeling.value,p=profile();const minutes=feeling!=='精力尚可'?0:busy==='很忙'||p.available_time==='不足 10 分钟'?5:busy==='比较空闲'&&p.available_time==='20 分钟以上'?20:10;state.activitySuggestion={minutes,reason:minutes?'按今天的精力与可用时间，先安排容易执行的活动。':'把恢复放在前面。确认休息会移除今天已安排的运动；饮食计划保留。'};render();});
  const strategy=$('#strategyform');if(strategy)strategy.addEventListener('submit',event=>{event.preventDefault();const request=strategy.elements.message.value;run(async()=>{const data=await api('/api/strategy/draft',{...requestBase(),request});state.draft=data.adjustment;await refreshState();render();});});
  const snackSearch=$('#snacksearch');if(snackSearch)snackSearch.addEventListener('submit',event=>{event.preventDefault();state.snackQuery=snackSearch.elements.q.value.trim();state.snackGroup=snackSearch.elements.group.value;render();});
  const search=$('#foodsearch');if(search)search.addEventListener('submit',event=>{event.preventDefault();state.foodQuery=search.elements.q.value.trim();render();});
}
async function extraAction(name,b){
  if(name==='add-snack')await setPlan(await api('/api/snacks/add',{...requestBase(),snack_id:b.dataset.id}),'小食已加入并保存');
  else if(name==='remove-snack')await setPlan(await api('/api/snacks/remove',{...requestBase(),entry_id:b.dataset.id}),'已移除小食');
  else if(name==='remove-activity')await setPlan(await api('/api/activities/remove',{...requestBase(),entry_id:b.dataset.id}),'已移除运动');
  else if(name==='accept-activity'){
    if(!state.activitySuggestion)return;
    if(!state.activitySuggestion.minutes&&state.plan.activities.length&&!confirm('确认今天休息，并移除已安排的运动吗？'))return;
    const result=await api(state.activitySuggestion.minutes?'/api/activities/add':'/api/activities/rest',{...requestBase(),kind:'walk',minutes:state.activitySuggestion.minutes});state.activitySuggestion=null;await setPlan(result,'今天的安排已保存');
  }
  else if(name==='strategy-focus'){const data=await api('/api/strategy/draft',{...requestBase(),focus:b.dataset.focus});state.draft=data.adjustment;await refreshState();render();toast('策略草案已保存，确认后才会生效');}
  else if(name==='export'){
    const data=await api('/api/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='自在身材-我的数据-'+localDate()+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('已导出 JSON，请妥善保存个人资料');
  }
  else if(name==='revoke-consent'){
    const p=structuredClone(state.profile.data);p.ai_consent=false;const data=await api('/api/profile',{profile:p,expected_version:state.profile.version},'PUT');state.profile=data.profile;state.form=structuredClone(p);render();toast('已撤回授权，不会再发送新的 AI 请求');
  }
  else if(name==='delete-data'){
    const confirmation=prompt('这将删除本地画像、计划、草案和反馈。此操作不可在应用中撤销。请输入：删除我的本地数据');
    if(confirmation===null)return;
    if(confirmation!=='删除我的本地数据')throw new Error('确认文字不一致，未删除任何数据。');
    await api('/api/data/delete',{confirmation});state.form=structuredClone(defaults);state.draft=null;state.request='';await refreshState();location.hash='welcome';render();toast('本地个人数据已删除，食品库已保留');
  }
}
