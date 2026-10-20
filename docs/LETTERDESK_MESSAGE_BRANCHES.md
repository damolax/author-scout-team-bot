# Letter Desk — message branch naming convention

This naming system applies across all six service workspaces.

## Exactly how the user labels branches

```text
Message01            — First approved outreach
├─ Yes               → Message0101Yes
│  ├─ Yes             → Message0201Yes
│  ├─ No              → Message0201No
│  └─ Question        → Message0201Question
├─ No                → Message0101No [stop if declining further contact]
├─ Question          → Message0101Question
├─ Objection         → Message0101Objection
├─ Not now           → Message0101Later [stop/pause]
└─ No reply          → Message0101NoReply [only if follow-up approved]
```

- Human labels such as `Message0101Yes` and `Message0101No` are accepted as column names in Excel/CSV uploads.
- Node IDs and branch labels are different concepts. A branch may reference a message to draft, or a terminal decision with nothing to send.
- Any `Yes`/`No` answer must be interpreted in context of the preceding question. A contextual `No` can lead to a *reviewed* alternative reply; it is not inherently an opt-out.
- Explicit decline or opt-out stops outreach; do not auto-send a "No" script afterward. Hard bounces stop outbound attempts too.
- Send-as identity, approved message, branch conditions, consent/compliance, and outreach caps still gate all sends.
- Replies of uncertain intent route for human review; complex quotes, commitments, sensitive objections, and contractual questions require human review.
- Every message supports multiple variants within the branch, with one published version chosen by user or explicit preapproved rules, not arbitrary random swapping.
- Store the branch transition along with the incoming reply evidence and the workflow/template version; never confuse "drafted" with "sent".

## Upload example

`Author,Email,Message 01,Message0101Yes,Message0101No,Message0101Question,Message0201Yes,Message0201No`

All message columns are optional. The importer creates only draft/review records and does not auto-send anything.

## Current implementation status

Core JavaScript import naming and branching decision contracts exist on the feature branch; the live UI, send workers, reply classification, and database persistence are **not** wired together yet. This document specifies behavior to implement in the dedicated Conversation Builder during Phase 5.
