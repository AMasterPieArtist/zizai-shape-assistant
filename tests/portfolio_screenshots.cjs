// Portfolio captures use a new temporary database and synthetic profiles only.
// Optional: requires Playwright + installed Microsoft Edge, not needed to run the app.
const {chromium}=require(process.env.PLAYWRIGHT_PATH || 'playwright');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'zizai-portfolio-'));
const out=path.join(root,'docs','screenshots','portfolio');
let browser,server;
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const probe=require('node:net').createServer();
  await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;
  await new Promise(r=>probe.close(r));const base=`http://127.0.0.1:${port}`;
  // Prevent inherited credentials from being used; no .env is included in release.
  server=spawn(process.env.PYTHON || 'python',['app.py','--port',String(port),'--db',path.join(temp,'demo.sqlite3')],{
    cwd:root,windowsHide:true,stdio:'ignore',env:{...process.env,DEEPSEEK_API_KEY:''}
  });
  let ready=false;
  for(let i=0;i<80;i++){try{if((await fetch(base+'/api/status')).ok){ready=true;break;}}catch{} await new Promise(r=>setTimeout(r,100));}
  assert(ready,'Server failed to start');
  browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1080},deviceScaleFactor:1});
  const errors=[],captures=[];page.on('pageerror',e=>errors.push(e.message));
  async function nav(hash){await page.goto(base+'/#'+hash);await page.waitForFunction(()=>state.initialized&&!state.busy);await page.evaluate(()=>window.scrollTo(0,0));await page.waitForTimeout(150);}
  async function shot(name,locator){
    await page.waitForFunction(()=>{const e=document.querySelector('#toast');return !e||getComputedStyle(e).display==='none'||Number(getComputedStyle(e).opacity)===0;});
    await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(100);
    const p=path.join(out,name+'.png');
    if(locator)await locator.screenshot({path:p});else await page.screenshot({path:p});
    captures.push({file:'docs/screenshots/portfolio/'+name+'.png',route:await page.evaluate(()=>location.hash),synthetic:true,mode:'demo'});
  }
  await page.goto(base+'/#welcome');await page.waitForFunction(()=>state.initialized);
  await shot('01-welcome');
  await page.evaluate(async()=>{
    const p={...defaults,nickname:'小满',work_intensity:'busy',sleep:'经常晚睡',health_status:'general',meal_sources:['canteen','delivery'],preferences:'喜欢清淡，也想给咖啡留个位置',ai_consent:false};
    await api('/api/profile',{profile:p,expected_version:0},'PUT');
    for(const ago of [2,1,0]){
      const d=new Date();d.setDate(d.getDate()-ago);
      const day=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
      let plan=(await api('/api/plans/generate',{date:day,mode:'demo'})).plan;
      plan=(await api('/api/meals/complete',{date:day,expected_version:plan.version,meal:ago?'lunch':'breakfast',completed:true})).plan;
      if(!ago){
        plan=(await api('/api/activities/add',{date:day,expected_version:plan.version,kind:'swim',minutes:30})).plan;
        await api('/api/activities/add',{date:day,expected_version:plan.version,kind:'walk',minutes:20});
      }
    }
  });
  await page.reload();await page.waitForFunction(()=>state.initialized&&state.plan);
  await nav('home');await shot('02-today');
  await nav('strategy');await shot('03-strategy');
  await page.setViewportSize({width:1440,height:1660});
  await nav('lunch');await page.locator('#mealsearch input').fill('米粉');
  await page.getByRole('button',{name:'搜索',exact:true}).click();
  await page.waitForFunction(()=>!state.busy&&state.mealBrowser?.query==='米粉');
  assert(await page.locator('.option').count()>0);await shot('04-meal-search');
  await page.getByRole('button',{name:'选择外卖',exact:true}).click();
  await page.waitForFunction(()=>location.hash==='#takeout'&&!state.busy&&state.mealBrowser?.scene==='delivery');
  // The scene retains the previous query; clear it to show a normal recommendation batch.
  await page.locator('#mealsearch input').fill('');await page.getByRole('button',{name:'搜索',exact:true}).click();
  await page.waitForFunction(()=>!state.busy&&state.mealBrowser?.query==='');await shot('05-takeout');
  await page.setViewportSize({width:1440,height:1080});
  await nav('snacks');await page.locator('#snacksearch input[name="q"]').fill('热奶铁');
  await page.getByRole('button',{name:'查询',exact:true}).click();
  assert.equal(await page.locator('.option').count(),3);await shot('06-drinks');
  await nav('adjust');
  await page.locator('#adjustform textarea').fill('今天临时加班，晚餐想方便一些。取消游泳，步行保留。');
  await page.locator('#adjustform button').click();
  await page.waitForFunction(()=>!state.busy&&state.draft?.status==='pending');
  assert.equal(await page.evaluate(()=>state.plan.activities.length),2);
  assert.equal(await page.evaluate(()=>state.draft.candidate.activities.length),1);
  await shot('07-adjustment',page.locator('.draft'));
  await page.getByRole('button',{name:'确认并应用调整',exact:true}).click();
  await page.waitForFunction(()=>!state.busy&&state.plan.activities.length===1);
  assert.equal(await page.evaluate(()=>state.plan.activities[0].kind),'walk');
  await nav('home');await page.setViewportSize({width:390,height:844});
  await shot('08-mobile');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);
  const report={captured_at:new Date().toISOString(),profile:'Synthetic adult 小满, busy workday',real_model_calls:0,isolated_database:true,swimming_removed_after_confirmation:true,mobile_overflow:false,page_errors:errors,captures};
  fs.writeFileSync(path.join(out,'capture-report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({result:'PASS',screenshots:captures.length,pageErrors:errors,isolatedDatabase:true}));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();
  if(server&&server.exitCode===null){const stopped=new Promise(r=>server.once('exit',r));server.kill();await stopped;}
  fs.rmSync(temp,{recursive:true,force:true});
});
