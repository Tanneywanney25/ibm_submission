// Dependency-free DOM contract test; no real providers, keys, or network.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
class Element{
 constructor(tag){this.tagName=tag;this.children=[];this.listeners={};this.dataset={};this.textContent='';this.value='';this.hidden=false;}
 appendChild(x){this.children.push(x);return x;}
 setAttribute(k,v){this[k]=v;}
 replaceChildren(...children){this.children=children;}
 addEventListener(k,fn){this.listeners[k]=fn;}
 focus(){}
}
Object.defineProperty(Element.prototype,'textContent',{
 get(){return (this._text||'')+this.children.map(c=>c.textContent).join('');},
 set(value){this._text=String(value);}
});
const ids=new Map(['ask-form','ask-question','ask-submit','ask-health','ask-status','ask-result','ask-answer','ask-execution','ask-freshness','ask-charts','ask-tables','ask-sources','ask-facts','ask-facts-panel'].map(id=>[id,new Element('div')]));
const doc={getElementById:id=>ids.get(id),createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t),querySelectorAll:()=>[]};
let offline=false;
const result={answer:'Safe text <script>not executed</script> [data-1]',metadata:{data_through:'2026-10-15',scope:'historical building universe'},execution:{requested_model:'test'},
 charts:[{type:'forecast',title:'Daily count forecast',points:[{label:'2026-10-15',value:8},{label:'2026-10-19',value:12,lower:0,upper:30,forecast:true},{label:'2026-10-20',value:10,lower:0,upper:28,forecast:true}]},{type:'bar',title:'Boroughs',points:[{label:'Bronx',value:5}]}],
 analyses:[{operation:'forecast',metadata:{data_through:'2026-10-15'},table:[{day:'2026-10-19',expected:12,lower:0,upper:30}],forecast:{quality:'experimental_low_coverage',test_interval_coverage:.6,model_test_mae:4,baseline_test_mae:3,note:'Experimental.'}}],
 sources:[{id:'data-1',title:'HPD',url:'https://data.cityofnewyork.us'},{id:'bad',title:'Bad URL',url:'javascript:alert(1)'}]};
async function fetch(url,opts){
 if(url.endsWith('health'))return {ok:true,json:async()=>({model_configured:true})};
 if(offline)return {ok:false,json:async()=>({error:'Research service offline'})};
 if(opts.method==='POST')return {ok:true,json:async()=>({id:'a'.repeat(48)})};
 return {ok:true,json:async()=>({status:'completed',result})};
}
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../web/static/assistant.js'),'utf8'),{document:doc,fetch,AbortController,URL,Date,Promise,Number,String,Set,Object,Math,Error,setTimeout:(f,n)=>setTimeout(f,n===1800?0:n),clearTimeout});
(async()=>{
 ids.get('ask-question').value='Show forecast';
 await ids.get('ask-form').listeners.submit({preventDefault(){}});
 assert.equal(ids.get('ask-status').textContent,'Analysis complete.');
 assert.equal(ids.get('ask-charts').children.length,2);



 assert.ok(ids.get('ask-facts').children.length>=3 && ids.get('ask-facts').children.length<=5);
 const texts=e=>[e.textContent,...e.children.flatMap(texts)];
 assert.ok(texts(ids.get('ask-charts')).includes('2026-10-19, 0–30 (12)'));
 assert.ok(texts(ids.get('ask-charts')).some(t=>t.includes('backtest coverage 60%')));
 assert.ok(texts(ids.get('ask-facts')).some(t=>t.includes('the range is 0–30 (predicted value = 12)')));
 assert.ok(!texts(ids.get('ask-facts')).some(t=>t.includes('Daily ranges are not')));
 assert.ok(ids.get('ask-facts').children.some(li=>li.children.some(c=>c.tagName==='strong')));
 assert.ok(!texts(ids.get('ask-charts')).some(t=>t==='ask-range-labels'));
 offline=true;
 await ids.get('ask-form').listeners.submit({preventDefault(){}});
 assert.match(ids.get('ask-status').textContent,/offline/);
 assert.equal(ids.get('ask-submit').disabled,false);
 console.log('PASS: compact results, calculated facts, tooltip ranges, shared coverage legend, offline state.');
})().catch(e=>{console.error(e);process.exitCode=1});
