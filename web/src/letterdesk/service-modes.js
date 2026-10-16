// Letter Desk 2.0 service contracts. No database, browser, or provider dependency.
export const SERVICE_MODES = Object.freeze([
  { key: 'author', label: 'Author Scouting', noun: 'Author', primaryName: 'author_name',
    fields: { author_name: ['author', 'author name', 'writer'], books: ['book titles', 'books', 'published books'], genre: ['genre'], publication: ['recent publication', 'publication date'], publisher: ['publisher'], author_profile: ['author profile', 'author linkedin'], recent_activity: ['recent activity'], literary_angle: ['literary angle'], email_source_url: ['email source url'] } },
  { key: 'automation', label: 'Automation Scouting', noun: 'Business', primaryName: 'business_name',
    fields: { business_name: ['business name', 'company', 'company name'], business_type: ['business type', 'industry'], current_tools: ['current tools', 'tech stack'], workflow_signal: ['manual workflow signal', 'workflow problem'], integration_opportunity: ['integration opportunity', 'automation need'], evidence_url: ['opportunity evidence url', 'evidence url'] } },
  { key: 'website-design', label: 'Website Design Scouting', noun: 'Business', primaryName: 'business_name',
    fields: { business_name: ['business name', 'company'], website_issue: ['website issue', 'web issue'], issue_page_url: ['page url', 'issue page url'], ux_observation: ['ux observation', 'ux/accessibility observation', 'accessibility issue'], website_technology: ['website technology', 'cms'], evidence_url: ['evidence url'] } },
  { key: 'digital-planner', label: 'Digital Planner Scouting', noun: 'Creator or Shop', primaryName: 'shop_name',
    fields: { shop_name: ['creator or shop name', 'creator name', 'shop name'], storefront_url: ['storefront url', 'shop url'], planner_niche: ['planner niche', 'niche'], product_type: ['product type'], product_url: ['product url'], audience: ['audience'], evidence_url: ['opportunity evidence url', 'evidence url'] } },
  { key: 'shopify', label: 'Shopify Scouting', noun: 'Store', primaryName: 'store_name',
    fields: { store_name: ['store name', 'shop name'], store_url: ['shopify store url', 'store url'], product_category: ['product category', 'store niche'], store_issue: ['store issue', 'checkout issue'], issue_page_url: ['issue page url', 'product url'], ecommerce_opportunity: ['ecommerce opportunity'], evidence_url: ['evidence url'] } },
  { key: 'google-maps', label: 'Google Maps Scouting', noun: 'Local Business', primaryName: 'business_name',
    fields: { business_name: ['business name', 'place name'], maps_url: ['google maps url', 'maps url', 'map link'], place_id: ['google place id', 'place id'], category: ['business category', 'category'], address: ['address'], listing_observation: ['listing observation', 'google business profile observation'], evidence_url: ['evidence url'] } },
]);

export const COMMON_IMPORT_FIELDS = Object.freeze({
  name: ['name', 'lead name', 'contact name'],
  email: ['email', 'email address', 'contact email', 'public professional email', 'recipient'],
  website: ['website', 'website url', 'business website', 'author website'],
  country: ['country'],
  city: ['city', 'location'],
  source_url: ['source url', 'discovery source', 'source link'],
  evidence_notes: ['evidence notes', 'research notes', 'notes'],
  subject: ['subject', 'subject line', 'message 01 subject'],
  first_message: ['first message', 'initial message', 'message 01', 'message 1', 'email body'],
  first_message_english: ['first message english', 'first message (english)', 'message english'],
  do_not_contact: ['do not contact', 'dnc', 'opt out', 'opted out'],
});

export function normalizeHeader(value) {
  return String(value ?? '').normalize('NFKC').toLowerCase().trim().replace(/[_\-]+/g, ' ').replace(/[^\p{L}\p{N} ]/gu, ' ').replace(/\s+/g, ' ');
}

export function getServiceMode(key) {
  const mode = SERVICE_MODES.find((s) => s.key === key);
  if (!mode) throw new Error('Unsupported Letter Desk service mode: ' + String(key));
  return mode;
}

function indexedRow(row) {
  const index = new Map();
  for (const [key, value] of Object.entries(row || {})) {
    if (value == null || String(value).trim() === '') continue;
    const normalized = normalizeHeader(key);
    if (!index.has(normalized)) index.set(normalized, String(value).trim());
  }
  return index;
}

function pick(index, aliases) {
  for (const alias of aliases) {
    const value = index.get(normalizeHeader(alias));
    if (value) return value;
  }
  return '';
}

function isAffirmative(value) {
  return /^(true|yes|y|1|opted out|unsubscribe|unsubscribed)$/i.test(String(value || '').trim());
}

export function mapImportRow(serviceKey, row) {
  const mode = getServiceMode(serviceKey);
  const index = indexedRow(row);
  const common = Object.fromEntries(Object.entries(COMMON_IMPORT_FIELDS).map(([key, aliases]) => [key, pick(index, aliases)]));
  const serviceData = Object.fromEntries(Object.entries(mode.fields).map(([key, aliases]) => [key, pick(index, aliases)]));
  const name = common.name || serviceData[mode.primaryName] || '';
  const website = common.website || serviceData.store_url || serviceData.storefront_url || serviceData.author_profile || '';
  const mapsUrl = serviceData.maps_url || '';
  const email = common.email.toLowerCase();
  const optedOut = isAffirmative(common.do_not_contact);
  const errors = [];
  if (!name) errors.push('Missing prospect name.');
  if (!email && !website && !mapsUrl && !serviceData.place_id) errors.push('Provide an email, website, Google Maps URL, or Place ID.');
  if (email && !/^[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+$/.test(email)) errors.push('Email format is invalid.');

  const messageVersions = [];
  const messageKeys = new Set();
  for (const [column, value] of index.entries()) {
    // Headers: Message 01, Message0101Yes, Message0101No,
    // Message 0101 Question. The suffix is a branch label, not send approval.
    const match = column.replace(/\s+/g, '').match(/^message(\d{1,8})(yes|no|question|objection|later|noreply|review|optout|bounce)?$/i);
    if (match) {
      const suffixLabels = { yes: 'Yes', no: 'No', question: 'Question', objection: 'Objection', later: 'Later', noreply: 'NoReply', review: 'Review', optout: 'OptOut', bounce: 'Bounce' };
      const suffix = suffixLabels[(match[2] || '').toLowerCase()] || '';
      const code = suffix ? 'Message' + match[1] + suffix : 'MSG-' + match[1];
      if (!messageKeys.has(code)) {
        messageKeys.add(code);
        messageVersions.push({
          code, body: value, reviewRequired: true,
          terminal: ['OptOut', 'Bounce'].includes(suffix),
          autoSendEligible: false
        });
      }
    }
  }
  messageVersions.sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }));

  return {
    service_key: mode.key,
    name,
    email,
    website,
    maps_url: mapsUrl,
    country: common.country,
    city: common.city,
    source_url: common.source_url,
    evidence_notes: common.evidence_notes,
    service_data: serviceData,
    message: { subject: common.subject, body: common.first_message, body_english: common.first_message_english, versions: messageVersions },
    do_not_contact: optedOut,
    errors,
    state: errors.length ? 'invalid' : optedOut ? 'suppressed' : common.first_message ? 'message_review' : 'lead_needs_template',
    ready_to_send: false, // File import never authorizes delivery.
  };
}

export function getImportColumns(serviceKey) {
  const mode = getServiceMode(serviceKey);
  return { common: Object.keys(COMMON_IMPORT_FIELDS), specific: Object.keys(mode.fields), optionalMessages: true };
}
