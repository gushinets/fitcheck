# ADR 001: Standalone FitCheck backend

Status: accepted, 2026-10-11. Owner: ANY-643.

FitCheck owns its API, PostgreSQL, identity, quotas and workers. anytoolai-platform is an architectural reference only: no package imports, shared database, runtime dependency or platform integration.

Use one modular Python package in backend/: API and future worker call application services, which use repositories/provider gateways. HTTP handlers do not contain domain rules. Provider secrets and prompts remain server-side. API and worker are separate processes; database migrations run once before deployment. A single repository keeps contracts, clients and implementation aligned. Microservices and workflow kernels are unnecessary at this stage.

ANY-643 implements API startup, health, error boundaries and contracts. Planned business operations are exported separately from live OpenAPI, with implementation state and owning issue; no successful runtime stubs. Next.js APIs and local web/extension persistence remain until ANY-653.

Sequence: ANY-644 storage → ANY-645 auth → ANY-646 profiles; ANY-647 extraction and ANY-648 LLM gateway follow foundation; ANY-649 durable jobs combines them; ANY-650/651/652 history, guest quotas and import; ANY-653 client integration; ANY-654 deployment/backups/production validation. At integration, protect or disable old Next.js LLM routes to avoid bypassing identity/quota policies.

Web uses secure HttpOnly same-origin cookies with Origin/CSRF validation; extension uses browser login, one-time code/PKCE S256 and scoped bearer tokens. Importing local email/password never proves server identity. Current Dokploy fitcheck-dev is unchanged by foundation work.
