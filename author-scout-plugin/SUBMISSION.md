# Author Scout public plugin submission notes

## Intended audience
Personal ChatGPT users, including Plus and lower plans where the public Author Scout plugin is available.

## No OpenAI API billing dependency
The Author Scout backend does not call paid OpenAI models for this plugin workflow. ChatGPT performs the reasoning in the user's ChatGPT session.

## MCP endpoint
https://author-scout-team-bot.onrender.com/mcp

## OAuth
Author Scout exposes OAuth 2.1-style authorization endpoints with PKCE:
- Resource metadata: https://author-scout-team-bot.onrender.com/.well-known/oauth-protected-resource
- Authorization-server metadata: https://author-scout-team-bot.onrender.com/.well-known/oauth-authorization-server
- Authorization endpoint: https://author-scout-team-bot.onrender.com/oauth/authorize
- Token endpoint: https://author-scout-team-bot.onrender.com/oauth/token

The user generates a short-lived one-time ChatGPT connection code from Author Scout Web. The code is consumed during OAuth account linking and is not sent to the MCP model as tool data.

## Tools
- get_profile (read)
- get_unresearched_authors (read)
- get_my_authors (read)
- get_author (read)
- save_author_research (write, non-destructive, does not send email)
- get_message_queue (read)

## External side effects
The plugin never sends author email. Gmail sending remains a separate Author Scout action requiring the user's explicit action/approval.

## Submission prerequisites
OpenAI's public-plugin submission flow requires a verified developer or business identity in the OpenAI platform submission portal. Publication is subject to OpenAI review and plan/region availability.
