import test from 'node:test'
import assert from 'node:assert/strict'
import {isPasswordRecovery,withoutSigninHint,shouldTryStoredSession} from './session-policy.js'

test('staging invitation does not sign out returning user',()=>{
 assert.equal(shouldTryStoredSession('https://preview.test/?signin=1','signed-session'),true)
 assert.equal(shouldTryStoredSession('https://preview.test/?signin=1',''),false)
 assert.equal(withoutSigninHint('/?signin=1&tab=services'),'/?tab=services')
})
test('only explicit reset route suppresses session restore',()=>{
 assert.equal(isPasswordRecovery('/reset-password?token=x'),true)
 assert.equal(shouldTryStoredSession('/reset-password?token=x','signed-session'),false)
 assert.equal(shouldTryStoredSession('/?signin=1&tab=services','signed-session'),true)
})
test('keep unrelated URL fragments and parameters',()=>{
 assert.equal(withoutSigninHint('/?signin=1&tab=services#flow'),'/?tab=services#flow')
 assert.equal(withoutSigninHint('/?tab=services'), '/?tab=services')
})
