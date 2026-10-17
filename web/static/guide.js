/* Shared, dependency-free guide + FAQ search. No localStorage or chat persistence. */
(function(root,factory){
  'use strict';
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root.document){
    if(root.document.readyState==='loading')root.document.addEventListener('DOMContentLoaded',()=>api.init(root),{once:true});
    else api.init(root);
  }
})(typeof window==='undefined'?globalThis:window,function(){
  'use strict';
  const STOP=new Set('a an and are as at be can could do does for from get go how i in is it me my of on or our please the there this to us want what when where which who why will with would you your'.split(' '));
  const DIRECT=new Set('heatahead bbl map borough neighborhood hexagon hexagons risk probability calibration reliability unranked login signup google privacy alerts alert subscribe unsubscribe notifications remember autologin landlord owner agent draft inspector inspectors queue csv replay monitor satellite imagery footprints'.split(' '));
  function normalize(value){return String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/['’]/g,'').replace(/[^a-z0-9]+/g,' ').trim();}
  function tokens(value){return [...new Set(normalize(value).split(' ').filter(w=>w&&!STOP.has(w)))];}
  function extractBBL(value){
    const text=String(value||'').trim();
    const match=/^[1-5]\d{9}$/.exec(text)||/\bbbl\s*[:#]?\s*([1-5]\d{9})\b/i.exec(text);
    return match?(match[1]||match[0]):null;
  }
  function privateQuestion(value){
    const text=String(value||'');
    const redacted=text.replace(/\b[1-5]\d{9}\b/g,'building');
    return /[^\s@]+@[^\s@]+\.[^\s@]+/.test(text)||/(?:\d[\s().+-]*){7,}/.test(redacted)||
      /\b(?:apt|apartment|unit|suite)\s*#?\s*\d/i.test(text)||
      /\b(?:password|client.secret|api.key)\s*(?:is|:|=)/i.test(text)||
      /\b(?:my phone|my number)\b.*\d{3}/i.test(text);
  }
  function rank(question,items){
    const q=' '+normalize(question)+' ',words=tokens(question);
    return items.map(item=>{
      let score=0,hits=0;
      for(const term of [item.question,...item.terms]){const phrase=normalize(term);if(phrase&&q.includes(' '+phrase+' '))score+=6+phrase.split(' ').length;}
      for(const keyword of item.keywords){if(words.includes(keyword)){score+=2;hits++;}}
      return {item,score,hits};
    }).sort((a,b)=>b.score-a.score||b.hits-a.hits);
  }
  function match(question,items,previous){
    const normalized=normalize(question);
    if(/\b(gas leak|smell gas|carbon monoxide|co alarm|911|fire)\b/.test(normalized))return items.find(i=>i.id==='emergency');
    if(/\b(no heat|no hot water|heat is out|heat stopped|heat not working|heat died|heating is broken|heat failed|311)\b/.test(normalized))return items.find(i=>i.id==='no-heat');
    if(/\b(no hexagons?|without hexagons?|missing hexagons?|no colored overlay|no coloured overlay|no color|no colour|blank areas?|empty areas?|uncolored buildings?|uncoloured buildings?|gray buildings?|grey buildings?|gaps on the map|gaps in the map)\b/.test(normalized))return items.find(i=>i.id==='unranked');
    if(/\b(height|heights|tall|taller|tallest)\b/.test(normalized))return items.find(i=>i.id==='heights');
    if(/\b(color|colors|colour|colours|blue|gradient|legend)\b/.test(normalized))return items.find(i=>i.id==='colors');
    if(/\b(?:stop|remove|delete|cancel|disable)\b.*\b(?:alerts?|notifications?|emails?|registration|building)\b|\b(?:alerts?|notifications?)\b.*\boff\b|\bunsubscribe\b/.test(normalized))return items.find(i=>i.id==='remove-alerts');
    if(extractBBL(question)&&/^(?:bbl\s*[:#]?\s*)?[1-5]\d{9}$/i.test(question.trim()))return items.find(i=>i.id==='look-up');
    if(/^(and |what about |how do i do that|where do i do that|tell me more|go there|open it)/.test(normalized)&&tokens(normalized).length<=3){
      const direct=rank(question,items)[0];
      if((!direct||direct.score<6)&&previous)return items.find(i=>i.id===previous);
    }
    const best=rank(question,items)[0];
    const unique=best&&tokens(question).some(word=>DIRECT.has(word)&&best.item.keywords.includes(word)&&items.filter(i=>i.keywords.includes(word)).length===1);
    return best&&(best.score>=6||best.hits>=2||unique)?best.item:null;
  }
  function safeLink(href){
    if(typeof href!=='string'||/[\\\u0000-\u0020]/.test(href))return false;
    try{
      const u=new URL(href,'https://heatahead.invalid');
      if(u.origin==='https://heatahead.invalid')return href.startsWith('/')&&!href.startsWith('//')&&['/','/building','/map','/monitor','/learn-more','/faq','/api/queue.csv'].includes(u.pathname);
      return u.protocol==='https:'&&!u.username&&!u.password&&['www.nyc.gov','portal.311.nyc.gov','data.cityofnewyork.us','open-meteo.com'].includes(u.hostname);
    }catch{return false;}
  }
  function contextualLink(href,bbl){
    if(!safeLink(href))return null;
    if(/^\/building(?:[?#]|$)/.test(href)&&/^[1-5]\d{9}$/.test(String(bbl||''))){
      const url=new URL(href,'https://heatahead.invalid');url.searchParams.set('bbl',bbl);
      return url.pathname+url.search+url.hash;
    }
    return href;
  }
  function init(win){
    const doc=win.document,$=id=>doc.getElementById(id),bootstrap=$('hg-content');
    if(!bootstrap||!$('hg-launcher')||bootstrap.dataset.ready)return;
    let content;
    try{content=JSON.parse(bootstrap.textContent);if(!Array.isArray(content.items))return;}catch{return;}
    bootstrap.dataset.ready='1';
    const items=content.items,byId=new Map(items.map(i=>[i.id,i]));
    const panel=$('hg-dialog'),launcher=$('hg-launcher'),input=$('hg-input'),log=$('hg-log'),status=$('hg-status');
    let previous=null,bbl=null,pending=null,version=0,returnFocus=launcher;
    const el=(tag,cls,text)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
    function currentBBL(){
      const selected=win._bbl||new URLSearchParams(win.location.search).get('bbl');
      return /^[1-5]\d{9}$/.test(String(selected||''))?String(selected):null;
    }
    function scroll(){log.scrollTop=log.scrollHeight;}
    function bubble(speaker,text){
      const n=el('div','hg-message'+(speaker==='You'?' hg-user':''));
      n.append(el('span','hg-speaker',speaker),el('p','',text));log.append(n);
      // Keep memory/DOM bounded during a long visit. Nothing is saved between pages.
      while(log.children.length>24)log.firstElementChild.remove();
      scroll();return n;
    }
    function links(node,actions,source=false){
      const block=el('div',source?'hg-sources':'hg-actions');
      for(const action of actions){
        const href=contextualLink(action.href,bbl||currentBBL());if(!href)continue;
        const a=el('a','',action.label+(href.startsWith('https://')?' ↗':''));a.href=href;
        if(href.startsWith('https://')){a.target='_blank';a.rel='noopener noreferrer';}
        block.append(a);
      }
      if(block.children.length)node.append(block);
    }
    function follow(node,ids){
      const block=el('div','hg-follow');
      for(const id of ids){const item=byId.get(id);if(!item)continue;
        const button=el('button','',item.question);button.type='button';
        button.addEventListener('click',()=>ask(item.question,item));block.append(button);
      }
      node.append(block);scroll();
    }
    function answer(item,usedAI=false){
      previous=item.id;
      const node=bubble('HeatAhead guide',item.answer);
      links(node,item.links);if(item.sources.length)links(node,item.sources,true);
      follow(node,item.follow.slice(0,3));
      status.textContent=usedAI?'AI matched your question to this published FAQ.':'';
    }
    function welcome(){
      const node=bubble('HeatAhead guide','What would you like to do? I can explain the site and give you a shortcut to the right page.');
      follow(node,['look-up','alerts','heights','no-heat']);
    }
    function fallback(question){
      const node=bubble('HeatAhead guide','I could not confidently match that question. Try a short question about a building, the map, alerts or inspections, or browse the FAQs.');
      links(node,[{label:'Browse all FAQs',href:'/faq'},{label:'See how HeatAhead works',href:'/learn-more'}]);
      follow(node,rank(question,items).filter(r=>r.score>0).slice(0,2).map(r=>r.item.id));scroll();
    }
    function busy(value){$('hg-send').disabled=value;}
    async function ask(raw,selected=null){
      const question=String(raw||'').trim();if(!question)return;
      if(question.length>400||privateQuestion(question)){
        status.textContent='Use a short general question without passwords, contact information or unit details.';
        input.value='';input.focus();return;
      }
      const ticket=++version;if(pending)pending.abort();pending=null;busy(false);status.textContent='';
      bbl=extractBBL(question)||currentBBL()||bbl;
      bubble('You',question);input.value='';
      if(/^(hi|hello|hey|help|help me|thanks|thank you)$/.test(normalize(question))){welcome();return;}
      const item=selected||match(question,items,previous);
      if(item){answer(item);return;}
      if(!content.ai_enabled){fallback(question);return;}
      pending=new AbortController();const controller=pending;
      const timer=win.setTimeout(()=>controller.abort(),7000);busy(true);
      status.textContent='Finding the closest help topic…';
      try{
        const response=await win.fetch('/api/guide/ask',{method:'POST',credentials:'same-origin',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({question,previous_topic:previous}),signal:controller.signal});
        const result=response.ok?await response.json():null;
        if(ticket!==version)return;
        if(result&&result.mode==='ai'&&byId.has(result.topic))answer(byId.get(result.topic),true);
        else{fallback(question);status.textContent='AI matching is unavailable. Common answers and links still work.';}
      }catch{if(ticket===version){fallback(question);status.textContent='Could not connect. Use the FAQs or one of the shortcuts.';}}
      finally{win.clearTimeout(timer);if(ticket===version){pending=null;busy(false);}}
    }
    function open(){
      returnFocus=doc.activeElement||launcher;panel.hidden=false;launcher.setAttribute('aria-expanded','true');
      if(!log.children.length)welcome();input.focus();
    }
    function close(){
      panel.hidden=true;launcher.setAttribute('aria-expanded','false');
      if(returnFocus&&returnFocus.isConnected)returnFocus.focus({preventScroll:true});
    }
    launcher.hidden=false;
    launcher.addEventListener('click',()=>panel.hidden?open():close());
    $('hg-close').addEventListener('click',close);
    panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();close();}});
    $('hg-form').addEventListener('submit',event=>{event.preventDefault();ask(input.value);});
    $('hg-clear').addEventListener('click',()=>{
      version++;if(pending)pending.abort();pending=null;busy(false);previous=null;bbl=null;
      log.replaceChildren();input.value='';status.textContent='';welcome();input.focus();
    });
    doc.querySelectorAll('[data-open-guide]').forEach(button=>{button.hidden=false;button.addEventListener('click',open);});
    if(content.ai_enabled)$('hg-privacy').textContent='Common answers stay on this device. Unfamiliar questions may use AI matching. Leave out personal and unit details.';
    setupFAQ(doc,items);
  }
  function setupFAQ(doc,items){
    const search=doc.getElementById('faq-search');if(!search)return;
    const tools=doc.querySelector('[data-faq-tools]'),nodes=[...doc.querySelectorAll('[data-faq-item]')];
    let category='all';
    function filter(){
      const words=tokens(search.value);let count=0;
      for(const node of nodes){
        const item=items.find(i=>i.id===node.id);if(!item)continue;
        const haystack=normalize([item.question,item.answer,...item.terms,...item.keywords].join(' '));
        node.hidden=!(category==='all'||item.category===category)||!words.every(word=>haystack.includes(word));
        if(!node.hidden)count++;
      }
      doc.querySelectorAll('[data-faq-group]').forEach(group=>{group.hidden=![...group.querySelectorAll('[data-faq-item]')].some(n=>!n.hidden);});
      doc.getElementById('faq-count').textContent=count+' '+(count===1?'answer':'answers')+' found';
      doc.getElementById('faq-empty').hidden=count!==0;
    }
    doc.querySelectorAll('[data-faq-category]').forEach(button=>{
      if(button.tagName!=='BUTTON')return;
      button.addEventListener('click',()=>{
        category=button.dataset.faqCategory;
        doc.querySelectorAll('button[data-faq-category]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));filter();
      });
    });
    search.addEventListener('input',filter);tools.hidden=false;filter();
    function reveal(){
      let id;try{id=decodeURIComponent(doc.defaultView.location.hash.slice(1));}catch{return;}
      const target=nodes.find(node=>node.id===id);if(!target)return;
      category='all';search.value='';
      doc.querySelectorAll('button[data-faq-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.faqCategory==='all')));
      filter();target.open=true;target.scrollIntoView({block:'start'});
    }
    doc.defaultView.addEventListener('hashchange',reveal);reveal();
  }
  return {normalize,tokens,extractBBL,privateQuestion,rank,match,safeLink,contextualLink,init,setupFAQ};
});
