/* HeatAhead's actual optional storage: one local dashboard preference. */
(function(win){
  'use strict';
  const KEY='heatahead_privacy',PANELS='heatahead_panels',TTL=180*24*60*60*1000;
  const doc=win.document;
  function readChoice(){
    try{
      const value=JSON.parse(win.localStorage.getItem(KEY)),age=Date.now()-value.decidedAt;
      return value.version===1&&typeof value.preferences==='boolean'&&
        Number.isFinite(value.decidedAt)&&age>=0&&age<TTL?value:null;
    }catch{return null;}
  }
  let choice=readChoice(),openSettings=()=>{};
  function allowed(){return !!(choice&&choice.preferences&&Date.now()-choice.decidedAt<TTL);}
  function clearOptional(){try{win.localStorage.removeItem(PANELS);}catch{}}
  if(!allowed())clearOptional();
  win.HeatAheadPrivacy={
    preferencesAllowed:allowed,
    readPanels(){if(!allowed())return null;try{return JSON.parse(win.localStorage.getItem(PANELS));}catch{return null;}},
    savePanels(value){if(!allowed())return false;try{win.localStorage.setItem(PANELS,JSON.stringify(value));return true;}catch{return false;}},
    openSettings(){openSettings();}
  };
  function init(){
    const $=id=>doc.getElementById(id),banner=$('privacy-banner'),overlay=$('privacy-overlay');
    if(!banner||!overlay)return;
    const dialog=$('privacy-dialog'),toggle=$('privacy-preferences');
    let returnFocus=null;
    function layout(){
      const height=banner.hidden?0:banner.getBoundingClientRect().height+32;
      doc.documentElement.style.setProperty('--privacy-space',height+'px');
      doc.body.classList.toggle('has-privacy-banner',!banner.hidden);
    }
    function showBanner(){banner.hidden=!!choice;layout();}
    function close(){
      overlay.hidden=true;
      if(returnFocus&&returnFocus.isConnected&&!returnFocus.closest('[hidden]'))returnFocus.focus({preventScroll:true});
    }
    openSettings=()=>{
      returnFocus=doc.activeElement;toggle.checked=allowed();overlay.hidden=false;
      $('privacy-close').focus();
    };
    function save(preferences){
      choice={version:1,preferences:!!preferences,decidedAt:Date.now()};
      let persisted=true;
      try{win.localStorage.setItem(KEY,JSON.stringify(choice));}catch{persisted=false;}
      if(!choice.preferences)clearOptional();
      close();showBanner();
      if(banner.contains(doc.activeElement))doc.querySelector('.privacy-footer-button')?.focus({preventScroll:true});
      $('privacy-status').textContent=persisted?'Your cookie choices are saved.':
        'Your choice applies to this visit. This browser could not save it for next time.';
      win.dispatchEvent(new win.CustomEvent('heatahead-privacy-change',{detail:{preferences:choice.preferences}}));
    }
    doc.querySelectorAll('[data-open-privacy]').forEach(button=>{
      button.hidden=false;button.addEventListener('click',openSettings);
    });
    doc.querySelectorAll('[data-privacy-accept]').forEach(button=>button.addEventListener('click',()=>save(true)));
    doc.querySelectorAll('[data-privacy-reject]').forEach(button=>button.addEventListener('click',()=>save(false)));
    $('privacy-save').addEventListener('click',()=>save(toggle.checked));
    $('privacy-close').addEventListener('click',close);
    overlay.addEventListener('click',event=>{if(event.target===overlay)close();});
    dialog.addEventListener('keydown',event=>{
      if(event.key==='Escape'){event.preventDefault();close();return;}
      if(event.key!=='Tab')return;
      const controls=[...dialog.querySelectorAll('button:not([disabled]),input:not([disabled]),a[href]')]
        .filter(node=>!node.hidden&&!node.closest('[hidden]'));
      const first=controls[0],last=controls[controls.length-1];
      if(event.shiftKey&&doc.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&doc.activeElement===last){event.preventDefault();first.focus();}
    });
    win.addEventListener('storage',event=>{
      if(event.key!==KEY&&event.key!==null)return;
      choice=readChoice();if(!allowed())clearOptional();
      toggle.checked=allowed();showBanner();
    });
    win.addEventListener('resize',layout);
    if(win.ResizeObserver)new win.ResizeObserver(layout).observe(banner);
    showBanner();
  }
  if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',init,{once:true});else init();
})(window);
