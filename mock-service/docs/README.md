# Mock Service

A reusable Express.js/TypeScript server for simulating external APIs during development and testing.

## Quick Start

```bash
cd mock-service
npm install
npm run dev      # Start with hot-reload (tsx watch)
```

**Startup seeding:** The server automatically seeds the 4 default BRP test cases on startup, so you don’t need to run the seed script for normal use. To disable (e.g. no test data): set `SEED_DEFAULT_TEST_CASES=0`. To reseed via HTTP when the server is already running: `npm run seed`.

## How It Works

1. Drop a JSON file in `mocks/` — it defines a mock API endpoint
2. The server reads all `mocks/*.json` files at startup and registers Express routes
3. Template expressions (`{{faker.*}}`, `{{request.*}}`, `{{now}}`) are resolved at request time
4. If `persistenceKey` is set, responses are cached in SQLite — same key = same data every time  
5. On startup, the server seeds the default BRP test cases (clean approval, document mismatch, sanctions, PEP) so they’re available immediately; SQLite is ephemeral across restarts unless you use persistent storage (e.g. `MOCK_DATA_DIR` on a mounted volume).

## Adding a New Mock

Create a JSON file in `mocks/` with this structure:

```json
{
  "id": "my-api",
  "name": "My External API",
  "description": "What this mock simulates",
  "method": "POST",
  "path": "/api/v1/my-endpoint",
  "request": {
    "body": {
      "fieldName": { "type": "string", "required": true }
    }
  },
  "response": {
    "status": 200,
    "persistenceKey": "{{fieldName}}",
    "schema": {
      "id": "{{faker.string.uuid}}",
      "name": "{{faker.person.fullName}}",
      "input": "{{request.fieldName}}",
      "timestamp": "{{now}}"
    }
  }
}
```

### Template Expressions

| Expression | Description | Example |
|-----------|-------------|---------|
| `{{faker.*}}` | Any faker.js method | `{{faker.person.firstName}}`, `{{faker.string.numeric(9)}}` |
| `{{request.fieldName}}` | Value from request body | `{{request.documentNumber}}` |
| `{{now}}` | Current ISO timestamp | `2025-01-15T10:00:00.000Z` |

### Persistence

Set `persistenceKey` to a template that produces a unique key per request. The first call generates data via faker and stores it in SQLite; subsequent calls with the same key return the cached response.

## Admin Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/mocks` | List all registered mock endpoints |
| GET | `/admin/data/:mockId` | List all persisted records for a mock |
| DELETE | `/admin/data/:mockId/:key` | Delete a specific record |
| POST | `/admin/data/:mockId` | Seed a record (`{ "key": "...", "data": {...} }`) |

## Deploying to AWS Elastic Beanstalk

See **[docs/ELASTIC-BEANSTALK.md](docs/ELASTIC-BEANSTALK.md)** for EB config, SQLite setup, and CloudFormation deploy. **Deploy from repo root:** `./scripts/deploy_mock_service.sh` (templates in **`templates/mock-service/`**). Deploy mock-service first so the agent can use the Beanstalk URL as `BRP_API_URL`.

---

## Directory Structure

```
mock-service/
├── src/
│   ├── server.ts                    # Express entrypoint + admin routes
│   ├── routes/dynamic-router.ts     # Reads mocks/*.json, registers routes
│   ├── middleware/
│   │   ├── faker-generator.ts       # Resolves {{faker.*}} templates
│   │   └── persistence.ts           # SQLite lookup-or-create
│   └── utils/template.ts            # Template interpolation engine
├── mocks/                           # Mock endpoint definitions (JSON)
├── seeds/                           # Seed scripts for test data
├── data/                            # Auto-created SQLite database
└── docs/                            # API-specific documentation
    └── apis/
```

## API Documentation

See `docs/apis/` for detailed documentation on each mocked API:
- [BRP Identity Verification](docs/apis/brp-identity-verification.md)
