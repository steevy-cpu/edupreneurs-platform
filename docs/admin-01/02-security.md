# Security notes

## What the browser contains
Synthetic fixtures, French strings, no key, URL, token or student data. `scripts/check-dist.mjs` scans the **built** assets for service-role
keys, Supabase hosts, JWTs, Postgres URLs, OpenRouter/OpenAI-style keys, private keys, payment secrets, local API ports and any unexpected
`http(s)://` URL; it also verifies the CSP and that no source map ships. `scripts/check-source.mjs` + ESLint forbid raw HTML
(`dangerouslySetInnerHTML`, `innerHTML`…), `fetch`/XHR/WebSocket, `localStorage`/`sessionStorage`/cookies, `eval`, `import.meta.env` and URLs in source.

## CSP (built html)
`default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'`.
No inline script or style anywhere (layout uses classes and SVG attributes), so `unsafe-inline` is never needed. `connect-src 'none'` makes “no network”
browser-enforced. A real deployment must also send it as an HTTP header with `frame-ancestors 'none'` and `Referrer-Policy: no-referrer` (a meta tag cannot).

## Role preview ≠ authentication
The dashed “Aperçu de rôle (synthétique, pas une connexion)” selector switches a persona in memory. There is no login, password, token, session, MFA
or staff identity. Hiding menus/buttons is convenience; **FastAPI (and the `staff.*` SQL functions) must decide every request**, with a 403 test for
each role × route (Admin-00 docs 4–5). Hidden sections also refuse their URL in the demo, which proves nothing about the server.

## Step-up and audit
Publish/withdraw/rollback dialogs show “Step-up MFA non implémenté” and produce a **synthetic** receipt (`SYN-0001`) labelled as such. Real receipts and
audit rows are written by the server, never by the browser.

## Not built, by design
Staff auth, MFA, session handling, API client, any hosted-service connection, any deployment. Gates in Admin-00 doc 5 §8 remain closed.
