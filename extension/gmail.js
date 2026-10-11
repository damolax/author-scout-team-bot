(() => {
  if(globalThis.__letterdeskGmail)return;
  globalThis.__letterdeskGmail=true;
  let working=false;
  const visible=e=>!!e&&e.getClientRects().length>0;
  function account(){
    const found=new Set();
    // Read only the Google account control, never recipient chips or message contents.
    for(const e of document.querySelectorAll('a[href*="accounts.google.com/SignOutOptions"],a[href*="accounts.google.com/AccountChooser"]')){
      if(!visible(e))continue;
      const matches=(e.getAttribute('aria-label')||e.getAttribute('title')||'').match(/[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi)||[];
      for(const email of matches)found.add(email.toLowerCase());
    }
    return found.size===1?[...found][0]:null;
  }
  const pause=ms=>new Promise(r=>setTimeout(r,ms));
  async function waitFor(fn){for(let i=0;i<40;i++){const result=fn();if(result)return result;await pause(150);}throw Error('Gmail layout was not recognized. No message was sent. Use the copy buttons instead.');}
  function setInput(el,value){const setter=Object.getOwnPropertyDescriptor(el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;setter.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}
  async function fill(d){
    if(working)throw Error('Finish the current draft first.');
    if(account()!==d.account)throw Error('The Gmail account could not be confirmed. Nothing was filled.');
    working=true;
    try{
      // Never replace an existing compose window or reply.
      if([...document.querySelectorAll('input[name="subjectbox"]')].some(visible))throw Error('Save and close your existing Gmail draft before preparing another.');
      const compose=[...document.querySelectorAll('[gh="cm"],.T-I.T-I-KE')].find(visible);
      if(!compose)throw Error('Compose button not found. Refresh Gmail or use the copy buttons.');
      compose.click();
      const subject=await waitFor(()=>[...document.querySelectorAll('input[name="subjectbox"]')].find(visible));
      const dialog=subject.closest('[role="dialog"]')||subject.closest('form')?.parentElement;
      if(!dialog)throw Error('Could not isolate the new compose window. Nothing was sent.');
      const to=await waitFor(()=>[...dialog.querySelectorAll('input[name="to"],textarea[name="to"],input[role="combobox"]')].find(visible));
      const body=await waitFor(()=>[...dialog.querySelectorAll('[contenteditable="true"][role="textbox"],[contenteditable="true"][g_editable="true"]')].find(visible));
      if(account()!==d.account)throw Error('Account changed. Draft filling stopped.');
      if(subject.value||to.value)throw Error('The new draft is not empty. Nothing was overwritten.');
      to.focus();setInput(to,d.to);to.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));to.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
      subject.focus();setInput(subject,d.subject);
      body.focus();const message=document.createElement('div');message.style.whiteSpace='pre-wrap';message.textContent=d.body;body.prepend(message,document.createElement('br'));body.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:d.body}));
      if(subject.value!==d.subject||message.textContent!==d.body||!body.contains(message))throw Error('Gmail did not retain the full draft. Check it manually before sending.');
      const note=document.createElement('div');note.textContent='Letterdesk draft ready. Check the From address, recipient and full message, then click Send yourself.';note.style.cssText='padding:12px;background:#e5f1eb;color:#173e30;font:14px system-ui;border:1px solid #abc9b8;';note.setAttribute('role','status');dialog.prepend(note);
      return {ok:true};
    }finally{working=false;}
  }
  chrome.runtime.onMessage.addListener((m,sender,reply)=>{
    if(sender.id!==chrome.runtime.id)return;
    if(m.type==='LD_ACCOUNT'){reply({email:account()});return;}
    if(m.type==='LD_FILL'){fill(m.draft).then(reply).catch(e=>reply({ok:false,error:e.message}));return true;}
  });
})();
