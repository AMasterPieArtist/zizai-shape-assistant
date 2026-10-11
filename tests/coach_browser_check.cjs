// Verify Xiaozizai against synthetic data, without paid model requests.
const {chromium}=require(process.env.PLAYWRIGHT_PATH || 'playwright');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const root=path.resolve(__dirname,'..'),temp=fs.mkdtempSync(path.join(os.tmpdir(),'zizai-coach-'));
let browser,server,base;
(async()=>{
  const probe=require('node:net').createServer();
  await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;
  await new Promise(r=>probe.close(r));base=`http://127.0.0.1:${port}`;
  server=spawn(process.env.PYTHON || 'python',['app.py','--port',String(port),'--db',path.join(temp,'test.sqlite3')],{cwd:root,windowsHide:true,stdio:'ignore'});
  let ready=false;
  for(let i=0;i<80;i++){try{if((await fetch(base+'/api/status')).ok){ready=true;break;}}catch{} await new Promise(r=>setTimeout(r,100));}
  assert(ready,'Test server did not start');
  browser=await chromium.launch({channel:'msedge',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.waitForFunction(()=>state.initialized);
  assert.equal(await page.evaluate(()=>state.coach),null);
  await page.evaluate(async()=>{
    const p={...defaults,nickname:'陪伴测试',work_intensity:'busy',health_status:'general',meal_sources:['canteen','delivery'],ai_consent:false};
    await api('/api/profile',{profile:p,expected_version:0},'PUT');
    for(const ago of [2,1,0]){
      const date=new Date();date.setDate(date.getDate()-ago);
      const day=`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
      let plan=(await api('/api/plans/generate',{date:day})).plan;
      plan=(await api('/api/meals/complete',{date:day,expected_version:plan.version,meal:'lunch',completed:true})).plan;
      if(ago===0){
        plan=(await api('/api/activities/add',{date:day,expected_version:plan.version,kind:'swim',minutes:30})).plan;
        await api('/api/activities/add',{date:day,expected_version:plan.version,kind:'walk',minutes:20});
      }
    }
  });
  await page.goto(base+'/#home');await page.reload();await page.waitForFunction(()=>state.initialized&&state.coach);
  const card=page.getByRole('region',{name:'小自在陪伴'});
  await card.waitFor({state:'visible'});
  assert.equal(await page.evaluate(()=>state.coach.stats.completed_days),3);
  assert((await card.innerText()).includes('3 天标记过餐次完成'));
  await card.getByText('这句话依据什么？').click();
  assert((await card.innerText()).includes('非 AI 生成'));
  const dir=path.join(root,'docs','screenshots');fs.mkdirSync(dir,{recursive:true});
  await page.screenshot({path:path.join(dir,'coach-home-desktop.png'),fullPage:true});
  const before=await page.evaluate(()=>JSON.stringify(state.plan));
  await page.getByRole('button',{name:'收起陪伴',exact:true}).click();
  await page.waitForFunction(()=>!state.busy&&state.coach.collapsed);
  assert.equal(await page.evaluate(()=>JSON.stringify(state.plan)),before);
  await page.reload();await page.waitForFunction(()=>state.initialized&&state.coach);
  assert.equal(await card.locator('.coach-message').count(),0);
  await page.getByRole('button',{name:'展开陪伴',exact:true}).click();
  await page.waitForFunction(()=>!state.busy&&!state.coach.collapsed);
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(dir,'coach-home-mobile.png'),fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Coach mobile horizontal overflow');
  await page.getByRole('link',{name:'和小自在调整计划',exact:true}).click();
  await page.locator('#adjustform textarea').fill('今天临时加班，晚餐想方便一些。取消游泳，步行保留。');
  await page.locator('#adjustform button').click();
  await page.waitForFunction(()=>!state.busy&&state.draft?.status==='pending');
  assert((await page.locator('.coach-reply').innerText()).includes('小自在的调整建议'));
  assert.equal(await page.evaluate(()=>state.plan.activities.length),2,'Draft must not immediately remove swimming');
  await page.screenshot({path:path.join(dir,'coach-adjust-mobile.png'),fullPage:true});
  await page.getByRole('button',{name:'确认并应用调整',exact:true}).click();
  await page.waitForFunction(()=>!state.busy&&state.plan.activities.length===1);
  assert.equal(await page.evaluate(()=>state.plan.activities[0].kind),'walk');
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(async()=>{
    const p={...state.profile.data,nickname:'测试画像B',preferences:'不同测试画像'};
    await api('/api/profile',{profile:p,expected_version:state.profile.version},'PUT');
  });
  await page.goto(base+'/#home');await page.reload();await page.waitForFunction(()=>state.initialized&&state.coach);
  assert.equal(await page.evaluate(()=>state.coach.stats.completed_days),0);
  assert.equal(await page.evaluate(()=>state.coach.kind),'profile_changed');
  assert((await card.innerText()).includes('画像更新了'));
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({result:'PASS',groundedCompletionFeedback:true,collapsePersistent:true,collapseLeavesPlanUnchanged:true,dynamicAdjustmentKeepsConfirmation:true,swimRemovedWalkPreserved:true,profileHistorySeparated:true,mobileOverflow:false,consoleErrors:errors}));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{
  if(browser)await browser.close();
  if(server&&server.exitCode===null){const stopped=new Promise(r=>server.once('exit',r));server.kill();await stopped;}
  fs.rmSync(temp,{recursive:true,force:true});
});
