(function(){
  'use strict';
  const form=document.getElementById('newsletter-form');if(!form)return;
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    if(!form.reportValidity())return;
    const button=form.querySelector('button[type=submit]'),status=document.getElementById('newsletter-status');
    button.disabled=true;status.textContent='Requesting your confirmation email…';
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
    try{
      const response=await fetch('/api/newsletter/subscribe',{method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json'},signal:controller.signal,
        body:JSON.stringify({name:form.elements.name.value.trim(),email:form.elements.email.value.trim(),
          website:form.elements.website.value,consent:true})});
      const result=await response.json();
      status.textContent=response.ok?result.message:(result.error||'Signup is unavailable right now. Please try again later.');
      if(response.ok)form.reset();
    }catch{status.textContent='We couldn’t confirm the request. Please try again later or email heataheadnyc@gmail.com.';}
    finally{clearTimeout(timer);button.disabled=false;}
  });
})();
