// Phase 8: ?signin=1 is a navigation hint, never a revoke/logout signal.
// Returning visitors should remain signed in until they use the Sign out control.
export function isPasswordRecovery(url){
  const u=new URL(url,'https://letterdesk.invalid')
  return u.pathname==='/reset-password'||u.searchParams.has('token')||u.searchParams.has('error')
}
export function withoutSigninHint(url){
  const u=new URL(url,'https://letterdesk.invalid')
  u.searchParams.delete('signin')
  return u.pathname+(u.searchParams.toString()?'?'+u.searchParams.toString():'')+u.hash
}
export function shouldTryStoredSession(url,sessionKey){
  return !isPasswordRecovery(url)&&Boolean(String(sessionKey||'').trim())
}
