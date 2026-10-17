// Letter Desk 2.0: provider-neutral branching conversation workflow.
// Labels such as Message0101Yes and Message0101No are user-visible branch names.
// Classification comes ONLY from authorized reply sync or human review.
// This module NEVER sends an email.
export const REPLY_OUTCOMES = Object.freeze([
  'yes', 'no', 'positive', 'question', 'objection', 'not_now', 'negative',
  'opt_out', 'no_reply', 'bounce', 'uncertain'
]);
const TERMINAL_OUTCOMES = new Set(['negative', 'opt_out', 'bounce']);
const VALID_ACTIONS = new Set(['draft_for_review', 'queue_approved', 'stop', 'wait', 'manual_review']);
const NODE_CODE_RE = /^(?:MSG-\d{1,6}|Message\d{2,8}(?:Yes|No|Question|Objection|Later|NoReply|Review|OptOut|Bounce)?)$/;
const RESPONSE_ALIASES = Object.freeze({
  yes: 'yes', no: 'no', positive: 'positive', negative: 'negative',
  question: 'question', objection: 'objection', later: 'not_now',
  not_now: 'not_now', no_reply: 'no_reply', bounced: 'bounce',
  optout: 'opt_out', opt_out: 'opt_out'
});

export function normalizeReplyOutcome(value) {
  return RESPONSE_ALIASES[String(value || '').trim().toLowerCase()] || (REPLY_OUTCOMES.includes(value) ? value : 'uncertain');
}

// The No/OptOut/Bounce nodes are terminal dispositions, NOT messages scheduled to send.
// A polite acknowledgment of a decline, if appropriate, requires separate human approval.
export const EXAMPLE_FLOW = Object.freeze({
  version: 2,
  serviceKey: 'author',
  maxMessagesPerContact: 3,
  maxNoReplyFollowups: 1,
  nodes: [
    { code: 'Message01', stage: 'initial', subject: '', body: '', reviewRequired: true },
    { code: 'Message0101Yes', stage: 'interested', subject: '', body: '', variantGroup: 'interest', reviewRequired: true },
    { code: 'Message0101No', stage: 'terminal', subject: '', body: '', reviewRequired: true },
    { code: 'Message0101Question', stage: 'question', subject: '', body: '', reviewRequired: true },
    { code: 'Message0101Objection', stage: 'objection', subject: '', body: '', reviewRequired: true },
    { code: 'Message0101Later', stage: 'terminal', subject: '', body: '', reviewRequired: true },
    { code: 'Message0101NoReply', stage: 'followup', subject: '', body: '', reviewRequired: true },
    { code: 'Message0201Yes', stage: 'proposal_discussion', subject: '', body: '', reviewRequired: true },
    { code: 'Message0201No', stage: 'alternative', subject: '', body: '', reviewRequired: true },
    { code: 'Message0201Question', stage: 'question', subject: '', body: '', reviewRequired: true },
  ],
  edges: [
    { from: 'Message01', outcome: 'yes', to: 'Message0101Yes', action: 'draft_for_review' },
    { from: 'Message01', outcome: 'positive', to: 'Message0101Yes', action: 'draft_for_review' },
    { from: 'Message01', outcome: 'no', to: null, action: 'stop', branchLabel: 'Message0101No' },
    { from: 'Message01', outcome: 'negative', to: null, action: 'stop', branchLabel: 'Message0101No' },
    { from: 'Message01', outcome: 'question', to: 'Message0101Question', action: 'draft_for_review' },
    { from: 'Message01', outcome: 'objection', to: 'Message0101Objection', action: 'draft_for_review' },
    { from: 'Message01', outcome: 'not_now', to: null, action: 'stop', branchLabel: 'Message0101Later' },
    { from: 'Message01', outcome: 'no_reply', to: 'Message0101NoReply', action: 'draft_for_review' },
    { from: 'Message0101Yes', outcome: 'yes', to: 'Message0201Yes', action: 'draft_for_review' },
    { from: 'Message0101Yes', outcome: 'positive', to: 'Message0201Yes', action: 'draft_for_review' },
    { from: 'Message0101Yes', outcome: 'no', to: 'Message0201No', action: 'draft_for_review' },
    { from: 'Message0101Yes', outcome: 'negative', to: null, action: 'stop' },
    { from: 'Message0101Yes', outcome: 'question', to: 'Message0201Question', action: 'draft_for_review' },
  ]
});

