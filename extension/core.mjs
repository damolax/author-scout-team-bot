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
