import test from 'node:test';
import assert from 'node:assert/strict';
import {validateDraft,trustedSender} from '../extension/core.mjs';
const valid={id:'request-1',account:'sender@example.com',to:'reader@example.org',subject:'Hello',body:'Halló\nSecond line'};
test('accepts exact unicode body and normalizes account only',()=>{assert.deepEqual(validateDraft({...valid,account:'Sender@Example.com'}),valid)});
test('rejects header injection, bad accounts and oversized drafts',()=>{for(const change of [{subject:'Hi\nBcc: other@example.com'},{to:'a@b.com,c@d.com'},{account:'invalid'},{body:'x'.repeat(30001)},{id:'../x'}])assert.throws(()=>validateDraft({...valid,...change}))});
test('accepts only our app or extension sender',()=>{assert.equal(trustedSender({id:'ext',url:'https://author-scout-team-bot.vercel.app/?tab=messages'},'ext'),true);for(const url of ['https://evil.test','https://author-scout-team-bot.vercel.app.evil.test/','http://author-scout-team-bot.vercel.app/'])assert.equal(trustedSender({id:'ext',url},'ext'),false);assert.equal(trustedSender({id:'other',url:'https://author-scout-team-bot.vercel.app/'},'ext'),false)});
