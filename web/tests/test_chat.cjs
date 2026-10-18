/* Development-only: requires Python/Flask and jsdom@26. No real provider calls.
 * NODE_PATH=/tmp/heatahead-dom/node_modules node web/tests/test_chat.cjs
 */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process'),{JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'../..');
const {items}=require('../static/guide-content.json');
const source=fs.readFileSync(path.join(root,'web/static/guide.js'),'utf8');
const privacy=fs.readFileSync(path.join(root,'web/static/privacy.js'),'utf8');
const html=execFileSync(process.env.PYTHON||'python',['-c',[
  'import json',
  'from pathlib import Path',
  'from flask import Flask, render_template',
  'app=Flask("fixture",template_folder=str(Path("web/templates").resolve()))',
  'content=json.loads(Path("web/static/guide-content.json").read_text())',
  'with app.app_context(): print(render_template("_guide.html",guide_bootstrap={**content,"ai_enabled":False})+render_template("_privacy.html"))'
].join('\n')],{cwd:root,encoding:'utf8'});
const windows=[];
function setup(url='https://heatahead.test/building?bbl=3000410007',ai=false){
  const dom=new JSDOM('<!doctype html><body><a id="help-nav" href="/?help=1" data-open-guide data-guide-browse>Ask HeatAhead</a>'+html+'</body>',
    {url,runScripts:'outside-only'});
  const win=dom.window,doc=win.document;windows.push(win);
  if(ai){const data=doc.getElementById('hg-content');const content=JSON.parse(data.textContent);content.ai_enabled=true;data.textContent=JSON.stringify(content);}
  const calls=[];
  win.fetch=async(...args)=>{calls.push(args);throw new Error('No live network requests allowed');};
  // Load order matches the site: privacy API is ready before the deferred guide.
  win.eval(privacy);win.eval(source);doc.dispatchEvent(new win.Event('DOMContentLoaded'));
  return {win,doc,calls};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function ask(win,text){
  const doc=win.document;doc.getElementById('hg-input').value=text;
  doc.getElementById('hg-form').dispatchEvent(new win.Event('submit',{bubbles:true,cancelable:true}));
}
function click(doc,selector){const node=doc.querySelector(selector);assert.ok(node,selector);node.click();return node;}
function answer(doc){return doc.querySelector('#hg-log .hg-message:last-child');}

async function run(){
  {
    const {win,doc,calls}=setup();
    assert.equal(doc.getElementById('privacy-banner').hidden,false);
    const nav=doc.getElementById('help-nav');nav.focus();nav.click();
    assert.equal(doc.getElementById('hg-dialog').hidden,false);
    assert.equal(doc.getElementById('hg-browser').hidden,false);
    assert.equal(doc.querySelectorAll('#hg-browser [data-guide-question]').length,29);
    assert.equal(doc.getElementById('hg-count').textContent,'29 questions');
    assert.equal(doc.getElementById('privacy-banner').hidden,true,'Help does not get covered by an undecided cookie banner');
    assert.equal(win.HeatAheadPrivacy.preferencesAllowed(),false);
    assert.equal(win.location.pathname,'/building','Help stays on the current page');
    const search=doc.getElementById('hg-search');
    search.value='coloers';search.dispatchEvent(new win.Event('input'));
    assert.equal(doc.querySelector('#hg-browser [data-guide-question="colors"]').hidden,false);
    const category=doc.getElementById('hg-category');category.value='Accounts and alerts';category.dispatchEvent(new win.Event('change'));
    assert.equal(doc.getElementById('hg-empty').hidden,false);
    category.value='all';category.dispatchEvent(new win.Event('change'));search.value='email';search.dispatchEvent(new win.Event('input'));
    assert.equal(doc.querySelector('#hg-browser [data-guide-question="newsletter"]').hidden,false);
    search.value='';search.dispatchEvent(new win.Event('input'));
    click(doc,'#hg-browser [data-guide-question="look-up"]');
    assert.equal(doc.getElementById('hg-browser').hidden,true);
    assert.equal(doc.getElementById('hg-chat').hidden,false);
    assert.ok(answer(doc).textContent.includes(items.find(i=>i.id==='look-up').answer));
    assert.ok(answer(doc).querySelector('a[href="/building?bbl=3000410007"]'));
    click(doc,'#hg-tab-browse');
    doc.getElementById('hg-tab-browse').dispatchEvent(new win.KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true,cancelable:true}));
    assert.equal(doc.activeElement.id,'hg-tab-chat');
    assert.equal(doc.getElementById('hg-tab-chat').getAttribute('aria-selected'),'true');
    ask(win,'emial');
    assert.match(answer(doc).textContent,/Did you mean/);
    const options=[...answer(doc).querySelectorAll('[data-guide-question]')];
    assert.deepEqual(options.map(n=>n.dataset.guideQuestion),['alerts','newsletter','sign-in','draft-message']);
    assert.equal(doc.activeElement,options[0]);
    options.find(n=>n.dataset.guideQuestion==='newsletter').click();
    assert.ok(answer(doc).textContent.includes(items.find(i=>i.id==='newsletter').answer));
    ask(win,'tell me more');
    assert.ok(answer(doc).textContent.includes(items.find(i=>i.id==='newsletter').answer));
    ask(win,'stop emails');
    assert.deepEqual([...answer(doc).querySelectorAll('[data-guide-question]')].map(n=>n.dataset.guideQuestion),['remove-alerts','newsletter']);
    ask(win,'my email is person@example.test');
    assert.match(doc.getElementById('hg-status').textContent,/leave out contact/);
    assert.doesNotMatch(doc.getElementById('hg-log').textContent,/person@example/);
    ask(win,'<img src=x onerror=alert(1)>');
    assert.equal(doc.querySelector('#hg-log img'),null,'Visitor input is rendered as text');
    assert.ok(doc.getElementById('hg-log').textContent.includes('<img src=x onerror=alert(1)>'));
    ask(win,'write me a poem');
    assert.match(answer(doc).textContent,/couldn't find a close match/);
    ask(win,'my heat died and I need notifications');
    assert.ok(answer(doc).textContent.includes(items.find(i=>i.id==='no-heat').answer));
    assert.ok(answer(doc).querySelector('a[href^="https://portal.311.nyc.gov/"]'));
    ask(win,'why no color');
    click(doc,'#hg-log .hg-message:last-child .hg-actions [data-guide-question="no-heat"]');
    assert.ok(answer(doc).textContent.includes(items.find(i=>i.id==='no-heat').answer));
    for(let i=0;i<30;i++)ask(win,'map');
    assert.ok(doc.getElementById('hg-log').children.length<=24);
    assert.equal(calls.length,0,'Known questions, browsing and clarification never need a provider');
    click(doc,'#hg-clear');assert.equal(doc.getElementById('hg-log').children.length,1);
    doc.getElementById('hg-input').dispatchEvent(new win.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    assert.equal(doc.getElementById('hg-dialog').hidden,true);
    assert.equal(doc.activeElement,nav);
    assert.equal(doc.getElementById('privacy-banner').hidden,false);
    assert.equal(win.localStorage.getItem('heatahead_privacy'),null);
  }
  for(const url of ['https://heatahead.test/learn-more?help=heights','https://heatahead.test/learn-more?help=1#heights']){
    const {doc}=setup(url);
    assert.equal(doc.getElementById('hg-dialog').hidden,false);
    assert.ok(answer(doc).textContent.includes(items.find(i=>i.id==='heights').answer));
    assert.equal(doc.getElementById('privacy-banner').hidden,true);
    click(doc,'#hg-close');assert.equal(doc.activeElement.id,'hg-launcher');
  }
  {
    const {doc}=setup('https://heatahead.test/learn-more?help=1#not-a-topic');
    assert.equal(doc.getElementById('hg-browser').hidden,false);
  }
  {
    const {win,doc,calls}=setup('https://heatahead.test/?help=guide#reading-the-map');
    assert.equal(doc.getElementById('hg-guide').hidden,false);
    assert.equal(doc.getElementById('hg-guide-reading-the-map').open,true);
    assert.equal(doc.querySelectorAll('#hg-guide > details').length,5);
    assert.equal(doc.getElementById('privacy-banner').hidden,true);
    assert.equal(win.HeatAheadPrivacy.preferencesAllowed(),false);
    click(doc,'#hg-guide [data-guide-topic="unranked"]');
    assert.equal(doc.getElementById('hg-chat').hidden,false);
    assert.ok(answer(doc).textContent.includes(items.find(i=>i.id==='unranked').answer));
    ask(win,items.find(i=>i.id==='heights').question);
    const guideAction=[...answer(doc).querySelectorAll('.hg-actions button')].find(b=>!b.dataset.guideQuestion);
    assert.ok(guideAction,'Map explanation includes an in-place walkthrough action');
    guideAction.click();
    assert.equal(doc.getElementById('hg-guide').hidden,false);
    assert.equal(doc.getElementById('hg-guide-reading-the-map').open,true);
    assert.equal(win.location.pathname,'/');
    const tab=doc.getElementById('hg-tab-guide');
    tab.dispatchEvent(new win.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));
    assert.equal(doc.activeElement.id,'hg-tab-chat');
    doc.activeElement.dispatchEvent(new win.KeyboardEvent('keydown',{key:'End',bubbles:true,cancelable:true}));
    assert.equal(doc.activeElement.id,'hg-tab-guide');
    assert.equal(calls.length,0);
  }
  {
    const {win,doc,calls}=setup(undefined,true);click(doc,'#hg-launcher');
    ask(win,'email');assert.equal(calls.length,0,'Local ambiguity is shown immediately even with AI enabled');
    let release;
    win.fetch=(...args)=>{calls.push(args);return new Promise(resolve=>{release=resolve;});};
    ask(win,'please help with an unusual situation');
    assert.equal(doc.getElementById('hg-send').disabled,true);
    click(doc,'#hg-clear');
    release({ok:true,json:async()=>({topic:'heights',mode:'ai'})});await tick();
    assert.equal(doc.getElementById('hg-log').children.length,1,'Late provider response cannot restore a cleared conversation');
    win.fetch=async()=>({ok:true,json:async()=>({topic:'heights',mode:'ai'})});
    ask(win,'help with an unusual situation');await tick();
    assert.match(answer(doc).textContent,/Did you mean/);
    assert.equal(answer(doc).querySelector('[data-guide-question]').dataset.guideQuestion,'heights');
    assert.ok(!answer(doc).textContent.includes(items.find(i=>i.id==='heights').answer),'AI suggestions need a user choice');
    win.fetch=async()=>{throw new Error('offline');};ask(win,'another unusual situation');await tick();
    assert.match(doc.getElementById('hg-status').textContent,/Couldn't connect/);
    assert.equal(doc.getElementById('hg-send').disabled,false);
    click(doc,'#hg-tab-browse');assert.equal(doc.getElementById('hg-count').textContent,'29 questions');
    let late;
    win.fetch=()=>new Promise(resolve=>{late=resolve;});
    click(doc,'#hg-tab-chat');ask(win,'please help with an unusual situation');
    click(doc,'#hg-tab-guide');
    const before=doc.getElementById('hg-log').textContent;
    late({ok:true,json:async()=>({topic:'heights',mode:'ai'})});await tick();
    assert.equal(doc.getElementById('hg-log').textContent,before,'Opening the guide cancels pending AI suggestions');
    assert.equal(doc.getElementById('hg-guide').hidden,false);
  }
  console.log('PASS: real templates, all 29 help questions, typo search, categories, multiple choices, BBL links, keyboard tabs/focus, legacy FAQ fragments, no unsafe markup or private input, bounded chat, stale/offline AI and cookie-banner coexistence.');
}
run().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>windows.forEach(win=>win.close()));
