/* Run with Node 18+: node web/tests/test_map.cjs. No npm packages required.
 * Exercises the shipped map script against its actual 63k-property payload.
 * This checks interactions/data boundaries; visual WebGL QA uses the Vercel preview.
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const payload = JSON.parse(fs.readFileSync(path.join(root,'public/data/map_data.json'),'utf8'));
const html = fs.readFileSync(path.join(root, 'web/templates/map.html'), 'utf8');
let script = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m => m[1]).filter(Boolean).join('\n');
new vm.Script(script);
script = script.replace('  async function start() {', `
  module.exports = {parseRows,riskColor,riskLabel,sourceRows,summarize,onClick,openArea,closeArea,
    renderAreaPage,zoomToArea,makeLayers,applyFilter,detailBlend,gridBlend,pickMode,renderPixelRatios,mapController,showBuildings,start,
    onViewStateChange,onInteractionStateChange,state,AREA_PAGE_SIZE,DETAIL_START,DETAIL_END,
    setViewer:v=>{viewer=v;},setMap:v=>{baseMap=v;}};
  async function start() {`);
const elements = new Map();
let focused = null;
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, hidden:id === 'hm-area-panel', value:'0', innerHTML:'', textContent:'',
    isConnected:true, disabled:false, scrollTop:0, clientWidth:1000, clientHeight:800, dataset:{}, setAttribute(){}, addEventListener(){},
    focus(){focused=id;}, getBoundingClientRect(){return {width:1000,height:800};}
  });
  return elements.get(id);
}
const frames = new Map(); let nextFrame = 0;
const flush = () => { const callbacks=[...frames.values()]; frames.clear(); callbacks.forEach(cb=>cb()); };
const navigation = [], calls = [];
let constructed = null;
class Layer {constructor(props){this.props=props;}}
const context = vm.createContext({module:{exports:{}}, Intl, performance, AbortController, console,
  setTimeout, clearTimeout,
  requestAnimationFrame:cb=>{frames.set(++nextFrame,cb);return nextFrame;},
  fetch:async()=>({ok:true,headers:{get:()=>'application/json'},json:async()=>payload}),
  window:{matchMedia:()=>({matches:true}),location:{assign:url=>navigation.push(url)}},
  document:{readyState:'loading',addEventListener(){},querySelectorAll:()=>[],getElementById:element,
    activeElement:{isConnected:true,focus(){focused='previous';}}},
  deck:{HexagonLayer:Layer,ScatterplotLayer:Layer,FlyToInterpolator:class {},
    WebMercatorViewport:class {fitBounds(){return {longitude:-73.97,latitude:40.715,zoom:10.05};}},
    DeckGL:class {constructor(options){constructed=options;}setProps(props){calls.push(props);}getMapboxMap(){return null;}}}
});
vm.runInContext(script,context);
const api = context.module.exports;
const plain = v => JSON.parse(JSON.stringify(v));
const parsed = api.parseRows(payload);
assert.equal(parsed.skipped,0);
assert.ok(parsed.rows.length > 63000);
assert.equal(new Set(parsed.rows.map(r=>r.bbl[0])).size,5);
api.state.rows=parsed.rows; api.state.filtered=parsed.rows;
api.setViewer({setProps:props=>calls.push(props)});
console.log('PASS: actual payload preserves all five boroughs and BBL alignment.');

assert.deepEqual(plain(api.riskColor(0)),[219,239,255]);
assert.deepEqual(plain(api.riskColor(1)),[27,92,180]);
let previous=api.riskColor(0); const distinct=new Set();
for(let i=0;i<=990;i++){
  const color=api.riskColor(i/1000);
  distinct.add(color.join(','));
  color.forEach((v,c)=>{assert.ok(v<=previous[c]);assert.ok(Math.abs(v-previous[c])<=1);});
  previous=color;
}
assert.ok(distinct.size>200);
assert.equal(api.riskLabel(.2),'20–39%');
assert.equal(api.riskLabel(1),'80–99%');
console.log('PASS: smooth 256-step scale, monotonic light-to-dark colors, honest risk bands.');

// All bin members, including ties, are listed; selecting an area never navigates.
const rows=parsed.rows.slice(0,47).map((row,i)=>({...row,p:(i%10)/10}));
const object={points:rows.map(source=>({source}))};
api.onClick({object});
assert.equal(navigation.length,0);
assert.equal(element('hm-area-panel').hidden,false);
assert.equal(api.state.selectedRows.length,47);
assert.equal(focused,'hm-area-close');
assert.match(element('hm-area-title').textContent,/47 buildings/);
assert.match(element('hm-area-page').textContent,/1–20 of 47/);
assert.equal((element('hm-area-list').innerHTML.match(/<li>/g)||[]).length,20);
for(let i=1;i<api.state.selectedRows.length;i++) assert.ok(api.state.selectedRows[i-1].p>=api.state.selectedRows[i].p);
const all=[];
for(let page=0;page<3;page++){
  api.state.selectedPage=page; api.renderAreaPage();
  all.push(...[...element('hm-area-list').innerHTML.matchAll(/href="\/building\?bbl=(\d+)"/g)].map(m=>m[1]));
}
assert.equal(new Set(all).size,47);
assert.deepEqual([...all].sort(),plain(rows.map(r=>r.bbl).sort()));
assert.equal(element('hm-area-next').disabled,true);
api.closeArea(true); assert.equal(focused,'previous');
assert.equal(element('hm-area-panel').hidden,true);
api.onClick({object:{points:[{source:rows[0]}]}});
assert.match(element('hm-area-title').textContent,/1 building in/);
assert.equal(navigation.length,0);
api.onClick({object:rows[3]});
assert.equal(navigation[0],'/building?bbl='+rows[3].bbl);
assert.equal(api.sourceRows({points:[0,{index:1}]}).length,2);
console.log('PASS: area click lists every member with pagination; only a property click opens one record.');

api.state.mode='flat'; api.zoomToArea();
assert.equal(calls.at(-1).initialViewState.pitch,0);
assert.equal(element('hm-area-panel').hidden,true);
api.showBuildings();
assert.equal(calls.at(-1).initialViewState.pitch,0,'View buildings keeps the chosen flat mode');
api.state.mode='3d'; api.showBuildings();
assert.equal(calls.at(-1).initialViewState.pitch,55);
api.state.fallbackUsed=true; api.showBuildings();
assert.equal(calls.at(-1).initialViewState.pitch,0);
api.state.fallbackUsed=false;
console.log('PASS: area zoom targets its properties; flat/3D choices and fallback are preserved.');

let previousLayers=null;
for(let i=0;i<=1000;i++){
  api.state.view.zoom=8+i/100;
  const layers=api.makeLayers().map(l=>l.props),[overview,hex,points]=layers;
  assert.ok(Math.abs(layers.reduce((sum,l)=>sum+l.opacity,0)-.95)<1e-12);
  assert.equal(layers.filter(l=>l.pickable&&l.visible).length,1);
  assert(overview.radius>hex.radius,'overview cells must be larger');
  for(const l of layers)assert.equal(l.data,api.state.filtered);
  for(const l of [overview,hex]){
    assert.equal(l.colorRange.length,256);assert.deepEqual(plain(l.colorDomain),[0,.99]);
    assert.equal(l.colorAggregation,'MEAN');assert.equal(l.elevationAggregation,'SUM');
    assert.equal(l.elevationScale,1.5,'complaint heights use the same scale in both grids');
  }
  if(previousLayers){
    for(let j=0;j<3;j++){
      const l=layers[j],previous=previousLayers[j];
      assert.equal(l.id,previous.id);assert.equal(l.radius,previous.radius);
      assert.equal(l.getPosition,previous.getPosition);assert.equal(l.getColorWeight,previous.getColorWeight);
      assert.equal(l.getFillColor,previous.getFillColor);
      assert.ok(Math.abs(l.opacity-previous.opacity)<.02,'no opacity jumps during either handover');
    }
    assert(overview.opacity<=previousLayers[0].opacity+1e-12);
    assert(points.opacity>=previousLayers[2].opacity-1e-12);
  }
  previousLayers=layers;
}
for(const [zoom,active] of [[10,0],[12.6,1],[15,2]]){
  api.state.view.zoom=zoom;
  const layers=api.makeLayers().map(l=>l.props);
  assert.equal(layers[active].opacity,.95);assert(layers[active].pickable&&layers[active].visible);
}
console.log('PASS: 1,001 zoom samples keep both fades continuous, exactly one pick target, and fixed radii/data/accessors.');

for(const dpr of [undefined,NaN,Infinity,0,-1,.75,1,1.25,1.5,2,3,4]){
  const ratios=api.renderPixelRatios(dpr);
  assert(ratios.map>=1&&ratios.map<=2);assert(ratios.overlay>=1&&ratios.overlay<=1.5);
  assert(ratios.map>=ratios.overlay);
}
assert.deepEqual(plain(api.renderPixelRatios(1)),{map:1,overlay:1});
assert.deepEqual(plain(api.renderPixelRatios(2)),{map:2,overlay:1.5});
console.log('PASS: sharper high-DPI rendering is capped; standard-density displays keep their original cost.');

assert.equal(api.mapController('flat').scrollZoom.speed,.025);
assert.equal(api.mapController('flat').scrollZoom.smooth,false);
assert.equal(api.mapController('flat').dragPan,true);
assert.equal(api.mapController('flat').inertia,false,'respects reduced motion');
api.state.view.zoom=13; const before=calls.length;
for(let i=0;i<100;i++) api.onViewStateChange({viewState:{...api.state.view,zoom:13+i/100}});
assert.equal(frames.size,1,'many zoom events schedule only one graphics update per frame');
assert.equal(calls.length,before);flush();assert.equal(calls.length,before+1);
const after=calls.length;
for(let i=0;i<100;i++) api.onViewStateChange({viewState:{...api.state.view,longitude:-74+i/10000}});
assert.equal(frames.size,0,'constant-zoom pans do not recreate data layers');
assert.equal(calls.length,after);
api.state.view.zoom=16;api.state.renderedBlend=1;
api.onViewStateChange({viewState:{...api.state.view,zoom:15.5}});
api.onViewStateChange({viewState:{...api.state.view,zoom:11}});
flush(); assert.equal(calls.at(-1).layers[0].props.opacity,.95,'rapid zoom-out restores hexagons');
api.onInteractionStateChange({isDragging:true});assert.equal(api.state.interacting,true);
api.onInteractionStateChange({isDragging:false});assert.equal(api.state.interacting,false);
console.log('PASS: wheel delay removed; zooms coalesce; pans reuse GPU data; rapid zoom-out restores coverage.');

api.state.view.zoom=10.5;api.state.renderedBlend=0;api.state.renderedGridBlend=0;
const beforeGrid=calls.length;
api.onViewStateChange({viewState:{...api.state.view,zoom:11.6}});flush();
assert.equal(calls.length,beforeGrid+1,'overview-to-neighborhood fade redraws before the building-dot fade starts');
assert(calls.at(-1).layers[0].props.opacity<.95);assert(calls.at(-1).layers[1].props.opacity>0);
api.onClick({object});assert.equal(element('hm-area-panel').hidden,false);
api.onViewStateChange({viewState:{...api.state.view,zoom:12.4}});flush();
assert.equal(element('hm-area-panel').hidden,true,'switching grids discards a previous area list');
console.log('PASS: overview-only zooms redraw correctly and area lists cannot refer to the previous grid.');

api.onClick({object});element('hm-risk-filter').value='99';api.applyFilter();
assert.equal(element('hm-area-panel').hidden,true,'filter changes discard the stale area selection');
assert.ok(api.state.filtered.every(r=>r.p>=.99));
console.log('PASS: selected-area lists cannot survive as stale data after a risk filter change.');

(async()=>{
  context.window.deck=context.deck;
  context.window.maplibregl=context.maplibregl={};
  context.window.devicePixelRatio=3;
  await api.start();
  assert(constructed,'keyless startup creates the map');
  assert.equal(constructed.mapOptions.pixelRatio,2);
  assert.equal(constructed.useDevicePixels,1.5);
  assert.equal(constructed.layers.length,3);
  assert.equal(constructed.layers[0].props.opacity,.95);
  assert.equal(api.state.rows.length,parsed.rows.length);
  constructed.onAfterRender();assert.equal(api.state.ready,true);
  assert.equal(element('hm-message').hidden,true);
  assert.match(element('hm-view-label').textContent,/City view/);
  console.log('PASS: actual startup wires bounded high-DPI settings and the city overview into the shipped map.');
})().catch(error=>{console.error(error);process.exitCode=1;});
