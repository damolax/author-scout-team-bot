import test from 'node:test';
import assert from 'node:assert/strict';
import { SERVICE_MODES, mapImportRow, getImportColumns } from './service-modes.js';
import { EXAMPLE_FLOW, validateConversationFlow, resolveConversationTransition, normalizeReplyOutcome } from './conversation-flow.js';

test('six service workspaces have distinct schemas', () => {
  assert.equal(SERVICE_MODES.length, 6);
  assert.equal(new Set(SERVICE_MODES.map(s => s.key)).size, 6);
  for (const service of SERVICE_MODES) assert.ok(getImportColumns(service.key).specific.length);
});

test('legacy author workbook maps without changing its four-column format', () => {
  const r = mapImportRow('author', { Author: 'Example Author', Email: 'Author@Example.org', Subject: 'Your book', 'First Message': 'I enjoyed your essay.' });
  assert.equal(r.name, 'Example Author');
  assert.equal(r.email, 'author@example.org');
  assert.equal(r.message.body, 'I enjoyed your essay.');
  assert.equal(r.state, 'message_review');
  assert.equal(r.ready_to_send, false);
});

test('a business can be imported without a first message', () => {
  const r = mapImportRow('automation', { 'Business Name': 'Example Business', Website: 'https://example.org', 'Manual Workflow Signal': 'Manual spreadsheet handoffs' });
  assert.equal(r.state, 'lead_needs_template');
  assert.equal(r.message.body, '');
  assert.equal(r.service_data.workflow_signal, 'Manual spreadsheet handoffs');
});

test('each service can import a lead with distinct fields and no first message', () => {
  const cases = [
    ['website-design', {'Business Name': 'Acme', 'Website URL': 'https://acme.test', 'Website Issue': 'Broken mobile layout'}],
    ['digital-planner', {'Shop Name': 'Example Shop', 'Storefront URL': 'https://shop.test', 'Planner Niche': 'Teacher templates'}],
    ['shopify', {'Store Name': 'Example Store', 'Shopify Store URL': 'https://store.test', 'Store Issue': 'Broken cart'}],
    ['google-maps', {'Business Name': 'Example Cafe', 'Google Maps URL': 'https://maps.google.com/?q=cafe', 'Listing Observation': 'No website linked'}],
  ];
  for (const [mode, row] of cases) {
    const result = mapImportRow(mode, row);
    assert.equal(result.errors.length, 0, mode + ': ' + result.errors.join('; '));
    assert.equal(result.state, 'lead_needs_template');
  }
});

test('suppression and invalid emails block send eligibility', () => {
  assert.equal(mapImportRow('author', {Author:'Test',Email:'bad-email'}).state, 'invalid');
  const r = mapImportRow('author', {Author:'Test',Email:'test@example.org','Do Not Contact':'yes','First Message':'Hi'});
  assert.equal(r.state, 'suppressed');
  assert.equal(r.ready_to_send, false);
});

test('message 01 plus follow-up branch columns can be carried as variants', () => {
  const r = mapImportRow('author', { Author: 'Example', Email: 'example@example.org', 'Message 01': 'Hello', 'Message 0101': 'Thank you for your interest', 'Message 0102': 'Happy to answer the question' });
  assert.equal(r.message.versions.length, 3);
  assert.equal(r.message.versions[0].code, 'MSG-01');
  assert.equal(r.message.versions[1].code, 'MSG-0101');
  assert.equal(r.message.body, 'Hello');
});

test('example branching flow is valid', () => {
  assert.deepEqual(validateConversationFlow(EXAMPLE_FLOW), []);
});

test('positive and question replies yield different reviewed branches', () => {
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message01', 'positive').nextCode, 'Message0101Yes');
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message01', 'question').nextCode, 'Message0101Question');
});

test('declines and opt-outs stop; unknown replies require review', () => {
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message01', 'negative').action, 'stop');
  const decline = resolveConversationTransition(EXAMPLE_FLOW, 'Message01', 'opt_out');
  assert.equal(decline.suppress, true);
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message01', 'uncertain').action, 'manual_review');
});

test('caps stop repeated outreach, cycles are rejected', () => {
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message01', 'no_reply', {noReplyFollowups: 1}).action, 'stop');
  const cyclic = { ...EXAMPLE_FLOW, edges: [...EXAMPLE_FLOW.edges, { from:'Message0201Yes', outcome:'question', to:'Message01', action:'draft_for_review'}] };
  assert.ok(validateConversationFlow(cyclic).some(x=>x.includes('Cycle')));
});

test('Message01 can lead to specifically named Message0101Yes and Message0101No branches', () => {
  assert.equal(normalizeReplyOutcome('Yes'), 'yes');
  assert.equal(normalizeReplyOutcome('No'), 'no');
  const yes = resolveConversationTransition(EXAMPLE_FLOW, 'Message01', 'Yes');
  assert.equal(yes.nextCode, 'Message0101Yes');
  assert.equal(yes.action, 'draft_for_review');
  const no = resolveConversationTransition(EXAMPLE_FLOW, 'Message01', 'No');
  assert.equal(no.branchLabel, 'Message0101No');
  assert.equal(no.action, 'stop');
  assert.equal(no.suppress, false);
});

test('Yes branch can branch again into Message0201Yes or Message0201No', () => {
  const yes = resolveConversationTransition(EXAMPLE_FLOW, 'Message0101Yes', 'Yes');
  const no = resolveConversationTransition(EXAMPLE_FLOW, 'Message0101Yes', 'No');
  assert.equal(yes.nextCode, 'Message0201Yes');
  assert.equal(no.nextCode, 'Message0201No');
  assert.equal(no.action, 'draft_for_review');
  assert.equal(no.needsHumanApproval, true);
});

test('branch-labeled workbook columns import without accidentally approving sending', () => {
  const r = mapImportRow('author', {
    Author: 'Sample Author',
    Email: 'author@example.org',
    'Message 01': 'Hello',
    Message0101Yes: 'Wonderful, tell me more',
    Message0101No: 'Thank you for your time',
    Message0101Question: 'Happy to explain'
  });
  assert.deepEqual(new Set(r.message.versions.map(v => v.code)),
    new Set(['MSG-01', 'Message0101Yes', 'Message0101No', 'Message0101Question']));
  assert.equal(r.message.versions.find(v => v.code === 'Message0101No').autoSendEligible, false);
  assert.equal(r.message.versions.every(v => v.autoSendEligible === false), true);
});

test('explicit negative and unsubscribe differ from a contextual No answer', () => {
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message0101Yes', 'negative').action, 'stop');
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message0101Yes', 'negative').suppress, true);
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message0101Yes', 'opt_out').suppress, true);
  assert.equal(resolveConversationTransition(EXAMPLE_FLOW, 'Message0101Yes', 'no').nextCode, 'Message0201No');
});
