export const APP = 'https://author-scout-team-bot.vercel.app';
export const emailOK = value => typeof value === 'string' && /^[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+$/.test(value);
export function validateDraft(d) {
  if (!d || !emailOK(d.account) || !emailOK(d.to)) throw Error('Choose a Gmail account and a valid recipient.');
  if (typeof d.subject !== 'string' || !d.subject.trim() || d.subject.length > 400 || /[\r\n]/.test(d.subject)) throw Error('Enter a subject on one line, up to 400 characters.');
  if (typeof d.body !== 'string' || !d.body.trim() || d.body.length > 30000) throw Error('Enter a message up to 30,000 characters.');
  if (typeof d.id !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(d.id)) throw Error('Invalid draft request.');
  return {id:d.id, account:d.account.toLowerCase(), to:d.to, subject:d.subject, body:d.body};
}
export function trustedSender(sender, extensionId) {
  if (sender.id !== extensionId) return false;
  try { const u = new URL(sender.url); return u.origin === APP || u.protocol === 'chrome-extension:' && u.hostname === extensionId; } catch { return false; }
}
export function validateQueue(input) {
  const accounts=[...new Set((input?.accounts||[]).map(a=>String(a).toLowerCase()))];
  if(!accounts.length||accounts.length>20||accounts.some(a=>!emailOK(a)))throw Error('Choose at least one open Gmail account.');
  const min=Number(input.minSeconds),max=Number(input.maxSeconds);
  if(!Number.isInteger(min)||!Number.isInteger(max)||min<2||max<min||max>86400)throw Error('Set a delay range from 2 to 86400 seconds, with maximum at least minimum.');
  if(!/^[a-f0-9]{64}$/.test(input.scope||''))throw Error('Workspace session is missing. Refresh Letterdesk.');
  if(!Array.isArray(input.messages)||!input.messages.length||input.messages.length>100)throw Error('Choose 1 to 100 messages per queue.');
  const ids=new Set();
  const jobs=input.messages.map(m=>{if(!Number.isSafeInteger(m.messageId)||m.messageId<1||ids.has(m.messageId))throw Error('Duplicate or invalid message ID.');ids.add(m.messageId);const d=validateDraft({...m,id:String(m.messageId),account:accounts[0]});return {messageId:m.messageId,to:d.to,subject:d.subject,body:d.body,status:'pending'};});
  const fromEmails={};
  for(const account of accounts){const from=String(input.fromEmails?.[account]||account).trim().toLowerCase();if(!emailOK(from))throw Error('Enter a valid Send as address for '+account);fromEmails[account]=from;}
  return {accounts,fromEmails,minSeconds:min,maxSeconds:max,scope:input.scope,jobs};
}
export function nextEligible(accounts,cooldowns,now){return accounts.filter(a=>(cooldowns[a]||0)<=now)}
export function randomDelay(min,max,random=Math.random){return (min+Math.floor(random()*(max-min+1)))*1000}
