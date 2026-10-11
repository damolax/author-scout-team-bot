import {APP, validateDraft, trustedSender} from './core.mjs';
async function accounts() {
  const tabs = await chrome.tabs.query({url:'https://mail.google.com/*'});
  const results = await Promise.all(tabs.map(async tab => {
    try { const r = await chrome.tabs.sendMessage(tab.id, {type:'LD_ACCOUNT'}); return r?.email ? {email:r.email,tabId:tab.id,windowId:tab.windowId} : null; } catch { return null; }
  }));
  return results.filter(Boolean);
}
let preparing = false;
async function handle(m) {
  if (m.type === 'LD_PING') return {ok:true,version:chrome.runtime.getManifest().version};
  if (m.type === 'LD_ACCOUNTS') return {ok:true,accounts:await accounts()};
  if (m.type !== 'LD_PREPARE') throw Error('Unknown action.');
  const draft = validateDraft(m.draft);
  if (preparing) throw Error('A draft is already being prepared. Please wait.');
  preparing=true;
  try {
    const key='draft:'+draft.id;
    if ((await chrome.storage.session.get(key))[key]) throw Error('This request was already opened. Check Gmail before creating another draft.');
    const match=(await accounts()).find(a=>a.email.toLowerCase()===draft.account && (!m.tabId || a.tabId===m.tabId));
    if (!match) throw Error('Open this Gmail account in a tab, refresh that tab once, then refresh the account list.');
    await chrome.tabs.update(match.tabId,{active:true});
    await chrome.windows.update(match.windowId,{focused:true});
    // Record before filling: an interrupted response must never silently create another draft.
    await chrome.storage.session.set({[key]:true});
    const result=await chrome.tabs.sendMessage(match.tabId,{type:'LD_FILL',draft});
    if (!result?.ok) throw Error(result?.error||'Could not confirm the draft. Check Gmail before retrying.');
    return {ok:true,account:match.email,prepared:true};
  } finally {preparing=false;}
}
chrome.runtime.onMessage.addListener((m,sender,reply)=>{
  if (!trustedSender(sender,chrome.runtime.id)) {reply({ok:false,error:'Untrusted page.'});return;}
  handle(m).then(reply).catch(e=>reply({ok:false,error:e.message}));
  return true;
});
