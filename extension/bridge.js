(() => {
  const origin='https://author-scout-team-bot.vercel.app';
  window.addEventListener('message',async event=>{
    const m=event.data;
    if(event.source!==window||event.origin!==origin||m?.source!=='LETTERDESK_APP'||!['LD_PING','LD_ACCOUNTS','LD_PREPARE','LD_QUEUE_START','LD_QUEUE_STATUS','LD_QUEUE_PAUSE','LD_QUEUE_RESUME','LD_QUEUE_SKIP','LD_QUEUE_CLEAR'].includes(m.type)||typeof m.requestId!=='string')return;
    let result;
    try {result=await chrome.runtime.sendMessage({type:m.type,draft:m.draft,tabId:m.tabId,queue:m.queue,scope:m.scope});}
    catch {result={ok:false,error:'Refresh Letterdesk and Gmail after installing or updating the extension.'};}
    window.postMessage({source:'LETTERDESK_EXTENSION',requestId:m.requestId,...result},origin);
  });
})();
