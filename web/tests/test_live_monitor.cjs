// Exercise the actual monitor script against a minimal DOM: render + retry.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../templates/current_complaints.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
class Element {
  constructor(){this.children=[];this.textContent='';}
  append(x){this.children.push(x);}
  replaceChildren(){this.children=[];}
}
async function run(offline){
  const ids=new Map();
  const document={getElementById(id){if(!ids.has(id))ids.set(id,new Element());return ids.get(id);},createElement(){return new Element();}};
  const payload={
    stats:{status:'ok',latest_heat_received:'2026-10-16T12:00:00',last_successful_poll:'2026-10-17T22:00:00Z',complaints_24h:1,complaints_7d:2,source_lag_hours:30,unlocated_complaints_7d:0},
    queue:{buildings:[{bbl:'2032120092',complaints_7d:2,latest_received:'2026-10-16T12:00:00'}]},
    events:{events:[{bbl:'2032120092',received_date:'2026-10-16T12:00:00',reported_problem:'NO HEAT'}]}
  };
  let scheduled=0;
  vm.runInNewContext(script,{document,AbortController,Date,Number,encodeURIComponent,Promise,
    setTimeout(fn,ms){if(ms===15000)scheduled++;return 1;},clearTimeout(){},
    fetch:async url=>({ok:!offline,json:async()=>payload[url.split('/').pop().split('?')[0]]})});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(scheduled,1);
  if(offline){assert.match(ids.get('current-banner').textContent,/offline/);}
  else{
    assert.equal(ids.get('current-events').children.length,1);
    assert.equal(ids.get('current-queue').children.length,1);
    assert.match(ids.get('current-banner').textContent,/30.0 hours old/);
  }
}
(async()=>{await run(false);await run(true);console.log('Current monitor rendering, publication lag and offline retry passed');})();
