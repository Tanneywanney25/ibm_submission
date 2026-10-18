/* npm install --prefix /tmp/heatahead-dom jsdom@26
 * NODE_PATH=/tmp/heatahead-dom/node_modules node web/tests/test_privacy.cjs
 * Development-only DOM tests; no production dependency or network requests.
 */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM}=require('jsdom');
const source=file=>fs.readFileSync(path.join(__dirname,'..',file),'utf8');
const privacyMarkup=source('templates/_privacy.html');
const privacyScript=source('static/privacy.js');
const windows=[];
const KEY='heatahead_privacy',PANELS='heatahead_panels';
function setup(choice,blocked=false){
  const dom=new JSDOM('<!doctype html><body><footer><button class="privacy-footer-button" data-open-privacy hidden>Cookie settings</button></footer>'+privacyMarkup+'</body>',
    {url:'https://heatahead.test',runScripts:'outside-only'});
  const win=dom.window;windows.push(win);
  win.localStorage.setItem(PANELS,'["queue"]');
  if(choice)win.localStorage.setItem(KEY,JSON.stringify(choice));
  const reads=[];
  const get=win.Storage.prototype.getItem;
  win.Storage.prototype.getItem=function(key){reads.push(key);if(blocked)throw new Error('blocked');return get.call(this,key);};
  if(blocked){win.Storage.prototype.setItem=win.Storage.prototype.removeItem=()=>{throw new Error('blocked');};}
  win.eval(privacyScript);win.document.dispatchEvent(new win.Event('DOMContentLoaded'));
  return {win,doc:win.document,api:win.HeatAheadPrivacy,reads};
}
function click(doc,selector){doc.querySelector(selector).click();}
function tick(){return new Promise(resolve=>setImmediate(resolve));}