export function validateConversationFlow(flow) {
  const errors = [];
  if (!flow || typeof flow !== 'object') return ['Flow must be an object.'];
  const nodes = Array.isArray(flow.nodes) ? flow.nodes : [];
  const edges = Array.isArray(flow.edges) ? flow.edges : [];
  if (!nodes.length) errors.push('At least one message node is required.');
  if (!nodes.some(n => n.code === 'MSG-01' || n.code === 'Message01')) errors.push('Missing initial Message01 node.');
  if (!Number.isSafeInteger(flow.maxMessagesPerContact) || flow.maxMessagesPerContact < 1 || flow.maxMessagesPerContact > 12) errors.push('maxMessagesPerContact must be 1–12.');
  if (!Number.isSafeInteger(flow.maxNoReplyFollowups) || flow.maxNoReplyFollowups < 0 || flow.maxNoReplyFollowups > 3) errors.push('maxNoReplyFollowups must be 0–3.');

  const nodeCodes = new Set();
  const nodeByCode = new Map();
  for (const n of nodes) {
    if (!NODE_CODE_RE.test(String(n.code || ''))) errors.push('Invalid message code: ' + String(n.code));
    if (nodeCodes.has(n.code)) errors.push('Duplicate message code: ' + n.code);
    nodeCodes.add(n.code);
    nodeByCode.set(n.code, n);
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
    if (e.branchLabel && (!nodeCodes.has(e.branchLabel) || nodeByCode.get(e.branchLabel)?.stage !== 'terminal')) {
      errors.push('Stop branch label must reference an existing terminal node: ' + e.branchLabel);
    }
    if (e.branchLabel && e.action !== 'stop') errors.push('Branch label is only for a stop action.');
    const key = [e.from, e.outcome].join(':');
    if (seen.has(key)) errors.push('Ambiguous transition for ' + key);
    seen.add(key);
  }

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
  const knownOutcome = normalizeReplyOutcome(outcome);
  const edge = (flow.edges || []).find(e => e.from === currentCode && e.outcome === knownOutcome);
  if (TERMINAL_OUTCOMES.has(knownOutcome)) {
    return { action: 'stop', reason: knownOutcome, branchLabel: edge?.branchLabel || null, suppress: knownOutcome === 'opt_out' || knownOutcome === 'negative' };
  }
  if (knownOutcome === 'uncertain') return { action: 'manual_review', reason: 'Reply intent requires human review.' };
  if ((state.messageCount || 0) >= flow.maxMessagesPerContact) return { action: 'stop', reason: 'message_cap_reached' };
  if (knownOutcome === 'no_reply' && (state.noReplyFollowups || 0) >= flow.maxNoReplyFollowups) return { action: 'stop', reason: 'followup_cap_reached' };
  if (!edge) return { action: 'manual_review', reason: 'No approved branch for this situation.' };
  if (edge.action === 'stop') return { action: 'stop', reason: knownOutcome, branchLabel: edge.branchLabel || null, suppress: false };
  if (edge.action === 'wait') return { action: 'wait', nextCode: edge.to || null };
  if (edge.action === 'queue_approved' && !state.campaignApproved) {
    return { action: 'manual_review', reason: 'Campaign approval required.', nextCode: edge.to };
  }
  return { action: edge.action, nextCode: edge.to, needsHumanApproval: edge.action === 'draft_for_review' };
}
