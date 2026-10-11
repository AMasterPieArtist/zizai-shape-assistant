/* Existing Zizai prototype layout, connected to same-origin Python + SQLite APIs.
 * No API key or sensitive persistent profile is stored in browser storage.
 */
'use strict';
const pages = [['welcome','欢迎来到自在'],['basic','基本情况'],['life','生活节奏'],['preferences','偏好与限制'],['strategy','个人策略'],['home','今日计划'],['lunch','午餐推荐'],['adjust','动态调整'],['snacks','饮品与小食'],['activity','运动安排'],['foods','食品数据'],['history','调整记录'],['privacy','我的数据']];
const labels = {breakfast:'早餐', lunch:'午餐', snack:'下午茶', dinner:'晚餐'};
const times = {breakfast:'08:00', lunch:'12:30', snack:'15:30', dinner:'18:30'};
const exclusionChoices = ['乳制品','鸡蛋','小麦','大豆','花生','坚果','鱼','虾蟹','牛肉','猪肉','肉类','辣'];
const defaults = {nickname:'小满', age:28, sex:'female', height_cm:165, current_weight_kg:60, target_weight_kg:57, target_weeks:12, goal:'规律饮食', work_intensity:'normal', meal_sources:['canteen'], exercise_frequency:'rare', available_time:'10–20 分钟', sleep:'偶尔晚睡', preferences:'清淡家常菜', exclusions:[], exclusions_note:'', main_difficulty:'吃饭不规律', health_status:'', ai_consent:false};
const localDate = () => {const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
const state = {profile:null, coach:null, form:structuredClone(defaults), plan:null, status:null, day:localDate(), mode:'demo', meal:'lunch', adjustments:[], draft:null, foods:[], snackCatalog:[], busy:false, initialized:false, request:'', foodQuery:'', recipeCatalog:[], mealFamily:'', mealQuery:'', mealBrowser:null, error:'', activitySuggestion:null};
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const photo = 'food.jpg';
const button = (label,route,cls='') => `<a class="button ${cls}" href="#${route}">${label}</a>`;
const action = (label,name,cls='',attrs='') => `<button type="button" class="button ${cls}" data-action="${name}" ${attrs}>${label}</button>`;
const heading = (title,sub,extra='') => `<div class="heading"><div><div class="eyebrow">A LITTLE CARE, EVERY DAY</div><h1>${title}</h1><p>${sub}</p></div>${extra}</div>`;
const profile = () => state.profile?.data || state.form;
const sourceText = p => (p.meal_sources||[]).map(x=>({canteen:'食堂',delivery:'外卖',home:'自己做饭'}[x])).join(' / ');
const requestBase = () => ({date:state.day, expected_version:state.plan?.version||0});
const sourceBadge = source => source === 'deepseek' ? 'DeepSeek · 结构与候选已校验' : '本地模板 · 非 AI 生成';
const numberText = n => Number.isFinite(n) ? Math.round(n).toLocaleString('zh-CN') : '待补充';

async function api(path, body, method) {
  const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(), 95000);
  try {
    const response=await fetch(path,{method:method||(body?'POST':'GET'),headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:controller.signal});
    const data=await response.json();
    if(!response.ok){const e=new Error(data.error?.message||'请求失败，请重试。'); e.code=data.error?.code; e.status=response.status; throw e;}
    return data;
  } catch(e) {
    if(e.name==='AbortError') throw new Error('等待服务超时。请刷新查看是否已完成，避免重复提交。');
    if(e instanceof TypeError) throw new Error('无法连接本地后端，请确认 VS Code 终端中的 python app.py 仍在运行。');
    throw e;
  } finally {clearTimeout(timer);}
}
function toast(message){$('#toast').textContent=message; $('#toast').style.display='block'; clearTimeout(window.toastTimer); window.toastTimer=setTimeout(()=>$('#toast').style.display='none',4000);}
function busy(value){state.busy=value; $('#working').hidden=!value; $('#app').setAttribute('aria-busy',String(value)); document.querySelectorAll('button,input,select,textarea').forEach(el=>{if(value){el.dataset.wasDisabled=String(el.disabled);el.disabled=true;}else{el.disabled=el.dataset.wasDisabled==='true';delete el.dataset.wasDisabled;}});}
function showError(message){state.error=message; const box=$('#global-alert');if(box){box.textContent=message;box.hidden=false;box.scrollIntoView({block:'nearest'});}toast(message);}
async function run(task){if(state.busy)return; state.error='';if($('#global-alert'))$('#global-alert').hidden=true; busy(true);try{await task();}catch(e){showError(e.message);if(e.status===409){await refreshState().catch(()=>{});}}finally{busy(false);}}
async function refreshState(initial=false){
  const day=state.day;
  const [pr,pl,ad,co]=await Promise.all([api('/api/profile'),api('/api/plans?date='+day),api('/api/adjustments?date='+day),api('/api/coach?date='+day)]);
  if(day!==state.day)return;
  state.profile=pr.profile; state.plan=pl.plan; state.adjustments=ad.adjustments; state.coach=co.coach?.profile_version===pr.profile?.version?co.coach:null;
  if(state.mealBrowser&&!state.mealBrowser.key.startsWith(`${state.day}:${pr.profile?.version}:`)){state.mealBrowser=null;state.mealQuery='';}
  if(initial&&pr.profile)state.form=structuredClone(pr.profile.data);
  if(state.draft)state.draft=state.adjustments.find(x=>x.id===state.draft.id&&x.status==='pending')||null;
}
async function setPlan(data,message){state.plan=data.plan;await refreshState();render();if(message)toast(message);}
function needProfile(){return `<div class="formwrap">${heading('先认识一下你','完成三步画像后，就可以生成并保存自己的计划。')}<div class="formcard"><p>第一次使用时，页面不会把示例信息自动当作你的真实画像。</p>${button('开始填写画像','basic')}<p class="note">已保存的数据留在本机；未开启授权时不会发送给 DeepSeek。</p></div></div>`;}
function needPlan(){return `<div class="formwrap">${heading('给这一天，一点小小的安排',`${esc(state.day)} 还没有保存的计划。`)}<div class="formcard"><span class="pill">${state.mode==='demo'?'本地模板演示':'DeepSeek AI'}</span><p class="section-head">先生成四餐与运动建议，再选择、调整和保存。</p>${action('生成这一天的计划','generate')}<p class="note">首次启动自动建表。演示模式不联网；AI 模式需要本地 Key 和明确的数据授权。</p>${button('修改画像','basic','light')}</div></div>`;}
function input(label,key,type='text',attrs=''){return `<label>${label}<input name="${key}" type="${type}" value="${esc(state.form[key])}" ${attrs}></label>`;}
function select(label,key,options){return `<label>${label}<select name="${key}" aria-label="${esc(label)}" required>${options.map(item=>{const [value,title]=Array.isArray(item)?item:[item,item];return `<option value="${esc(value)}" ${state.form[key]===value?'selected':''}>${esc(title)}</option>`;}).join('')}</select></label>`;}
function form(step,title,sub,body,next){return `<div class="formwrap">${heading(title,sub)}<div class="progress" aria-label="第 ${step} 步，共 3 步">${[1,2,3].map(x=>`<span class="${x<=step?'on':''}"></span>`).join('')}</div><form id="profileform" class="formcard" data-step="${step}" data-next="${next}"><span class="pill">认识你 · ${step} / 3</span><div style="margin-top:25px">${body}</div><p class="note">第三步点击保存后，画像写入本机 SQLite；刷新或重启不会丢失。当前为本地单用户版本。</p><div class="actions">${button('上一步',['welcome','basic','life'][step-1],'secondary')}<button class="button" type="submit">${step===3?'保存画像，查看策略':'下一步'}</button></div></form></div>`;}
function welcomePage(){return `<div class="welcome"><div><div class="eyebrow">ZIZAI · 自在的每一天</div><span class="pill">为忙碌的生活，留一点照顾</span><h1 style="margin-top:22px">好好吃，<br>慢慢来。</h1><p>不必让每一餐都变成一道难题。<br>小自在陪你从日常出发，找到方便、喜欢的饮食安排，<br>也为加班、聚餐和休息留一点弹性。</p>${button(state.profile?'修改我的画像':'开始定制','basic')} ${button('看看今日计划','home','secondary')}<p class="note">约 2 分钟，认识你的生活节奏</p></div><div class="visual"><img src="${photo}" alt="自然光下的新鲜蔬菜餐碗"><p class="note">一餐一饭，都是照顾自己的小事。</p></div></div>`;}
function profilePage(route){
  if(route==='basic')return form(1,'先认识一下你','没有标准答案，按你现在的状态填写就好。',input('怎么称呼你','nickname','text','required maxlength="30"')+`<div class="fields">${input('年龄（岁）','age','number','required min="10" max="100"')}${select('生理性别（用于参考公式）','sex',[['female','女'],['male','男']])}${input('身高（cm）','height_cm','number','required min="120" max="220" step="0.1"')}${input('当前体重（kg）','current_weight_kg','number','required min="30" max="250" step="0.1"')}${input('目标体重（kg）','target_weight_kg','number','required min="30" max="250" step="0.1"')}${input('目标周期（周）','target_weeks','number','required min="1" max="104"')}</div>`+select('这次想先做到什么','goal',['规律饮食','保持状态','温和管理体重'])+select('健康情况（请选择）','health_status',[['','请选择你的情况'],['general','一般健康成年人，无以下特殊情况'],['pregnant','孕期或哺乳期'],['condition','有需医生管理的疾病或特殊营养需求'],['eating_concern','有进食障碍或相关困扰']])+`<p class="note">特殊人群可以保存画像，但本原型不自动规划。公式仅估算维持能量，不根据目标体重生成减重处方。</p>`,'life');
  if(route==='life')return form(2,'让计划适应你的生活','从你最常遇到的一天开始。',select('工作节奏','work_intensity',[['normal','作息规律 / 偶尔加班'],['busy','经常加班']])+`<fieldset><legend>平时主要在哪里吃（可多选）</legend><div class="checkrow">${[['canteen','食堂'],['delivery','外卖'],['home','自己做饭']].map(([value,label])=>`<label><input type="checkbox" name="meal_sources" value="${value}" ${state.form.meal_sources.includes(value)?'checked':''}>${label}</label>`).join('')}</div></fieldset>`+select('每天方便活动的时间','available_time',['不足 10 分钟','10–20 分钟','20 分钟以上'])+select('近期作息','sleep',['偶尔晚睡','经常晚睡','作息稳定'])+select('当前运动习惯','exercise_frequency',[['rare','很少运动'],['some','每周 1–2 次'],['often','每周 3 次及以上']])+input('目前最想改善','main_difficulty','text','maxlength="200"'),'preferences');
  return form(3,'你的喜欢，都值得被记住','不勉强自己吃不喜欢的食物。',input('喜欢的口味或食物','preferences','text','maxlength="200"')+`<fieldset><legend>忌口或过敏食物（硬约束）</legend><div class="checkrow">${exclusionChoices.map(x=>`<label><input type="checkbox" name="exclusions" value="${x}" ${state.form.exclusions.includes(x)?'checked':''}>${x}</label>`).join('')}</div></fieldset>`+input('其他忌口（选填）','exclusions_note','text','maxlength="100" placeholder="无法覆盖的限制请填在这里"')+`<p class="note">无法识别的其他忌口会暂停自动规划；不会为了生成结果忽略限制。外食的实际配料与交叉接触仍需向商家确认。</p><details class="privacy-details"><summary>DeepSeek 会收到哪些信息？</summary><p>仅在选择 AI 模式并授权后，发送：工作节奏、饮食来源、运动频率与可用时间、作息、偏好、忌口、主要困难、程序计算的能量参考、候选食物，以及当日餐次状态、小食、运动安排和你输入的调整文本。</p><p>不会主动发送昵称、年龄、性别、身高、体重、目标体重或健康状况字段。你自己在自由文本中填写的信息也会随文本发送。数据会由 DeepSeek 按其服务政策处理。</p></details><label class="consent"><input type="checkbox" name="ai_consent" ${state.form.ai_consent?'checked':''}>我已阅读以上说明，同意在使用 AI 模式时发送这些信息（可随时取消）</label>`,'strategy');
}
function energyPanel(){
  if(!state.plan)return '';
  const n=state.plan.totals, snacks=state.plan.snacks||[];
  const extra=snacks.reduce((sum,x)=>sum+(x.nutrition?.kcal||0),0), unknown=snacks.some(x=>!x.nutrition), total=n.kcal+extra;
  const done=Object.values(state.plan.meals).filter(x=>x.completed&&x.enabled!==false).reduce((sum,x)=>sum+x.selected.nutrition.kcal,0);
  return `<div class="banner"><div><span class="eyebrow">今日计划 · 能量概览</span><h2>${numberText(total)} <small>千卡${unknown?' + 待补充':''}</small></h2><p>${state.plan.meals.snack.enabled===false?'三餐（下午茶未安排）':'三餐及可选下午茶'} + 已选小食的参考估算；已标记完成的餐次约 ${numberText(done)} 千卡。</p><small>${state.plan.optional_snack_note?esc(state.plan.optional_snack_note)+' ':''}这是计划估算，不能视为实际摄入。${unknown?'存在配方未知的小食，无法计算完整总量。':''}运动消耗单独展示，不从饮食中扣除。</small></div></div>`;
}
function mealSummary(meal,featured=false){
  const m=state.plan.meals[meal],o=m.selected;
  if(meal==='snack'&&m.enabled===false)return `<article class="meal optional-meal"><div class="meal-time"><strong>下午茶</strong>可选</div><div class="content"><h3>今天不安排下午茶</h3><p>未计入计划热量；三餐、已添加的饮品小食和运动保持不变。</p></div><div class="meal-buttons">${action('恢复下午茶','toggle-snack','secondary','data-enabled="true"')}</div></article>`;
  const content=`<div class="meal-time"><strong>${labels[meal]}</strong>${times[meal]}${meal==='snack'?'<br>可选':''}</div><div class="content">${featured?`<span class="tag">${esc(o.scene)} · 配图仅作示意</span>`:''}<h3>${esc(o.title)}</h3><p>${o.ingredients.slice(0,4).map(x=>esc(x.name)+' '+esc(x.portion.split('（')[0])).join(' · ')}</p><p>约 ${numberText(o.nutrition.kcal)} 千卡 · ${m.completed?'已标记完成':'已纳入计划'}</p></div><div class="meal-buttons">${action('换个方案','meal-route','light',`data-meal="${meal}"`)}${action(m.completed?'取消完成':'标记完成','meal-complete','secondary',`data-meal="${meal}"`)}${meal==='snack'?action('取消下午茶','toggle-snack','light',`data-enabled="false" ${m.completed?'disabled':''}`):''}</div>`;
  return featured?`<article class="meal featured"><img src="${photo}" alt="蔬菜餐碗，餐食氛围示意图"><div class="meal-detail">${content}</div></article>`:`<article class="meal">${content}</article>`;
}
function dayControls(){return `<div class="day-controls"><label>计划日期<input id="day" type="date" value="${state.day}" required></label><span class="pill">${state.plan?esc(sourceBadge(state.plan.source)):'尚未生成'}</span>${state.plan?action('重新生成','generate','secondary'):''}</div>`;}
function coachCard(){
  const c=state.coach;if(!c)return '';
  const avatar='<span class="coach-avatar" aria-hidden="true"><i></i></span>';
  const head=`<div class="coach-identity">${avatar}<div><strong>小自在</strong><small>${c.collapsed?'陪伴卡片已收起':'温暖、务实的日常陪伴教练'}</small></div></div>${action(c.collapsed?'展开陪伴':'收起陪伴','toggle-coach','light',`aria-expanded="${!c.collapsed}"`)}`;
  if(c.collapsed)return `<section class="coach-card compact" aria-label="小自在陪伴"><div class="coach-head">${head}</div></section>`;
  const cta=c.cta.action?action(c.cta.label,c.cta.action):button(c.cta.label,c.cta.route);
  return `<section class="coach-card" aria-label="小自在陪伴"><div class="coach-head">${head}</div><p class="coach-message">${esc(c.message)}</p><div class="coach-progress"><span class="pill">属于你的日常回顾</span><p>${esc(c.progress)}</p><small>${esc(c.window.start)} — ${esc(c.window.end)} · 有安排 ${c.stats.planned_days} 天 · 有餐次完成标记 ${c.stats.completed_days} 天</small></div><div class="coach-foot">${cta}<details><summary>这句话依据什么？</summary><p>${esc(c.source_label)}。${esc(c.record_note)}</p></details></div></section>`;
}
function homePage(){
  const p=profile();
  if(!state.profile)return needProfile();
  if(!state.plan)return dayControls()+coachCard()+needPlan();
  const stale=state.plan.profile_version!==state.profile.version;
  const data=strategyData();
  return heading(`${esc(p.nickname)}，今天也好好吃饭`,'把选择变简单，把生活过自在。',button('编辑画像','basic','secondary'))+dayControls()+
    (stale?`<div class="warning">画像已经更新，下面仍是旧画像生成的计划。请重新生成后再做选择，确保新的忌口生效。</div>`:'')+
    `<div class="dashboard"><section>${coachCard()}${energyPanel()}<div class="section-head"><h2>今天怎么吃</h2><small>三餐有安排，变化也没关系</small></div>${mealSummary('breakfast')}${mealSummary('lunch',true)}${mealSummary('snack')}${mealSummary('dinner')}<p class="note">餐食均已按保存时的忌口标签过滤；下午茶可自行取消或恢复；份量、营养为基础食材参考估算，不能保证门店实际配料一致。</p><div class="section-head"><h2>喜欢的小满足</h2>${button('添加饮品 / 小食','snacks','secondary')}</div>${snackList()}<div class="section-head"><h2>今天，动一动或歇一歇</h2>${button('安排运动','activity','secondary')}</div><p class="muted">${esc(state.plan.movement)}</p>${activityList()}<p class="note">运动消耗单独展示，不从饮食计划中扣除。</p><details class="rule-details"><summary>看看原型估算、规则和版本</summary><p>维持能量参考：${state.plan.reference.low}–${state.plan.reference.high} 千卡。${esc(state.plan.reference.label)}。</p><p>估算静息能量约 ${state.plan.reference.bmr_estimate} 千卡 × 原型活动系数 ${state.plan.reference.activity_factor}。<a class="textbtn" href="${esc(state.plan.reference.source_url)}" target="_blank" rel="noopener">公式来源</a></p><p>以下按当前启用餐次计算，未包含后来添加的小食；取消下午茶后可能低于原参考范围，未达项会如实显示。阈值待专业复核，通过不等于营养充分或适合个人。</p>${state.plan.checks.map(x=>`<span class="pill">${esc(x.name)} · ${x.passed?'通过':'未通过'}</span>`).join(' ')}<p class="note">模型 ${esc(state.plan.versions.model)} · Prompt ${esc(state.plan.versions.prompt)} · 知识库 ${esc(state.plan.versions.kb)} · 规则 ${esc(state.plan.versions.rules)}</p></details></section><aside><div class="sidecard"><span class="eyebrow">A PLAN THAT MOVES WITH YOU</span><h2>计划赶不上变化？<br>那就一起调一调。</h2><p>临时聚餐、加班或想喝奶茶，也可以从容安排。</p>${button('调整今天的计划','adjust')}</div><div class="sidecard white"><h3>你的饮食小偏好</h3><div class="rule">${esc(sourceText(p))}优先<small>先考虑现实中容易找到的</small></div><div class="rule">${esc(p.preferences||'按自己的口味')}<small>好好吃，也要吃得喜欢</small></div><div class="rule">${esc(p.exclusions.join('、')||p.exclusions_note||'暂未填写忌口')}<small>全部餐次在生成时过滤</small></div></div><div class="sidecard white"><span class="eyebrow">属于你的节奏</span><h3>${esc(data.focus)}</h3><p>${esc(data.items[0])}</p>${button('查看 / 调整策略','strategy','light')}</div><div class="sidecard white"><h3>这份安排，适合你吗？</h3><div class="rating" aria-label="生活适配评分">${[1,2,3,4,5].map(n=>`<button class="chip" data-action="rate" data-score="${n}" aria-label="${n} 分">${n}</button>`).join('')}</div><p class="note">1 分不太适合，5 分很合适。反馈只保存在本机，不代表已验证效果。</p></div></aside></div>`;
}
function mealBrowseKey(scene){return `${state.day}:${state.profile?.version}:${state.meal}:${scene}`;}
async function browseMeals({scene=location.hash==='#takeout'?'delivery':'profile',offset=0,nextBatch=false}={}){
  const key=mealBrowseKey(scene), previous=state.mealBrowser;
  const query=state.mealQuery.trim(),family=['lunch','dinner'].includes(state.meal)?state.mealFamily:'';
  const same=previous?.key===key&&previous.query===query&&previous.family===family;
  const excluded=nextBatch&&same?previous.seen:[];
  const result=await api('/api/meals/search',{...requestBase(),meal:state.meal,scene,query,family,offset,limit:scene==='delivery'&&!query?3:6,exclude_ids:excluded});
  if(nextBatch&&!result.options.length){toast('当前条件下的外卖示例已经看完，可以修改关键词或类型；已选餐食保持不变。');return;}
  state.mealBrowser={...result,key,meal:state.meal,query,family,seen:[...new Set([...excluded,...result.options.map(o=>o.id)])]};
  render();
}
function mealOptionCard(o,i,{catalog=false,scene='profile'}={}){
  const m=state.plan.meals[state.meal],locked=m.completed||m.enabled===false;
  return `<article class="option"><span class="eyebrow">OPTION ${i+1}</span><span class="tag">${o.id===m.selected.id?'已选方案':'可以选择'}</span><h2>${esc(o.title)}</h2>${o.meal_family?`<span class="pill">${esc(o.meal_family)}</span>`:''}<p>${esc(o.reason)}</p><div class="portion"><h3>一餐这样搭</h3>${o.ingredients.map(x=>`<p>${esc(x.name)} · ${esc(x.portion)}</p>`).join('')}<small class="muted">约 ${numberText(o.nutrition.kcal)} 千卡 · 参考估算<br>蛋白质 ${o.nutrition.protein}g · 碳水 ${o.nutrition.carbs}g · 脂肪 ${o.nutrition.fat}g</small></div><p>${esc(o.tip)}</p>${o.source_url?`<p class="note"><a href="${esc(o.source_url)}" target="_blank" rel="noopener">${esc(o.source_type||'营养参考来源')}</a></p>`:''}${o.estimate_note?`<p class="note">${esc(o.estimate_note)}</p>`:''}${action(o.id===m.selected.id?'已经选好':'选择这个','choose','',`data-id="${esc(o.id)}" data-catalog="${catalog}" data-scene="${scene}" ${locked||o.id===m.selected.id?'disabled':''}`)}</article>`;
}
function lunchPage(takeout=false){
  if(!state.profile)return needProfile();if(!state.plan)return needPlan();
  const p=profile(),m=state.plan.meals[state.meal],scene=takeout?'delivery':'profile',locked=m.completed||m.enabled===false;
  const families=[...new Set(['米饭配餐','自选汤锅','品牌汉堡配餐',...(state.recipeCatalog||[]).map(r=>r.meal_family).filter(Boolean)])];
  const selector=['lunch','dinner'].includes(state.meal)?`<div class="searchbar"><label>想换成哪类餐食？<select id="meal-family"><option value="">不限，看看不同搭配</option>${families.map(f=>`<option ${state.mealFamily===f?'selected':''}>${esc(f)}</option>`).join('')}</select></label></div>`:'';
  const menu=state.mealBrowser?.key===mealBrowseKey(scene)?state.mealBrowser:null;
  const options=menu?menu.options:takeout?[]:m.candidates;
  const title=takeout?`${labels[state.meal]}外卖，选一份方便的`:`${labels[state.meal]}，选一份喜欢的`;
  const extra=takeout?button('返回餐食推荐','lunch','secondary'):button('返回今日','home','secondary');
  const controls=takeout?`<div class="actions">${action('没有合适的，换一批','takeout-refresh','secondary',locked?'disabled':'')}${action('不喜欢，换一批','takeout-refresh','light',locked?'disabled':'')}</div>`:`<div class="actions">${action('没有这些菜','refresh-options','secondary',`data-reason="unavailable" ${locked?'disabled':''}`)}${action('不喜欢，换一批','refresh-options','light',`data-reason="dislike" ${locked?'disabled':''}`)}${action('换一批','refresh-options','secondary',`data-reason="refresh" ${locked?'disabled':''}`)}</div>`;
  return heading(title,takeout?'按常见外卖搭配找灵感，选择后加入当天计划。':'推荐之外，也可以搜一搜，按自己的喜好选。',extra)+
  (takeout?`<div class="chiprow">${['lunch','dinner'].map(k=>`<button class="chip ${state.meal===k?'selected':''}" data-action="takeout-meal" data-meal="${k}">${labels[k]}外卖</button>`).join('')}</div><p class="note">这里是常见外卖示例，不是实时门店菜单。暂无价格、库存、配送和下单功能；品牌配餐含自备配菜时会明确标注。</p>`:`<div class="chiprow">${Object.entries(labels).map(([k,v])=>`<button class="chip ${state.meal===k?'selected':''}" data-action="meal-route" data-meal="${k}">${v}${k==='snack'?' · 可选':''}</button>`).join('')}${['lunch','dinner'].includes(state.meal)?action('选择外卖','open-takeout','secondary'):''}</div>`)+
  `<div class="chiprow"><span class="pill">${takeout?'本次选择：外卖':esc(sourceText(p))}</span><span class="pill">忌口：${esc(p.exclusions.join('、')||'未填写')}</span>${!takeout&&!menu?`<span class="pill">第 ${m.batch} 批</span>`:''}</div><div class="success">${m.enabled===false?'今天未安排下午茶，先恢复后再选择。':`当前已选：${esc(m.selected.title)}。浏览、搜索和换一批都不会改变已选餐食，点击「选择这个」才更新。`}${m.completed?'这餐已经完成，请先在今日页取消完成后再修改。':''}</div>${m.enabled===false?action('恢复下午茶','toggle-snack','secondary','data-enabled="true"'):''}${selector}
  <form id="mealsearch" class="searchbar meal-search"><label>搜索餐食或食材<input type="search" name="query" maxlength="60" value="${esc(state.mealQuery)}" placeholder="例如：鸡肉、米粉、豆腐"></label><button class="button" type="submit">搜索</button>${menu?action(takeout?'返回外卖推荐':'返回推荐','clear-meal-search','light'):''}</form><p class="note">在当前食品库中搜索，仍保留你的忌口；留空搜索可浏览全部可选搭配。</p>
  ${menu?`<div class="section-head"><h2>${menu.query?'搜索结果':takeout?'外卖搭配推荐':'全部可选餐食'}</h2><small>符合条件 ${menu.total} 个${menu.options.length?` · 本页 ${menu.offset+1}–${menu.offset+menu.options.length}`:''}</small></div>`:''}
  <div class="listcards">${options.map((o,i)=>mealOptionCard(o,i,{catalog:!!menu,scene})).join('')}</div>${!options.length?`<div class="empty-meals"><h3>${menu?'没有找到符合条件的餐食':'看看今天有哪些外卖选择'}</h3><p>${menu?'换个关键词或类型试试，已选餐食保持不变。':'点击下方按钮查看常见外卖搭配。'}</p>${takeout&&!menu?action('查看外卖推荐','takeout-refresh','secondary'):''}</div>`:''}
  ${menu&&(menu.query||!takeout)?`<div class="actions">${menu.offset>0?action('上一页','meal-page','secondary',`data-offset="${Math.max(0,menu.offset-6)}"`):''}${menu.has_more?action('下一页','meal-page','secondary',`data-offset="${menu.offset+6}"`):''}</div>`:controls}
  <p class="note">候选包含常见点餐示例与品牌标准产品配餐；尚未连接附近门店的价格、库存和配送，不保证商家有售。营养数据和规则待专业复核。</p>`;
}
function activityDiffView(before,after){
  const previous=before.activities||[], next=after.activities||[];
  const removed=previous.filter(a=>!next.some(b=>b.entry_id===a.entry_id));
  const added=next.filter(a=>!previous.some(b=>b.entry_id===a.entry_id));
  if(!previous.length&&!next.length&&before.movement===after.movement)return '';
  const unchanged=JSON.stringify(previous)===JSON.stringify(next);
  const list=items=>items.length?items.map(a=>`<p>${esc(a.name)} · ${esc(a.minutes)} 分钟</p>`).join(''):'<p>没有已安排的运动，可以休息。</p>';
  return `<div class="compare"><div><h3>调整前 · 已安排运动</h3>${list(previous)}</div><div><h3>调整后 · 已安排运动</h3>${list(next)}${unchanged?'<p class="note">运动项目保持不变。休息建议不代表已经取消原运动。</p>':''}${removed.map(a=>`<p><strong>取消：${esc(a.name)} · ${esc(a.minutes)} 分钟</strong></p>`).join('')}${added.map(a=>`<p><strong>新增：${esc(a.name)} · ${esc(a.minutes)} 分钟</strong></p>`).join('')}</div></div>`;
}
function draftView(draft){
  if(!draft)return '';
  const before=draft.before_data,after=draft.candidate;
  const rows=Object.keys(labels).filter(k=>before.meals[k].selected.id!==after.meals[k].selected.id);
  return `<div class="draft"><span class="pill">${esc(sourceBadge(draft.source))} · ${draft.status==='pending'?'待确认草案':'已处理'}</span><div class="coach-reply"><strong>小自在的调整建议</strong><p>${esc(draft.message)}</p></div>${activityDiffView(before,after)}${rows.map(k=>`<div class="compare"><div><span class="eyebrow">调整前 · ${labels[k]}</span><h3>${esc(before.meals[k].selected.title)}</h3><p>约 ${numberText(before.meals[k].selected.nutrition.kcal)} 千卡</p></div><div><span class="eyebrow">调整后 · ${labels[k]}</span><h3>${esc(after.meals[k].selected.title)}</h3><p>约 ${numberText(after.meals[k].selected.nutrition.kcal)} 千卡</p><p>${esc(after.meals[k].selected.tip)}</p></div></div>`).join('')}${before.movement!==after.movement?`<div class="compare"><div><h3>原运动建议</h3><p>${esc(before.movement)}</p></div><div><h3>调整后</h3><p>${esc(after.movement)}</p></div></div>`:''}${before.strategy!==after.strategy?`<div class="compare"><div><h3>原策略</h3><p>${esc(before.strategy)}</p></div><div><h3>新的策略</h3><p>${esc(after.strategy)}</p></div></div>`:''}<p class="note">调整仅影响：${esc(draft.changes.join('、'))}。已完成餐次保留；额外饮品小食仍会保留，配方未知时不能做精确热量抵扣。确认会将计划版本 ${draft.base_version} 更新。</p>${draft.status==='pending'?`<div class="actions">${action('保留原计划','discard-draft','secondary',`data-id="${draft.id}"`)}${action('确认并应用调整','confirm-draft','',`data-id="${draft.id}"`)}</div>`:''}</div>`;
}
function adjustPage(){
  if(!state.profile)return needProfile();if(!state.plan)return needPlan();
  return `<div class="adjust">${heading('生活有变化，小自在陪你调一调','今天的安排可以有弹性。先看看建议，再决定要不要应用。',button('返回今日','home','secondary'))}<div class="formcard"><span class="pill">小自在 · ${state.mode==='demo'?'本地场景模板':'DeepSeek AI'}</span><h2 style="margin-top:20px">今天有什么新安排？</h2><div class="chiprow">${['今晚和朋友吃火锅','下午想喝奶茶','今天加班，不想运动'].map(x=>`<button class="chip" data-action="prompt" data-text="${esc(x)}">${esc(x)}</button>`).join('')}</div><form id="adjustform"><label>说说你的变化<textarea name="request" maxlength="600" required placeholder="例如：今天加班，晚餐想简单一些，也不想运动">${esc(state.request)}</textarea></label><p class="muted">当前计划版本 ${state.plan.version}。原计划会保留，只有确认后才会更新。</p><button class="button" type="submit">${state.mode==='demo'?'查看演示调整草案':'请 DeepSeek 生成草案'}</button></form><p class="note">演示模式只识别奶茶、聚餐／火锅、加班／运动三个场景。自由描述请选 DeepSeek；接口失败不会自动冒充 AI 返回模板。</p>${draftView(state.draft)}</div>${state.adjustments.some(x=>x.status==='pending')?`<p class="note">有未处理的草案，刷新后也可在${button('调整记录','history','light')}中继续查看。</p>`:''}</div>`;
}
function render(){
  let route=location.hash.slice(1)|| (state.profile?'home':'welcome');if(!pages.some(x=>x[0]===route)&&route!=='takeout')route='home';
  $('#nav').innerHTML=pages.map((p,i)=>`<a href="#${p[0]}" class="${p[0]===route||(route==='takeout'&&p[0]==='lunch')?'active':''}" ${p[0]===route||(route==='takeout'&&p[0]==='lunch')?'aria-current="page"':''}><span>${String(i+1).padStart(2,'0')}</span>${p[1]}</a>`).join('');$('#crumb').textContent=route==='takeout'?'常见外卖':pages.find(x=>x[0]===route)[1];
  let content='';
  if(route==='welcome')content=welcomePage();
  else if(['basic','life','preferences'].includes(route))content=profilePage(route);
  else if(route==='home')content=homePage();
  else if(route==='lunch'||route==='takeout')content=lunchPage(route==='takeout');
  else if(route==='adjust')content=adjustPage();
  else content=extraPage(route);
  $('#app').innerHTML=`<div id="global-alert" class="warning" role="alert" ${state.error?'':'hidden'}>${esc(state.error)}</div>`+content;
  bindForms();bindExtraForms();
  if(state.busy){document.querySelectorAll('#app button,#app input,#app select,#app textarea').forEach(x=>{x.dataset.wasDisabled=String(x.disabled);x.disabled=true;});}
}
function readProfileForm(form){
  const data=new FormData(form), step=Number(form.dataset.step);
  for(const [k,v] of data){if(['meal_sources','exclusions','ai_consent'].includes(k))continue;state.form[k]=['age','height_cm','current_weight_kg','target_weight_kg','target_weeks'].includes(k)?Number(v):v.trim();}
  if(step===2)state.form.meal_sources=data.getAll('meal_sources');
  if(step===3){state.form.exclusions=data.getAll('exclusions');state.form.ai_consent=data.has('ai_consent');}
}
function bindForms(){
  const family=$('#meal-family');if(family)family.addEventListener('change',()=>{state.mealFamily=family.value;if(location.hash==='#takeout'||state.mealBrowser)run(()=>browseMeals());});
  const search=$('#mealsearch');if(search){search.elements.query.addEventListener('input',()=>{state.mealQuery=search.elements.query.value;});search.addEventListener('submit',e=>{e.preventDefault();state.mealQuery=search.elements.query.value;run(()=>browseMeals());});}
  const f=$('#profileform');
  if(f)f.addEventListener('submit',event=>{event.preventDefault();if(!f.reportValidity())return;readProfileForm(f);if(Number(f.dataset.step)===2&&!state.form.meal_sources.length){showError('请至少选择一种饮食来源。');return;}if(f.dataset.step!=='3'){location.hash=f.dataset.next;return;}run(async()=>{const data=await api('/api/profile',{profile:state.form,expected_version:state.profile?.version||0},'PUT');state.profile=data.profile;state.form=structuredClone(data.profile.data);state.draft=null;await refreshState();location.hash='strategy';render();toast('画像已保存到本机');});});
  const af=$('#adjustform');if(af)af.addEventListener('submit',event=>{event.preventDefault();state.request=af.elements.request.value;run(async()=>{const data=await api('/api/adjustments',{...requestBase(),request:state.request,mode:state.mode});state.draft=data.adjustment;await refreshState();render();toast('草案已保存，正式计划尚未改变');});});
  const day=$('#day');if(day)day.addEventListener('change',()=>{if(!day.value)return;run(async()=>{state.day=day.value;state.draft=null;await refreshState();render();});});
}
async function generate(){
  if(state.plan&&!confirm('重新生成会替换这一天的餐食、小食和运动安排，恢复可选下午茶，并使旧草案过期。确定重新生成吗？'))return;
  const result=await api('/api/plans/generate',{...requestBase(),mode:state.mode,reset_completed:true});
  state.draft=null;await setPlan(result,'计划已保存，刷新后仍然保留');location.hash='home';
}
document.addEventListener('click',event=>{
  const b=event.target.closest('[data-action]');if(!b||b.disabled||state.busy)return;
  const name=b.dataset.action;
  if(name==='meal-route'){if(state.meal!==b.dataset.meal)state.mealFamily='';state.meal=b.dataset.meal;state.mealBrowser=null;state.mealQuery='';location.hash='lunch';render();return;}
  if(name==='prompt'){state.request=b.dataset.text;if($('#adjustform'))$('#adjustform').elements.request.value=state.request;return;}
  run(async()=>{
    if(name==='toggle-coach'){const data=await api('/api/coach/preferences',{date:state.day,expected_profile_version:state.profile.version,collapsed:!state.coach.collapsed});state.coach=data.coach;render();}
    else if(name==='generate')await generate();
    else if(name==='open-takeout'||name==='takeout-meal'){if(name==='takeout-meal')state.meal=b.dataset.meal;state.mealQuery='';state.mealFamily='';state.mealBrowser=null;await browseMeals({scene:'delivery'});location.hash='takeout';render();}
    else if(name==='takeout-refresh')await browseMeals({scene:'delivery',nextBatch:true});
    else if(name==='meal-page')await browseMeals({offset:Number(b.dataset.offset)});
    else if(name==='clear-meal-search'){state.mealQuery='';state.mealBrowser=null;if(location.hash==='#takeout')await browseMeals({scene:'delivery'});else render();}
    else if(name==='toggle-snack'){await setPlan(await api('/api/meals/optional',{...requestBase(),meal:'snack',enabled:b.dataset.enabled==='true'}),b.dataset.enabled==='true'?'下午茶已恢复并计入计划':'下午茶已取消，三餐与额外小食保留');}
    else if(name==='choose')await setPlan(await api('/api/meals/select',{...requestBase(),meal:state.meal,option_id:b.dataset.id,selection_source:b.dataset.catalog==='true'?'catalog':'batch',scene:b.dataset.scene||'profile'}),'已采用这个方案');
    else if(name==='refresh-options'){state.mealBrowser=null;state.mealQuery='';await setPlan(await api('/api/meals/refresh',{...requestBase(),meal:state.meal,reason:b.dataset.reason,family:['lunch','dinner'].includes(state.meal)?state.mealFamily||'':''}),'已更新候选，当前已选餐食仍保留');}
    else if(name==='meal-complete')await setPlan(await api('/api/meals/complete',{...requestBase(),meal:b.dataset.meal,completed:!state.plan.meals[b.dataset.meal].completed}),'完成状态已保存');
    else if(name==='confirm-draft'||name==='discard-draft'){const result=await api(`/api/adjustments/${b.dataset.id}/${name==='confirm-draft'?'confirm':'discard'}`,{});state.draft=null;await setPlan(result,name==='confirm-draft'?'调整已应用，按今天的节奏来就好':'已保留原计划，选择权在你手里');}
    else if(name==='rate'){await api('/api/feedback',{...requestBase(),score:Number(b.dataset.score)});toast('反馈已保存，谢谢你告诉我们');}
    else await extraAction(name,b);
  });
});
$('#mode').addEventListener('change',event=>{state.mode=event.target.value;render();if(state.mode==='deepseek'&&!state.status?.deepseek_configured)toast('尚未配置 API Key，请参照 README 在本地 .env 中填写并重启');});
window.addEventListener('hashchange',()=>{
  if(location.hash==='#takeout'&&!['lunch','dinner'].includes(state.meal))state.meal='lunch';
  if(location.hash==='#lunch'&&state.mealBrowser?.scene==='delivery'){state.mealBrowser=null;state.mealQuery='';}
  if(state.initialized){render();if(location.hash==='#takeout'&&state.plan&&state.profile&&state.mealBrowser?.key!==mealBrowseKey('delivery'))run(()=>browseMeals({scene:'delivery'}));}
  window.scrollTo(0,0);
});
window.addEventListener('DOMContentLoaded',async()=>{
  try{state.status=await api('/api/status');const [foods,snacks,recipes]=await Promise.all([api('/api/foods'),api('/api/snacks'),api('/api/recipes')]);state.foods=foods.foods;state.snackCatalog=snacks.snacks;state.recipeCatalog=recipes.recipes;await refreshState(true);if(location.hash==='#takeout'&&state.plan)await browseMeals({scene:'delivery'});state.initialized=true;render();}
  catch(e){state.initialized=true;state.error=e.message;render();}
});
