# Edupreneurs Admin (AD-1 prototype)

Desktop-first React + TypeScript web console, **synthetic fixtures only**. No server, no credentials, no network:
the production build ships `connect-src 'none'`. Full documentation: [`docs/admin-01/`](../../docs/admin-01/README.md).

```
cd apps/admin-web
npm ci
npm run dev        # http://127.0.0.1:5174  (demo persona: ?persona=p-chloe)
npm run verify     # typecheck + lint + tests + source scan + build + dist scan
npm run screenshots  # real Chrome screenshots of the build -> docs/admin-01/screenshots (needs Chrome)
```

It does not import from `apps/student-native` or `services/api`, and touches no database.
