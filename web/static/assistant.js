(() => {
'use strict';
const $=id=>document.getElementById(id);
const NS='http://www.w3.org/2000/svg';
const status=$('ask-status'), submit=$('ask-submit');
let active=false, windowResult={};
function node(tag,text,parent){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(parent)parent.appendChild(e);return e;}
function svgNode(tag,attrs,parent){const e=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));parent.appendChild(e);return e;}
const num=v=>Number(v).toLocaleString('en-US',{maximumFractionDigits:2});
function pointLabel(p){
  return Number.isFinite(p.lower)&&Number.isFinite(p.upper)
    ? `${p.label}, ${num(p.lower)}–${num(p.upper)} (${num(p.value)})`
    : `${p.label}, ${num(p.value)}`;
}
function facts(r){
  const list=$('ask-facts');list.replaceChildren();const entries=[];
  const add=(text,source)=>{if(entries.length<5&&!entries.some(e=>e.text===text))entries.push({text,source});};
  for(const c of r.charts||[]){
    const points=(c.points||[]).filter(p=>Number.isFinite(p.value));
    const predicted=points.filter(p=>p.forecast), observed=points.filter(p=>!p.forecast);
    if(predicted.length){
      const peak=predicted.reduce((a,b)=>b.value>a.value?b:a);
      add(`Highest forecast: ${peak.label}, the range is ${num(peak.lower)}–${num(peak.upper)} (predicted value = ${num(peak.value)}) complaints.`,c.title);
      const total=predicted.reduce((n,p)=>n+p.value,0);
      add(`The ${predicted.length}-day point estimates total ${num(total)} complaints.`,c.title);
      add(`An average of ${num(total/predicted.length)} complaints per day is predicted.`,c.title);
      if(total>0&&predicted.length>1)add(`${peak.label} accounts for ${num(100*peak.value/total)}% of the predicted total.`,c.title);
      const first=predicted[0], last=predicted[predicted.length-1];
      if(predicted.length>1&&first.value>0){const change=100*(last.value/first.value-1);add(`The point estimate ${change>=0?'rises':'falls'} ${num(Math.abs(change))}% from ${first.label} to ${last.label}.`,c.title);}
    }else if(points.length){
      const peak=points.reduce((a,b)=>b.value>a.value?b:a);
      add(`${peak.label} has the highest displayed count: ${num(peak.value)} complaints.`,c.title);
      const total=points.reduce((n,p)=>n+p.value,0);
      add(`The ${points.length} displayed ${c.type==='bar'?'categories':'periods'} account for ${num(total)} reported complaints.`,c.title);
      if(total>0&&points.length>1)add(`${peak.label} represents ${num(100*peak.value/total)}% of the displayed total.`,c.title);
    }
    if(predicted.length&&observed.length){const last=observed[observed.length-1];add(`Latest history shown: ${last.label}, ${num(last.value)} complaints.`,c.title);}
  }

  for(const entry of entries){
    const li=node('li',undefined,list);
    const parts=entry.text.split(/(\d{4}-\d{2}-\d{2}|[+-]?\d[\d,]*(?:\.\d+)?%?)/g);
    parts.forEach((part,i)=>{if(part)node(i%2?'strong':'span',part,li);});
  }
  $('ask-facts-panel').hidden=!entries.length;
}
function chart(c){
  if(!Array.isArray(c.points)||!c.points.length)return;
  const points=c.points.filter(p=>Number.isFinite(p.value)&&p.value>=0).slice(0,130);
  if(!points.length)return;
  const card=node('section',undefined,$('ask-charts'));card.className='card ask-chart';node('h2',c.title,card);
  const svg=svgNode('svg',{viewBox:'0 0 860 320',role:'img'},card);const desc=svgNode('title',{},svg);desc.textContent=c.title;
  const left=65, top=20, bottom=260,width=765;
  const max=Math.max(1,...points.map(p=>Number.isFinite(p.upper)?Math.max(p.value,p.upper):p.value));
  const y=v=>bottom-(v/max)*(bottom-top), x=i=>left+(points.length===1?width/2:i*width/(points.length-1));
  for(let i=0;i<5;i++){const value=max*i/4;svgNode('line',{x1:left,y1:y(value),x2:830,y2:y(value),class:'axis'},svg);const t=svgNode('text',{x:55,y:y(value)+4,'text-anchor':'end'},svg);t.textContent=Math.round(value).toLocaleString();}
  if(c.type==='bar'){
    const step=width/points.length;
    points.forEach((p,i)=>{const rect=svgNode('rect',{x:left+i*step+step*.15,y:y(p.value),width:step*.7,height:bottom-y(p.value),class:'bar'},svg);svgNode('title',{},rect).textContent=pointLabel(p);const t=svgNode('text',{x:left+(i+.5)*step,y:280,transform:`rotate(-25 ${left+(i+.5)*step} 280)`,'text-anchor':'end'},svg);t.textContent=String(p.label);});
  } else {
    const future=points.map((p,i)=>({...p,i})).filter(p=>p.forecast);
    if(future.length&&future.every(p=>Number.isFinite(p.lower)&&Number.isFinite(p.upper))){
      const polygon=future.map(p=>`${x(p.i)},${y(p.upper)}`).concat([...future].reverse().map(p=>`${x(p.i)},${y(p.lower)}`)).join(' ');
      svgNode('polygon',{points:polygon,class:'interval'},svg);
    }
    for(const prediction of [false,true]){
      const subset=points.map((p,i)=>({...p,i})).filter(p=>Boolean(p.forecast)===prediction);
      if(subset.length){svgNode('polyline',{points:subset.map(p=>`${x(p.i)},${y(p.value)}`).join(' '),class:prediction?'predicted':'observed'},svg);
        subset.forEach(p=>{const dot=svgNode('circle',{cx:x(p.i),cy:y(p.value),r:3,fill:prediction?'#6353b3':'#0b7a51'},svg);svgNode('title',{},dot).textContent=pointLabel(p);});}
    }
    [...new Set([0,Math.floor((points.length-1)/2),points.length-1])].forEach(i=>{svgNode('text',{x:x(i),y:285,'text-anchor':'middle'},svg).textContent=points[i].label;});
  }
  const f=(windowResult.analyses||[]).find(a=>a.forecast)?.forecast;
  node('p',c.type==='forecast'?`Green: history · Purple: experimental forecast · Shading: nominal 80% range${Number.isFinite(f?.test_interval_coverage)?`; backtest coverage ${num(100*f.test_interval_coverage)}%`:''}. Hover a point for date, range and predicted value.`:'Hover a mark for its value.',card).className='muted legend';
}
function render(r){
  windowResult=r;
  $('ask-result').hidden=false;
  $('ask-charts').replaceChildren();
  for(const c of r.charts||[])chart(c);
  facts(r);
  if(!$('ask-charts').children.length){
    const card=node('section',undefined,$('ask-charts'));card.className='card';
    node('h2','Answer',card);node('div',r.answer||'No chartable data returned.',card).id='ask-answer';
    const sources=node('ul',undefined,card);
    for(const source of r.sources||[]){try{const url=new URL(source.url);if(!['https:','http:'].includes(url.protocol))continue;const a=node('a',source.title,node('li',undefined,sources));a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';}catch{}}
  }
}
async function api(path,options={}){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
  try{const r=await fetch('/api/assistant/'+path,{...options,signal:controller.signal,cache:'no-store'});const data=await r.json();if(!r.ok)throw new Error(data.error||'Assistant unavailable');return data;}finally{clearTimeout(timer);}
}
document.querySelectorAll('[data-ask]').forEach(b=>b.addEventListener('click',()=>{$('ask-question').value=b.dataset.ask;$('ask-question').focus();}));
$('ask-form').addEventListener('submit',async event=>{
  event.preventDefault();if(active)return;active=true;submit.disabled=true;$('ask-result').hidden=true;status.className='';status.textContent='Preparing analysis…';
  try{
    const job=await api('jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:$('ask-question').value})});
    const start=Date.now();
    while(Date.now()-start<540000){
      await new Promise(resolve=>setTimeout(resolve,1800));
      const state=await api('jobs/'+job.id);
      if(state.status==='completed'){render(state.result);status.textContent='Analysis complete.';return;}
      if(state.status==='failed')throw new Error(state.result?.error||'Research failed');
      status.textContent='Researching and calculating… '+Math.floor((Date.now()-start)/1000)+'s';
    }
    throw new Error('This question took too long. Try a narrower question.');
  }catch(error){status.className='ask-error';status.textContent=error.name==='AbortError'?'Connection timed out. Try again shortly.':error.message;}
  finally{active=false;submit.disabled=false;}
});
api('health').then(h=>{$('ask-health').textContent=h.model_configured?'Assistant connected':'Model configuration needed';}).catch(()=>{$('ask-health').textContent='Assistant offline · complaint monitor is available below';});
})();