async function run(){
  {
    const {win,doc,api,reads}=setup();
    assert.equal(doc.getElementById('privacy-banner').hidden,false);
    assert.equal(api.preferencesAllowed(),false);
    assert.equal(api.readPanels(),null);
    assert.equal(api.savePanels(['buildings']),false);
    assert.equal(reads.includes(PANELS),false,'No optional reads before consent');
    assert.equal(win.localStorage.getItem(PANELS),null,'Old unconsented copy is removed');
    const button=doc.querySelector('[data-privacy-accept]');button.focus();button.click();
    assert.equal(api.preferencesAllowed(),true);
    assert.equal(doc.getElementById('privacy-banner').hidden,true);
    assert.equal(doc.activeElement,doc.querySelector('.privacy-footer-button'));
    assert.equal(api.savePanels(['stats','queue']),true);
    assert.deepEqual(Array.from(api.readPanels()),['stats','queue']);
    const footer=doc.querySelector('.privacy-footer-button');footer.click();
    assert.equal(doc.getElementById('privacy-overlay').hidden,false);
    assert.equal(doc.getElementById('privacy-preferences').checked,true);
    assert.equal(doc.activeElement.id,'privacy-close');
    doc.activeElement.dispatchEvent(new win.KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));
    assert.equal(doc.activeElement,doc.querySelector('#privacy-dialog [data-privacy-reject]'));
    doc.activeElement.dispatchEvent(new win.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
    assert.equal(doc.getElementById('privacy-overlay').hidden,true);
    assert.equal(doc.activeElement,footer);
    doc.cookie='heatahead_account=test-session; path=/; secure; samesite=lax';
    footer.click();doc.getElementById('privacy-preferences').checked=false;click(doc,'#privacy-save');
    assert.equal(api.preferencesAllowed(),false);
    assert.equal(win.localStorage.getItem(PANELS),null);
    assert.match(doc.cookie,/heatahead_account=test-session/,'Rejecting optional storage does not sign out');
    assert.equal(JSON.parse(win.localStorage.getItem(KEY)).preferences,false);
    // A later cross-tab withdrawal applies to this page too.
    footer.click();doc.getElementById('privacy-preferences').checked=true;click(doc,'#privacy-save');
    api.savePanels(['queue']);
    win.localStorage.setItem(KEY,JSON.stringify({version:1,preferences:false,decidedAt:Date.now()}));
    win.dispatchEvent(new win.StorageEvent('storage',{key:KEY}));
    assert.equal(api.preferencesAllowed(),false);assert.equal(win.localStorage.getItem(PANELS),null);
  }
  {
    const {win,doc,api}=setup();
    api.setHelpOpen(true);
    assert.equal(doc.getElementById('privacy-banner').hidden,true);
    assert.equal(api.preferencesAllowed(),false);
    assert.equal(win.localStorage.getItem(KEY),null,'Opening help never records acceptance');
    api.setHelpOpen(false);
    assert.equal(doc.getElementById('privacy-banner').hidden,false,'Undecided choices return after closing help');
  }
  for(const choice of [{version:1,preferences:true,decidedAt:Date.now()-181*86400000},
                       {version:0,preferences:true,decidedAt:Date.now()},
                       {version:1,preferences:true,decidedAt:Date.now()+100000}]){
    const {doc,api,reads}=setup(choice);
    assert.equal(api.preferencesAllowed(),false);assert.equal(doc.getElementById('privacy-banner').hidden,false);
    assert.equal(reads.includes(PANELS),false);
  }
  {
    const {doc,api}=setup({version:1,preferences:true,decidedAt:Date.now()});
    assert.equal(doc.getElementById('privacy-banner').hidden,true);
    assert.deepEqual(Array.from(api.readPanels()),['queue']);
  }
  {
    const {doc,api}=setup(null,true);click(doc,'[data-privacy-accept]');
    assert.equal(api.preferencesAllowed(),true);assert.equal(api.savePanels(['stats']),false);
    assert.match(doc.getElementById('privacy-status').textContent,/this visit/);
    click(doc,'.privacy-footer-button');click(doc,'#privacy-dialog [data-privacy-reject]');
    assert.equal(api.preferencesAllowed(),false);
  }
  // Exercise the existing account preference flow with optional storage rejected.
  {
    const {win,doc,api}=setup();click(doc,'[data-privacy-reject]');
    doc.body.insertAdjacentHTML('beforeend','<form id="panel_prefs"><input type="checkbox" data-panel="buildings" checked><input type="checkbox" data-panel="stats"></form><p id="panels_status"></p><div id="panel-buildings"></div><div id="panel-stats"></div>');
    win.eval("const $=id=>document.getElementById(id),PANEL_ORDER=['buildings','stats'],ROLE_PANELS={};const signedInAccount={email:'person@example.test'},accountCSRF='test-csrf';let accountRegistrations=[],panelsCustomized=false;"+
      source('templates/index.html').split('function defaultPanels(){')[1].split("if ($('panel_prefs'))")[0].replace(/^/,'function defaultPanels(){'));
    let call;
    win.fetch=async (url,options)=>{call={url,options};return {ok:true};};
    await win.savePanels();
    assert.equal(api.preferencesAllowed(),false);assert.equal(call.url,'/api/account/panels');
    assert.equal(call.options.headers['X-CSRF-Token'],'test-csrf');
    assert.match(doc.getElementById('panels_status').textContent,/Saved to your account/);
    win.fetch=async()=>{throw new Error('offline');};await win.savePanels();
    assert.match(doc.getElementById('panels_status').textContent,/this visit/);
    assert.equal(win.localStorage.getItem(PANELS),null);
  }
  // Form submits, safe messages, retries, and no accidental heat-alert signup.
  {
    const section=source('templates/index.html').match(/<section class="card newsletter-card"[\s\S]*?<\/section>/)[0];
    const dom=new JSDOM(section,{url:'https://heatahead.test',runScripts:'outside-only'}),win=dom.window;
    windows.push(win);const doc=win.document,form=doc.getElementById('newsletter-form');
    let payload,mode='success';
    win.fetch=async (url,options)=>{
      assert.equal(url,'/api/newsletter/subscribe');payload=JSON.parse(options.body);
      if(mode==='offline')throw new Error('offline');
      return {ok:mode==='success',json:async()=>mode==='success'?{message:'Check your inbox to confirm.'}:{error:'<img src=x onerror=alert(1)> unavailable'}};
    };
    win.eval(source('static/newsletter.js'));
    function submit(){
      form.elements.namedItem('email').value='person@example.test';form.elements.namedItem('name').value=' Em ';
      form.dispatchEvent(new win.Event('submit',{bubbles:true,cancelable:true}));
      assert.equal(form.querySelector('button').disabled,true);
    }
    submit();await tick();
    assert.deepEqual(payload,{name:'Em',email:'person@example.test',website:'',consent:true});
    assert.match(doc.getElementById('newsletter-status').textContent,/confirm/);
    assert.equal(form.querySelector('button').disabled,false);assert.equal(form.elements.namedItem('email').value,'');
    mode='error';submit();await tick();
    assert.equal(doc.getElementById('newsletter-status').querySelector('img'),null);
    assert.match(doc.getElementById('newsletter-status').textContent,/unavailable/);
    assert.equal(form.elements.namedItem('email').value,'person@example.test');
    mode='offline';submit();await tick();
    assert.match(doc.getElementById('newsletter-status').textContent,/couldn’t confirm/);
    assert.equal(form.querySelector('button').disabled,false);
  }
  console.log('PASS: consent defaults, accept/reject/settings, expiry, blocked storage, cross-tab withdrawal, keyboard focus, account saving, newsletter success/error/offline.');
}
run().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>windows.forEach(win=>win.close()));
