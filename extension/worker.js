import {validateDraft, validateQueue, trustedSender,emailOK,nextEligible,randomDelay} from './core.mjs';
const KEY='letterdeskQueueV2',LEDGER='letterdeskSendLedgerV2',ALARM='letterdeskQueueTick';
const REMOVED='letterdeskRemovedAccounts';
const removedAccounts=async()=> (await chrome.storage.local.get(REMOVED))[REMOVED]||[];
let accountChange=Promise.resolve();
let pumping=false,preparing=false,starting=false,pauseRequested=false,timer;
async function accounts(){const tabs=await chrome.tabs.query({url:'https://mail.google.com/*'});const found=await Promise.all(tabs.map(async tab=>{try{const r=await chrome.tabs.sendMessage(tab.id,{type:'LD_ACCOUNT'});return r?.email?{email:r.email.toLowerCase(),tabId:tab.id,windowId:tab.windowId}:null}catch{return null}}));const removed=await removedAccounts();return found.filter(a=>a&&!removed.includes(a.email))}
const read=async()=> (await chrome.storage.local.get(KEY))[KEY]||null;
const write=async q=>chrome.storage.local.set({[KEY]:q});
async function wake(delay=1000){clearTimeout(timer);timer=setTimeout(()=>tick(),Math.max(500,delay));await chrome.alarms.create(ALARM,{when:Date.now()+Math.max(1000,delay)});}
async function status(scope){const q=await read(),ledger=(await chrome.storage.local.get(LEDGER))[LEDGER]||{};return {ok:true,removed:await removedAccounts(),queue:q&&(!scope||q.scope===scope)?{...q,jobs:q.jobs.map(({body,subject,to,...job})=>job)}:null,attempted:Object.values(ledger).filter(r=>r.scope===scope).map(r=>r.messageId),receipts:Object.values(ledger).filter(r=>r.scope===scope&&r.status==='sent')}}
async function tick(){
 if(pumping||preparing)return;pumping=true;
 try{
  let q=await read();if(!q||q.state!=='running')return;
  const inFlight=q.jobs.find(j=>j.status==='sending');
  if(inFlight){inFlight.status='uncertain';q.state='paused';q.error='Sending was interrupted. Check Gmail Sent before skipping this message. It will not be retried automatically.';await write(q);return;}
  const job=q.jobs.find(j=>j.status==='pending');if(!job){q.state='complete';await write(q);return;}
  const removed=await removedAccounts(),available=q.accounts.filter(a=>!removed.includes(a));
  if(!available.length){q.state='paused';q.error='All queue accounts were removed. Add an account back or clear the queue.';await write(q);return;}
  const now=Date.now(),eligible=nextEligible(available,q.cooldowns,now);
  if(!eligible.length){await wake(Math.min(...available.map(a=>q.cooldowns[a]))-now);return;}
  const email=eligible[Math.floor(Math.random()*eligible.length)],match=(await accounts()).find(a=>a.email===email);
  if(!match){q.state='paused';q.error='Open and refresh Gmail for '+email+', then resume.';await write(q);return;}
  // Re-read after async detection so a user's pause cannot be lost.
  q=await read();if(q?.state!=='running')return;
  const current=q.jobs.find(j=>j.messageId===job.messageId);if(current?.status!=='pending')return;
  const ledger=(await chrome.storage.local.get(LEDGER))[LEDGER]||{},ledgerKey=q.scope+':'+job.messageId;
  if(ledger[ledgerKey]){current.status=ledger[ledgerKey].status==='sent'?'sent':'uncertain';q.state='paused';q.error='This message has an earlier send attempt. Check Gmail before continuing.';await write(q);return;}
  current.status='sending';current.account=email;current.startedAt=Date.now();q.error='';await write(q);
  ledger[ledgerKey]={scope:q.scope,messageId:job.messageId,account:email,status:'sending'};await chrome.storage.local.set({[LEDGER]:ledger});
  let result;
  try{await chrome.tabs.update(match.tabId,{active:true});await chrome.windows.update(match.windowId,{focused:true});if((await removedAccounts()).includes(email))result={ok:false,attempted:false,error:'Sender removed before sending.'};else result=await chrome.tabs.sendMessage(match.tabId,{type:'LD_SEND',draft:{...job,id:String(job.messageId),account:email}})}catch{result={ok:false,error:'Gmail disconnected during sending. Check Sent before continuing.'};}
  const latest=await read();if(!latest||latest.id!==q.id)return;
  const updated=latest.jobs.find(j=>j.messageId===job.messageId),finished=Date.now();
  updated.status=result?.ok&&result.sent?'sent':result?.attempted===false?'failed':'uncertain';updated.error=result?.error||'';updated.finishedAt=finished;
  const finalLedger=(await chrome.storage.local.get(LEDGER))[LEDGER]||{};
  finalLedger[ledgerKey]={scope:q.scope,messageId:job.messageId,account:email,status:updated.status,finishedAt:finished};
  await chrome.storage.local.set({[LEDGER]:finalLedger});
  latest.cooldowns[email]=finished+randomDelay(latest.minSeconds,latest.maxSeconds);
  if(updated.status!=='sent'){latest.state='paused';latest.error=updated.error||'Gmail did not confirm sending. Check Sent. No automatic retry.';}
  else if(!latest.jobs.some(j=>j.status==='pending'))latest.state='complete';
  if(pauseRequested&&latest.state==='running')latest.state='paused';await write(latest);if(latest.state==='running')await wake(1000);
 }finally{pumping=false;}
}
async function handle(m){
 if(m.type==='LD_PING')return {ok:true,version:chrome.runtime.getManifest().version};
 if(m.type==='LD_ACCOUNTS')return {ok:true,accounts:await accounts(),removed:await removedAccounts()};
 if(['LD_ACCOUNT_REMOVE','LD_ACCOUNT_RESTORE'].includes(m.type)){
  const email=String(m.email||'').trim().toLowerCase();if(!emailOK(email))throw Error('Invalid Gmail account.');
  const change=accountChange.then(async()=>{
   const removed=await removedAccounts();
   await chrome.storage.local.set({[REMOVED]:m.type==='LD_ACCOUNT_REMOVE'?[...new Set([...removed,email])]:removed.filter(a=>a!==email)});
   if(m.type==='LD_ACCOUNT_REMOVE'){
    const q=await read();if(q?.accounts.includes(email)&&q.state==='running'){
     pauseRequested=true;q.state='paused';q.error='Sender removed: '+email+'. A send already in progress may finish. Resume to use remaining accounts.';await write(q);clearTimeout(timer);await chrome.alarms.clear(ALARM);
    }
   }
  });accountChange=change.catch(()=>{});await change;
  return {ok:true,accounts:await accounts(),removed:await removedAccounts()};
 }
 if(m.type==='LD_QUEUE_STATUS')return status(m.scope);
 if(m.type==='LD_QUEUE_START'){
  const input=validateQueue(m.queue),old=await read();
  if(pumping||old?.state==='running'||old?.jobs.some(j=>j.status==='sending'))throw Error('Pause the active queue and wait for the current send to finish.');
  if(old?.state==='paused'&&old.jobs.some(j=>j.status==='pending'))throw Error('Finish or clear the paused queue before starting another.');
  const open=await accounts();if(input.accounts.some(a=>!open.some(o=>o.email===a)))throw Error('Every selected Gmail account must be open and detected.');
  const ledger=(await chrome.storage.local.get(LEDGER))[LEDGER]||{};
  if(input.jobs.some(j=>ledger[input.scope+':'+j.messageId]))throw Error('A selected message already has a send attempt. Refresh Letterdesk and exclude it.');
  const q={...input,id:crypto.randomUUID(),state:'running',cooldowns:old?.cooldowns||{},error:'',createdAt:Date.now()};pauseRequested=false;await write(q);await wake();return status(input.scope);
 }
 if(['LD_QUEUE_PAUSE','LD_QUEUE_RESUME','LD_QUEUE_SKIP','LD_QUEUE_CLEAR'].includes(m.type)){
  const q=await read();if(!q)return {ok:true};if(m.scope&&m.scope!==q.scope)throw Error('This queue belongs to a different workspace session.');
  if(m.type==='LD_QUEUE_PAUSE'){pauseRequested=true;q.state='paused';await write(q);clearTimeout(timer);await chrome.alarms.clear(ALARM);}
  if(m.type==='LD_QUEUE_RESUME'){const removed=await removedAccounts();q.accounts=q.accounts.filter(a=>!removed.includes(a));if(!q.accounts.length)throw Error('No sender accounts remain. Add an account back or clear the queue.');if(q.jobs.some(j=>['sending','uncertain','failed'].includes(j.status)))throw Error('Check Gmail, then skip the problem message before resuming.');q.state='running';q.error='';pauseRequested=false;await write(q);await wake();}
  if(m.type==='LD_QUEUE_SKIP'){if(pumping||q.jobs.some(j=>j.status==='sending'))throw Error('Wait for the current send to finish.');for(const j of q.jobs)if(['uncertain','failed'].includes(j.status))j.status='skipped';q.error='';await write(q);}
  if(m.type==='LD_QUEUE_CLEAR'){if(pumping||q.jobs.some(j=>j.status==='sending'))throw Error('Pause and wait for the current send to finish.');q.state='stopped';q.jobs=q.jobs.map(j=>j.status==='pending'?{...j,status:'skipped'}:j);await write(q);clearTimeout(timer);await chrome.alarms.clear(ALARM);}
  return status(m.scope);
 }
 if(m.type!=='LD_PREPARE')throw Error('Unknown action.');
 const draft=validateDraft(m.draft);if(preparing||pumping||(await read())?.state==='running')throw Error('Pause the queue before preparing another draft.');preparing=true;
 try{const key='draft:'+draft.id;if((await chrome.storage.session.get(key))[key])throw Error('Check Gmail: this draft was already requested.');const match=(await accounts()).find(a=>a.email===draft.account&&(!m.tabId||a.tabId===m.tabId));if(!match)throw Error('Open this Gmail account and refresh its tab once.');await chrome.tabs.update(match.tabId,{active:true});await chrome.windows.update(match.windowId,{focused:true});await chrome.storage.session.set({[key]:true});const result=await chrome.tabs.sendMessage(match.tabId,{type:'LD_FILL',draft});if(!result?.ok)throw Error(result?.error||'Check Gmail before retrying.');return {ok:true,prepared:true}}finally{preparing=false;}
}
chrome.runtime.onMessage.addListener((m,sender,reply)=>{if(!trustedSender(sender,chrome.runtime.id)){reply({ok:false,error:'Untrusted page.'});return;}if(m.type==='LD_QUEUE_START'&&starting){reply({ok:false,error:'A queue is already starting.'});return;}if(m.type==='LD_QUEUE_START')starting=true;handle(m).then(reply).catch(e=>reply({ok:false,error:e.message})).finally(()=>{if(m.type==='LD_QUEUE_START')starting=false});return true;});
chrome.alarms.onAlarm.addListener(a=>{if(a.name===ALARM)tick().catch(()=>{})});
async function pauseAfterRestart(){const q=await read();if(q?.state==='running'){for(const j of q.jobs)if(j.status==='sending')j.status='uncertain';q.state='paused';q.error='Chrome restarted or the extension updated. Check the queue and resume.';await write(q);}await chrome.alarms.clear(ALARM);}
chrome.runtime.onStartup.addListener(pauseAfterRestart);chrome.runtime.onInstalled.addListener(pauseAfterRestart);
