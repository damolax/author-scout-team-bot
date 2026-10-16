// Letter Desk 2.0: pure, provider-agnostic conversation decision graph.
// Classification MUST be supplied by an authorized reply-sync or human reviewer.
// This module never sends email by itself.
export const REPLY_OUTCOMES = Object.freeze([
  'positive', 'question', 'objection', 'not_now', 'negative',
  'opt_out', 'no_reply', 'bounce', 'uncertain'
]);
const TERMINAL_OUTCOMES = new Set(['negative', 'opt_out', 'bounce']);
const VALID_ACTIONS = new Set(['draft_for_review', 'queue_approved', 'stop', 'wait', 'manual_review']);

export const EXAMPLE_FLOW = Object.freeze({
  version: 1,
  serviceKey: 'author',
  maxMessagesPerContact: 3,
  maxNoReplyFollowups: 1,
  nodes: [
    { code: 'MSG-01', stage: 'initial', subject: '', body: '', reviewRequired: true },
    { code: 'MSG-0101', stage: 'interested', subject: '', body: '', variantGroup: 'interest', reviewRequired: true },
    { code: 'MSG-0102', stage: 'question', subject: '', body: '', variantGroup: 'question', reviewRequired: true },
    { code: 'MSG-0103', stage: 'no_reply', subject: '', body: '', variantGroup: 'followup', reviewRequired: true },
    { code: 'MSG-0201', stage: 'proposal_discussion', subject: '', body: '', reviewRequired: true },
  ],
  edges: [
    { from: 'MSG-01', outcome: 'positive', to: 'MSG-0101', action: 'draft_for_review' },
    { from: 'MSG-01', outcome: 'question', to: 'MSG-0102', action: 'draft_for_review' },
    { from: 'MSG-01', outcome: 'objection', to: 'MSG-0102', action: 'draft_for_review' },
    { from: 'MSG-01', outcome: 'not_now', to: null, action: 'stop' },
    { from: 'MSG-01', outcome: 'no_reply', to: 'MSG-0103', action: 'draft_for_review' },
    { from: 'MSG-0101', outcome: 'positive', to: 'MSG-0201', action: 'draft_for_review' },
    { from: 'MSG-0101', outcome: 'question', to: 'MSG-0102', action: 'draft_for_review' },
  ]
});

export function validateConversationFlow(flow) {
  const errors = [];
  if (!flow || typeof flow !== 'object') return ['Flow must be an object.'];
  const nodes = Array.isArray(flow.nodes) ? flow.nodes : [];
  const edges = Array.isArray(flow.edges) ? flow.edges : [];
  if (!nodes.length) errors.push('At least one message node is required.');
  if (!nodes.some(n => n.code === 'MSG-01')) errors.push('Missing initial MSG-01 node.');
  if (!Number.isSafeInteger(flow.maxMessagesPerContact) || flow.maxMessagesPerContact < 1 || flow.maxMessagesPerContact > 12) errors.push('maxMessagesPerContact must be 1–12.');
  if (!Number.isSafeInteger(flow.maxNoReplyFollowups) || flow.maxNoReplyFollowups < 0 || flow.maxNoReplyFollowups > 3) errors.push('maxNoReplyFollowups must be 0–3.');

  const nodeCodes = new Set();
  for (const n of nodes) {
    if (!/^MSG-\d{1,6}$/.test(String(n.code || ''))) errors.push('Invalid message code: ' + String(n.code));
    if (nodeCodes.has(n.code)) errors.push('Duplicate message code: ' + n.code);
    nodeCodes.add(n.code);
    if (typeof n.body !== 'string') errors.push('Message body must be text: ' + n.code);
  }
  const seen = new Set();
  for (const e of edges) {
    if (!nodeCodes.has(e.from)) errors.push('Unknown source node: ' + e.from);
    if (e.to && !nodeCodes.has(e.to)) errors.push('Unknown target node: ' + e.to);
    if (!REPLY_OUTCOMES.includes(e.outcome)) errors.push('Unknown outcome: ' + e.outcome);
    if (!VALID_ACTIONS.has(e.action)) errors.push('Invalid action: ' + e.action);
    if (TERMINAL_OUTCOMES.has(e.outcome) && (e.to || e.action !== 'stop')) {
      errors.push('Terminal outcome must stop: ' + e.outcome);
    }
    if (e.action === 'stop' && e.to) errors.push('Stopped edge must have no target.');
    const key = [e.from, e.outcome].join(':');
    if (seen.has(key)) errors.push('Ambiguous transition for ' + key);
    seen.add(key);
  }

  // Cycles can cause repeated outreach; prohibit before publication.
  const adjacency = new Map(nodes.map(n => [n.code, []]));
  for (const e of edges) if (adjacency.has(e.from) && e.to && adjacency.has(e.to)) adjacency.get(e.from).push(e.to);
  const visiting = new Set(), visited = new Set();
  function visit(code) {
    if (visiting.has(code)) { errors.push('Cycle detected near ' + code); return; }
    if (visited.has(code)) return;
    visiting.add(code);
    for (const next of adjacency.get(code) || []) visit(next);
    visiting.delete(code);
    visited.add(code);
  }
  for (const n of nodes) visit(n.code);
  return [...new Set(errors)];
}

export function resolveConversationTransition(flow, currentCode, outcome, state = {}) {
  const knownOutcome = REPLY_OUTCOMES.includes(outcome) ? outcome : 'uncertain';
  if (TERMINAL_OUTCOMES.has(knownOutcome)) {
    return { action: 'stop', reason: knownOutcome, suppress: knownOutcome === 'opt_out' || knownOutcome === 'negative' };
  }
  if (knownOutcome === 'uncertain') return { action: 'manual_review', reason: 'Reply intent requires human review.' };
  if ((state.messageCount || 0) >= flow.maxMessagesPerContact) return { action: 'stop', reason: 'message_cap_reached' };
  if (knownOutcome === 'no_reply' && (state.noReplyFollowups || 0) >= flow.maxNoReplyFollowups) return { action: 'stop', reason: 'followup_cap_reached' };
  const edge = (flow.edges || []).find(e => e.from === currentCode && e.outcome === knownOutcome);
  if (!edge) return { action: 'manual_review', reason: 'No approved branch for this situation.' };
  if (edge.action === 'stop') return { action: 'stop', reason: knownOutcome };
  if (edge.action === 'wait') return { action: 'wait', nextCode: edge.to || null };
  // Even the queue_approved setting does not approve content or override sender consent.
  if (edge.action === 'queue_approved' && !state.campaignApproved) {
    return { action: 'manual_review', reason: 'Campaign approval required.', nextCode: edge.to };
  }
  return { action: edge.action, nextCode: edge.to, needsHumanApproval: edge.action === 'draft_for_review' };
}
