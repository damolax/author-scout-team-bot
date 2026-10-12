// Run with jsdom 22 available in NODE_PATH. No Gmail or network calls.
const {JSDOM}=require('jsdom');const fs=require('node:fs');const assert=require('node:assert/strict');
async function fixture({existing=false,account='sender@example.com',signature='Signature',from='sender@example.com',confirmSend=true}={}){
 const dom=new JSDOM(`<a href="https://accounts.google.com/SignOutOptions" aria-label="Google Account: Sender (${account})">Account</a><div gh="cm">Compose</div>`,{runScripts:'outside-only',url:'https://mail.google.com/mail/u/0/'});const w=dom.window;w.setTimeout=fn=>{queueMicrotask(fn);return 1};w.sendClicks=0;w.HTMLElement.prototype.getClientRects=function(){return [{}]};let listener;
 w.chrome={runtime:{id:'ext',onMessage:{addListener:fn=>listener=fn}}};
 const compose=()=>{const d=w.document.createElement('div');d.setAttribute('role','dialog');d.innerHTML='<input name="from" type="hidden"><input name="to"><input name="subjectbox"><div contenteditable="true" role="textbox"></div><div role="button" data-tooltip="Send (Ctrl-Enter)">Send</div>';d.querySelector('[name=from]').value=from;d.querySelector('[name=to]').addEventListener('keydown',e=>{if(e.key==='Enter'){const chip=w.document.createElement('span');chip.setAttribute('email',e.target.value);d.append(chip)}});d.querySelector('[role=button]').onclick=()=>{w.sendClicks++;d.remove();if(confirmSend){const t=w.document.createElement('div');t.setAttribute('role','alert');t.textContent='Message sent';w.document.body.append(t)}};d.querySelector('[contenteditable]').textContent=signature;w.document.body.append(d)};
 w.document.querySelector('[gh=cm]').onclick=compose;if(existing)compose();
 w.eval(fs.readFileSync('extension/gmail.js','utf8'));
 const call=m=>new Promise(resolve=>listener(m,{id:'ext'},resolve));
 return {w,call};
}
(async()=>{
 const draft={account:'sender@example.com',to:'reader@example.com',subject:'A & B',body:'Halló\n<literal text>\nSecond line'};
 const a=await fixture();assert.equal((await a.call({type:'LD_ACCOUNT'})).email,draft.account);assert.equal((await a.call({type:'LD_FILL',draft})).ok,true);assert.equal(a.w.document.querySelector('[name=to]').value,draft.to);assert.equal(a.w.document.querySelector('[name=subjectbox]').value,draft.subject);assert.equal(a.w.document.querySelector('[contenteditable]').textContent,draft.body+'Signature');assert.equal(a.w.document.querySelectorAll('literal').length,0);
 const b=await fixture({account:'different@example.com'});assert.equal((await b.call({type:'LD_FILL',draft})).ok,false);assert.equal(b.w.document.querySelector('[name=subjectbox]'),null);
 const c=await fixture({existing:true});assert.equal((await c.call({type:'LD_FILL',draft})).ok,false);assert.equal(c.w.document.querySelectorAll('[name=subjectbox]').length,1);
 const sent=await fixture();assert.equal((await sent.call({type:'LD_SEND',draft})).sent,true);assert.equal(sent.w.sendClicks,1);
 const wrong=await fixture({from:'alias@example.com'});assert.equal((await wrong.call({type:'LD_SEND',draft})).ok,false);assert.equal(wrong.w.sendClicks,0);
 const uncertain=await fixture({confirmSend:false});const result=await uncertain.call({type:'LD_SEND',draft});assert.equal(result.ok,false);assert.equal(result.attempted,true);assert.equal(uncertain.w.sendClicks,1);
 console.log('Gmail DOM fixtures passed: exact text, signature preservation, account mismatch, existing draft protection.');
})().catch(e=>{console.error(e);process.exit(1)});
