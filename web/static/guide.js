/* Local help search and chat. No dependency, storage, or conversation persistence. */
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
  const STOP=new Set('a an and are as at be can could do does for from get go how i in is it me my of on or our please the there this that these those to us want what when where which who why will with would you your also about just really rlly pls plz need help tell know like stuff thing things some kind kinda bit im u ur so wanna see show'.split(' '));
  const DIRECT=new Set('heatahead bbl map borough neighborhood hexagon hexagons risk probability calibration reliability unranked login signup google privacy alerts alert subscribe unsubscribe notifications remember autologin landlord owner agent draft inspector inspectors queue csv replay monitor satellite imagery footprints newsletter cookies'.split(' '));
  const ALIASES={buildings:'building',properties:'building',property:'building',addresses:'address',
    hexagons:'hexagon',hexagonal:'hexagon',colours:'color',colour:'color',colors:'color',colored:'color',coloured:'color',
    taller:'height',tallest:'height',tall:'height',heights:'height',columns:'column',
    complaints:'complaint',reports:'report',photos:'photo',pictures:'photo',picture:'photo',pic:'photo',pics:'photo',
    notifications:'alert',notification:'alert',alerts:'alert',notify:'alert',warnings:'alert',warning:'alert',
    emails:'email',mail:'email',newsletters:'newsletter',updates:'update',subscriptions:'subscription',
    signin:'login',logged:'login',logging:'login',log:'login',signing:'login',
    scores:'risk',score:'risk',chance:'risk',chances:'risk',likelihood:'risk',probability:'risk',percentage:'risk',
    accuracy:'accurate',reliable:'reliability',owners:'owner',landlords:'landlord',agents:'agent',
    cookies:'cookie',trackers:'tracking',inspectors:'inspector',inspections:'inspection',
    boroughs:'borough',neighbourhood:'neighborhood',neighbourhoods:'neighborhood',neighborhoods:'neighborhood'};
  const INDEX=new WeakMap();
  const canonical=word=>ALIASES[word]||word;
  function normalize(value){return String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/e-mail/g,'email').replace(/['’]/g,'').replace(/[^a-z0-9]+/g,' ').trim();}
  function tokens(value){return [...new Set(normalize(value).split(' ').filter(w=>w&&!STOP.has(w)))];}
  function extractBBL(value){
    const text=String(value||'').trim();
    const found=/^[1-5]\d{9}$/.exec(text)||/\bbbl\s*[:#]?\s*([1-5]\d{9})\b/i.exec(text);
    return found?(found[1]||found[0]):null;
  }
  function privateQuestion(value){
    const text=String(value||''),redacted=text.replace(/\b[1-5]\d{9}\b/g,'building');
    return /[^\s@]+@[^\s@]+\.[^\s@]+/.test(text)||/(?:\d[\s().+-]*){7,}/.test(redacted)||
      /\b(?:apt|apartment|unit|suite)\s*#?\s*\d/i.test(text)||
      /\b(?:password|client.secret|api.key)\s*(?:is|:|=)/i.test(text)||
      /\b(?:my phone|my number)\b.*\d{3}/i.test(text);
  }
  function exactRank(question,items){
    const q=' '+normalize(question)+' ',words=tokens(question);
    return items.map(item=>{
      let score=0,hits=0;
      for(const term of [item.question,...item.terms]){
        const phrase=normalize(term);if(phrase&&q.includes(' '+phrase+' '))score+=6+phrase.split(' ').length;
      }
      for(const keyword of item.keywords)if(words.includes(keyword)){score+=2;hits++;}
      return {item,score,hits};
    }).sort((a,b)=>b.score-a.score||b.hits-a.hits);
  }
  // Bounded Damerau-Levenshtein permits a nearby missing letter or transposition.
  function distance(a,b,limit){
    if(Math.abs(a.length-b.length)>limit)return limit+1;
    let older=null,previous=Array.from({length:b.length+1},(_,i)=>i);
    for(let i=1;i<=a.length;i++){
      const row=[i];let minimum=i;
      for(let j=1;j<=b.length;j++){
        row[j]=Math.min(previous[j]+1,row[j-1]+1,previous[j-1]+(a[i-1]===b[j-1]?0:1));
        if(older&&i>1&&j>1&&a[i-1]===b[j-2]&&a[i-2]===b[j-1])row[j]=Math.min(row[j],older[j-2]+1);
        minimum=Math.min(minimum,row[j]);
      }
      if(minimum>limit)return limit+1;
      older=previous;previous=row;
    }
    return previous[b.length];
  }
  function index(items){
    if(INDEX.has(items))return INDEX.get(items);
    const vocabulary=new Set(Object.keys(ALIASES)),frequency=new Map();
    const entries=items.map(item=>{
      const raw=tokens([item.question,...item.terms,...item.keywords].join(' '));raw.forEach(w=>vocabulary.add(w));
      const all=new Set(raw.map(canonical)),keywords=new Set([...item.keywords.flatMap(tokens),...tokens(item.question)].map(canonical));
      all.forEach(w=>frequency.set(w,(frequency.get(w)||0)+1));
      return {item,all,keywords};
    });
    const result={entries,vocabulary,frequency};INDEX.set(items,result);return result;
  }
  function queryWords(question,lookup){
    return tokens(question).map(word=>{
      if(lookup.vocabulary.has(word))return {values:[canonical(word)],fuzzy:false};
      let best=3,values=[];
      if(word.length===3)values=[...lookup.vocabulary].filter(w=>w.length===4&&w.startsWith(word)).map(canonical);
      if(word.length>=4)for(const candidate of lookup.vocabulary){
        if(candidate.length<4)continue;
        const limit=Math.min(word.length,candidate.length)>=7?2:1;
        if(Math.abs(word.length-candidate.length)>limit)continue;
        const d=distance(word,candidate,limit);
        if(d<=limit&&d<=best){if(d<best){best=d;values=[];}values.push(canonical(candidate));}
      }
      return {values:values.length?[...new Set(values)]:[canonical(word)],fuzzy:!!values.length};
    });
  }
  function rank(question,items){
    const lookup=index(items),words=queryWords(question,lookup),exact=new Map(exactRank(question,items).map(r=>[r.item.id,r]));
    return lookup.entries.map(entry=>{
      const base=exact.get(entry.item.id);let score=base.score,hits=0,covered=0,fuzzyHits=0;
      for(const word of words){
        if(word.values.some(w=>entry.all.has(w)))covered++;
        const matches=word.values.filter(w=>entry.keywords.has(w));
        if(!matches.length)continue;
        hits++;if(word.fuzzy)fuzzyHits++;
        const rarity=Math.max(...matches.map(w=>1+Math.log((items.length+1)/(1+(lookup.frequency.get(w)||0)))));
        score+=(word.fuzzy?1.5:2)*rarity;
      }
      const coverage=words.length?covered/words.length:0;
      return {item:entry.item,score,hits,coverage,fuzzyHits,corrected:words.some(w=>w.fuzzy)};
    }).sort((a,b)=>b.score-a.score||b.coverage-a.coverage||b.hits-a.hits);
  }
  function directMatch(question,items,previous){
    const normalized=normalize(question);
    if(/\b(newsletter|project updates?|project emails?)\b/.test(normalized))return items.find(i=>i.id==='newsletter');
    if(/\b(cookies?|tracking)\b/.test(normalized))return items.find(i=>i.id==='cookies');
    if(/\b(?:contact|email|message|reach|talk to)\s+(?:you|the team|your team|heatahead)\b/.test(normalized))return items.find(i=>i.id==='team-contact');
    if(/\b(no hexagons?|without hexagons?|missing hexagons?|no colored overlay|no coloured overlay|no color|no colour|blank areas?|empty areas?|uncolored buildings?|uncoloured buildings?|gray buildings?|grey buildings?|gaps on the map|gaps in the map)\b/.test(normalized))return items.find(i=>i.id==='unranked');
    if(/\b(height|heights|tall|taller|tallest)\b/.test(normalized))return items.find(i=>i.id==='heights');
    if(/\b(color|colors|colour|colours|blue|gradient|legend)\b/.test(normalized))return items.find(i=>i.id==='colors');
    if(/\b(?:stop|remove|delete|cancel|disable)\b.*\b(?:alerts?|notifications?|emails?|registration|building)\b|\b(?:alerts?|notifications?)\b.*\boff\b|\bunsubscribe\b/.test(normalized))return items.find(i=>i.id==='remove-alerts');
    if(extractBBL(question)&&/^(?:bbl\s*[:#]?\s*)?[1-5]\d{9}$/i.test(question.trim()))return items.find(i=>i.id==='look-up');
    if(/^(and |what about |how do i do that|where do i do that|tell me more|go there|open it)/.test(normalized)&&tokens(normalized).length<=3){
      const best=exactRank(question,items)[0];
      if((!best||best.score<6)&&previous)return items.find(i=>i.id===previous);
    }
    const best=exactRank(question,items)[0];
    const unique=best&&tokens(question).some(word=>DIRECT.has(word)&&best.item.keywords.includes(word)&&items.filter(i=>i.keywords.includes(word)).length===1);
    return best&&(best.score>=6||best.hits>=2||unique)?best.item:null;
  }
  function interpret(question,items,previous){
    const normalized=normalize(question),byId=new Map(items.map(i=>[i.id,i]));
    const result=(answer=null,ids=[])=>({answer,suggestions:ids.map(id=>byId.get(id)).filter(Boolean)});
    if(!normalized||privateQuestion(question))return result();
    if(/\b(gas leak|smell gas|carbon monoxide|co alarm|911|fire)\b/.test(normalized))return result(byId.get('emergency'));
    if(/\b(no heat|no hot water|heat is out|heat stopped|heat not working|heat died|heating is broken|heat failed|311)\b/.test(normalized))return result(byId.get('no-heat'));
    const exact=items.find(item=>normalize(item.question)===normalized);if(exact)return result(exact);
    const rawWords=tokens(question),words=rawWords.map(canonical);
    const meaning=queryWords(question,index(items)).flatMap(word=>word.values),has=word=>meaning.includes(word);
    const newsletter=/\b(newsletter|project updates?|project emails?)\b/.test(normalized);
    if(!newsletter&&!/\b(heat|buildings?|cold)\b/.test(normalized)&&
      (has('unsubscribe')||(/\b(stop|cancel|disable)\b/.test(normalized)&&has('email'))))return result(null,['remove-alerts','newsletter']);
    if(words.length===1&&has('email'))return result(null,['alerts','newsletter','sign-in','draft-message']);
    if(words.length===1&&has('subscribe'))return result(null,['alerts','newsletter']);
    if(words.length===1&&has('risk'))return result(null,['winter-risk','cold-day','calibration']);
    if(words.length===1&&['contact','message'].some(has))return result(null,['team-contact','landlord','draft-message']);
    if(/\b(height|heights|tall|taller)\b/.test(normalized)&&/\b(colou?rs?|blue)\b/.test(normalized))return result(null,['heights','colors']);
    const ranked=rank(question,items),direct=directMatch(question,items,previous);
    if(direct&&!ranked[0]?.corrected){
      const strength=ranked.find(r=>r.item.id===direct.id)?.score||0;
      const alternatives=ranked.filter(r=>r.hits&&r.coverage>=.5&&r.score>=strength*.75).slice(0,3);
      if(strength<20&&/\b(and|or|versus|vs)\b/.test(normalized)&&alternatives.length>1)return result(null,alternatives.map(r=>r.item.id));
      return result(direct);
    }
    const candidates=ranked.filter(r=>r.score>=1.2&&r.hits>0&&
      (r.coverage>=.65||(r.coverage>=.4&&r.hits>=2))).slice(0,3);
    return result(null,candidates.map(r=>r.item.id));
  }
  function match(question,items,previous){return interpret(question,items,previous).answer;}
  function safeLink(href){
    if(typeof href!=='string'||/[\\\u0000-\u0020]/.test(href))return false;
    try{
      const u=new URL(href,'https://heatahead.invalid');
      if(u.origin==='https://heatahead.invalid')return href.startsWith('/')&&!href.startsWith('//')&&['/','/building','/map','/monitor','/learn-more','/contact','/privacy','/api/queue.csv'].includes(u.pathname);
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
    let content;try{content=JSON.parse(bootstrap.textContent);if(!Array.isArray(content.items))return;}catch{return;}
    if(!['hg-dialog','hg-chat','hg-browser','hg-tab-chat','hg-tab-browse','hg-search','hg-category','hg-count','hg-empty','hg-input','hg-log','hg-status','hg-form','hg-privacy','hg-intro','hg-send','hg-close','hg-clear'].every(id=>$(id)))return;
    bootstrap.dataset.ready='1';
    const items=content.items,byId=new Map(items.map(i=>[i.id,i]));
    const panel=$('hg-dialog'),launcher=$('hg-launcher'),input=$('hg-input'),log=$('hg-log'),status=$('hg-status');
    let previous=null,bbl=null,pending=null,version=0,returnFocus=launcher;
    const el=(tag,cls,text)=>{const node=doc.createElement(tag);if(cls)node.className=cls;if(text)node.textContent=text;return node;};
    function currentBBL(){
      const selected=win._bbl||new URLSearchParams(win.location.search).get('bbl');
      return /^[1-5]\d{9}$/.test(String(selected||''))?String(selected):null;
    }
    function scroll(){log.scrollTop=log.scrollHeight;}
    function view(name,focus=false){
      const browsing=name==='browse';if(browsing)cancel();
      $('hg-chat').hidden=browsing;log.hidden=browsing;$('hg-browser').hidden=!browsing;
      $('hg-form').hidden=browsing;$('hg-privacy').hidden=browsing;$('hg-intro').hidden=browsing;
      for(const id of ['chat','browse']){
        const active=id===name,tab=$('hg-tab-'+id);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
      }
      if(focus)(browsing?$('hg-search'):input).focus();
    }
    function bubble(speaker,text){
      const node=el('div','hg-message'+(speaker==='You'?' hg-user':''));
      node.append(el('span','hg-speaker',speaker),el('p','',text));log.append(node);
      while(log.children.length>24)log.firstElementChild.remove();scroll();return node;
    }
    function topicButton(item,handler){
      const button=el('button','',item.question);button.type='button';button.dataset.guideQuestion=item.id;
      button.addEventListener('click',handler||(()=>ask(item.question,item)));return button;
    }
    function links(node,actions,source=false){
      const block=el('div',source?'hg-sources':'hg-actions');
      for(const action of actions){
        const href=contextualLink(action.href,bbl||currentBBL());if(!href)continue;
        const url=new URL(href,'https://heatahead.invalid'),topic=byId.get(url.searchParams.get('help'));
        if(url.origin==='https://heatahead.invalid'&&topic){
          const button=topicButton(topic);button.textContent=action.label;block.append(button);continue;
        }
        const a=el('a','',action.label+(href.startsWith('https://')?' ↗':''));a.href=href;
        if(href.startsWith('https://')){a.target='_blank';a.rel='noopener noreferrer';}block.append(a);
      }
      if(block.children.length)node.append(block);
    }
    function follow(node,ids){
      const block=el('div','hg-follow');
      ids.forEach(id=>{if(byId.has(id))block.append(topicButton(byId.get(id)));});
      if(block.children.length)node.append(block);scroll();
    }
    function answer(item){
      previous=item.id;const node=bubble('HeatAhead guide',item.answer);
      links(node,item.links);if(item.sources.length)links(node,item.sources,true);follow(node,item.follow.slice(0,3));status.textContent='';
    }
    function welcome(){
      const node=bubble('HeatAhead guide','What would you like help with? Ask below, or browse all the help questions.');
      follow(node,['look-up','alerts','heights','no-heat']);
    }
    function suggest(options,usedAI=false){
      const text=options.length===1?'Did you mean this question?': 'Did you mean one of these? Choose the closest question.';
      const node=bubble('HeatAhead guide',text);node.classList.add('hg-suggestion');
      follow(node,options.map(i=>i.id));
      const browse=el('button','hg-browse-more','Browse all questions');browse.type='button';
      browse.addEventListener('click',()=>view('browse',true));node.append(browse);scroll();
      status.textContent=usedAI?'AI helped suggest a help topic. You choose the answer.':'';
      if(!panel.hidden&&panel.contains(doc.activeElement))node.querySelector('[data-guide-question]')?.focus();
    }
    function fallback(){
      const node=bubble('HeatAhead guide',"I couldn't find a close match. I can help with buildings, the map, alerts and using HeatAhead.");
      const browse=el('button','hg-browse-more','Browse help questions');browse.type='button';browse.addEventListener('click',()=>view('browse',true));node.append(browse);
      links(node,[{label:'Contact the team',href:'/contact'},{label:'How HeatAhead works',href:'/learn-more'}]);scroll();
    }
    function busy(value){$('hg-send').disabled=value;}
    function cancel(){version++;if(pending)pending.abort();pending=null;busy(false);status.textContent='';}
    async function ask(raw,selected=null){
      const question=String(raw||'').trim();if(!question)return;
      if(question.length>400||privateQuestion(question)){
        status.textContent='Keep questions under 400 characters and leave out contact details, passwords and apartment numbers.';
        input.value='';input.focus();return;
      }
      cancel();view('chat');const ticket=version;
      bbl=extractBBL(question)||currentBBL()||bbl;bubble('You',question);input.value='';
      if(/^(hi|hello|hey|help|help me|thanks|thank you)$/.test(normalize(question))){welcome();input.focus();return;}
      const understood=selected?{answer:selected,suggestions:[]}:interpret(question,items,previous);
      if(understood.answer){answer(understood.answer);input.focus();return;}
      if(understood.suggestions.length){suggest(understood.suggestions);return;}
      if(!content.ai_enabled){fallback();input.focus();return;}
      pending=new AbortController();const controller=pending,timer=win.setTimeout(()=>controller.abort(),7000);busy(true);status.textContent='Looking for a matching question…';
      try{
        const response=await win.fetch('/api/guide/ask',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({question,previous_topic:previous}),signal:controller.signal});
        const result=response.ok?await response.json():null;if(ticket!==version)return;
        if(result&&result.mode==='ai'&&byId.has(result.topic))suggest([byId.get(result.topic)],true);
        else{fallback();status.textContent='You can still browse every help question.';}
      }catch{if(ticket===version){fallback();status.textContent="Couldn't connect. The help questions still work here.";}}
      finally{win.clearTimeout(timer);if(ticket===version){pending=null;busy(false);}}
    }
    function filterQuestions(){
      const query=$('hg-search').value.trim(),category=$('hg-category').value;
      const candidates=query&&tokens(query).length?rank(query,items).filter(r=>r.hits&&r.score>=1.2&&r.coverage>=.4):null;
      const allowed=candidates?new Set(candidates.map(r=>r.item.id)):null;let count=0;
      doc.querySelectorAll('#hg-browser [data-guide-question]').forEach(button=>{
        const item=byId.get(button.dataset.guideQuestion);button.hidden=!!(!item||(category!=='all'&&item.category!==category)||(allowed&&!allowed.has(item.id)));
        if(!button.hidden)count++;
      });
      doc.querySelectorAll('[data-guide-category]').forEach(group=>{group.hidden=![...group.querySelectorAll('[data-guide-question]')].some(button=>!button.hidden);});
      $('hg-count').textContent=count+' '+(count===1?'question':'questions');$('hg-empty').hidden=count!==0;
    }
    function open(mode='chat',topic=null){
      if(panel.hidden)returnFocus=doc.activeElement||launcher;panel.hidden=false;launcher.setAttribute('aria-expanded','true');
      win.HeatAheadPrivacy?.setHelpOpen?.(true);
      if(topic&&byId.has(topic)){ask(byId.get(topic).question,byId.get(topic));return;}
      if(!log.children.length)welcome();view(mode,true);
    }
    function close(){
      panel.hidden=true;launcher.setAttribute('aria-expanded','false');
      win.HeatAheadPrivacy?.setHelpOpen?.(false);
      const target=returnFocus&&returnFocus!==doc.body&&returnFocus.isConnected&&!returnFocus.closest('[hidden]')?returnFocus:launcher;
      target.focus({preventScroll:true});
    }
    launcher.hidden=false;launcher.addEventListener('click',()=>panel.hidden?open():close());$('hg-close').addEventListener('click',close);
    panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();close();}});
    $('hg-form').addEventListener('submit',event=>{event.preventDefault();ask(input.value);});
    $('hg-clear').addEventListener('click',()=>{cancel();previous=null;bbl=null;log.replaceChildren();input.value='';welcome();view('chat',true);});
    for(const name of ['chat','browse']){
      const tab=$('hg-tab-'+name);tab.addEventListener('click',()=>view(name,true));
      tab.addEventListener('keydown',event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        event.preventDefault();const next=event.key==='Home'?'chat':event.key==='End'?'browse':name==='chat'?'browse':'chat';
        view(next);$('hg-tab-'+next).focus();
      });
    }
    $('hg-search').addEventListener('input',filterQuestions);$('hg-category').addEventListener('change',filterQuestions);
    doc.querySelectorAll('#hg-browser [data-guide-question]').forEach(button=>button.addEventListener('click',()=>{
      const item=byId.get(button.dataset.guideQuestion);if(item)ask(item.question,item);
    }));filterQuestions();
    doc.querySelectorAll('[data-open-guide],[data-guide-topic]').forEach(trigger=>{
      trigger.hidden=false;trigger.addEventListener('click',event=>{
        if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
        event.preventDefault();open(trigger.hasAttribute('data-guide-browse')?'browse':'chat',trigger.dataset.guideTopic||null);
      });
    });
    if(content.ai_enabled)$('hg-privacy').textContent="Unrecognized questions may use AI to suggest a help topic. Please leave out passwords, contact details and apartment numbers.";
    function openLinkedHelp(){
      const requested=new URLSearchParams(win.location.search).get('help');if(!requested)return;
      let legacy;try{legacy=decodeURIComponent(win.location.hash.slice(1));}catch{legacy='';}
      open('browse',byId.has(requested)?requested:requested==='1'&&byId.has(legacy)?legacy:null);
    }
    openLinkedHelp();
  }
  return {normalize,tokens,extractBBL,privateQuestion,rank,match,interpret,safeLink,contextualLink,init};
});
