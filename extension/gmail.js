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
  async function waitFor(fn){for(let i=0;i<40;i++){const result=fn();if(result)return result;await pause(150);}throw Error('Gmail layout was not recognized. Gmail could not confirm this step. Check the draft and Sent folder before retrying.');}
  function setInput(el,value){const setter=Object.getOwnPropertyDescriptor(el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype,'value').set;setter.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}
  async function fill(d,sendNow=false){
    let attempted=false;
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
      if(!sendNow)return {ok:true};
      // Automatic sending is restricted to an explicitly verified From identity.
      const from=dialog.querySelector('[name="from"]');
      const fromText=from?.value||from?.getAttribute('email')||'';
      const fromEmails=fromText.match(/[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi)||[];
      if(fromEmails.length!==1||fromEmails[0].toLowerCase()!==d.account)throw Error('The From address cannot be verified or differs from the selected Gmail account. Draft saved; queue paused.');
      await pause(300);
      const recipientValues=[...dialog.querySelectorAll('[email],[data-hovercard-id]')].map(e=>e.getAttribute('email')||e.getAttribute('data-hovercard-id'));
      if(!recipientValues.some(v=>v?.toLowerCase()===d.to.toLowerCase()))throw Error('Gmail has not confirmed the recipient. Draft saved; queue paused.');
      const send=[...dialog.querySelectorAll('[role="button"]')].find(e=>visible(e)&&/^Send(?:\s|$|\()/i.test(e.getAttribute('data-tooltip')||e.getAttribute('aria-label')||e.textContent.trim())&&!/schedule/i.test(e.getAttribute('aria-label')||''));
      if(!send||send.getAttribute('aria-disabled')==='true')throw Error('Gmail Send button is unavailable. Draft saved; queue paused.');
      if(account()!==d.account||subject.value!==d.subject||message.textContent!==d.body)throw Error('Account or draft changed. Sending stopped.');
      attempted=true;send.click();
      await waitFor(()=>!subject.isConnected&&[...document.querySelectorAll('[role="alert"],.bAq')].some(e=>visible(e)&&/message sent/i.test(e.textContent)));
      return {ok:true,sent:true};
    }catch(error){return {ok:false,error:error.message,attempted};}
    finally{working=false;}
  }
  chrome.runtime.onMessage.addListener((m,sender,reply)=>{
    if(sender.id!==chrome.runtime.id)return;
    if(m.type==='LD_ACCOUNT'){reply({email:account()});return;}
    if(m.type==='LD_FILL'||m.type==='LD_SEND'){fill(m.draft,m.type==='LD_SEND').then(reply).catch(e=>reply({ok:false,error:e.message}));return true;}
  });
})();
