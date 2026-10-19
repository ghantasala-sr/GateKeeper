# Running Gatekeeper locally

## One-time setup

```bash
cp .env.example .env               # then fill in the values (see the comments)
docker compose up -d               # Postgres (port 5434) and Keycloak (port 8080)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m scripts.gen_signing_key   # paste its output over TOKEN_SIGNING_KEY_B64=change-me in .env
.venv/bin/python -m scripts.migrate                      # tables, roles, RLS, audit
.venv/bin/python -m scripts.setup_keycloak               # Globex realm, SAML client, users
.venv/bin/python -m scripts.seed                         # companies, users, documents
.venv/bin/python -m app.rag.ingest                       # chunks + embeddings
cd ../frontend && npm install
```

Okta (Acme) needs an Integrator Free Plan org with an OIDC web app, the
`gk-employee` / `gk-hr-manager` / `gk-admin` groups, and a `groups` ID-token
claim; set `OKTA_ISSUER`, `OKTA_CLIENT_ID`, and `OKTA_CLIENT_SECRET` in `.env`.
The chat model needs `ANTHROPIC_API_KEY`.

## Every time

```bash
docker compose up -d
cd backend && .venv/bin/uvicorn app.main:app --reload     # API on :8000
cd frontend && npm run dev                                # UI on :3000
```

For SCIM provisioning from Okta, also run `ngrok http 8000` and create a
company's SCIM token with `.venv/bin/python -m scripts.create_scim_token "Acme Corp"`.

## Tests

```bash
cd backend && .venv/bin/python -m pytest                  # 225 tests, no API cost
RUN_LIVE=1 .venv/bin/python -m pytest tests/test_injection_live.py -s   # real Claude, a few cents
```

The suite needs Postgres running, migrated, seeded, and ingested. It removes the
audit rows it writes; don't run it against an audit log you need to keep.

## Test users

| Company | Sign in with | Users |
|---|---|---|
| Acme Corp | Okta | `employee@`, `hr.manager@`, `admin@acme.example` (passwords set in Okta) |
| Globex | SAML (Keycloak) | `employee@`, `hr.manager@`, `admin@globex.example` (password: `GLOBEX_TEST_PASSWORD` in `.env`) |
