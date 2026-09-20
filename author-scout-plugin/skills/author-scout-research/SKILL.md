---
name: author-scout-research
description: Research Author Scout authors deeply and prepare personalized first outreach messages.
---

Use the Author Scout MCP tools when the user asks to research, inspect, continue, or message authors from Author Scout.

## Workflow

1. Confirm the connected Author Scout account with `get_profile` when account identity matters.
2. Use `get_unresearched_authors` to fetch the next requested batch. Default to 25 when the user does not specify a number.
3. Treat each Author Scout Research Seed as the starting point, not as final proof.
4. Research each author deeply with the web/research capabilities available in the current ChatGPT conversation.
5. Verify important factual claims against reliable public sources.
6. Do not invent an author email, website, book, representation status, project, publication date, rights status, or current activity.
7. Do not claim to have read a work unless the evidence actually supports that claim.
8. Identify the author's current moment, project stage, publishing context, audience/platform signals, realistic opportunities, already-solved needs, counter-evidence, and the strongest outreach angle.
9. Create the first message in the author's appropriate language first, then a complete English version.
10. Keep the subject line separate from the body.
11. The first 2–3 sentences should demonstrate specific verified research.
12. Avoid em dashes and double-dash punctuation.
13. Keep the message human, professional, useful, and non-pushy.
14. Where `save_author_research` is available, save the verified research and first message back to Author Scout after completing each author. This action must never send email.
15. If write-back is unavailable on the user's ChatGPT surface or plan, present the finished results clearly in the conversation instead of pretending they were saved.
16. Use `get_message_queue` when the user asks to review messages already prepared in Author Scout.

## Important safety and ownership rules

- Only work with authors returned by the connected user's Author Scout account.
- Never attempt to access another Author Scout user's authors.
- Never send email from this plugin.
- Saving research is not permission to contact the author.
- Preserve source URLs so the user can audit the research.
