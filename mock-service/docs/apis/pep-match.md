# PEP Match API (Politically Exposed Persons)

Mock endpoint for PEP/sanctions screening, following the **OpenSanctions** match API style and **FollowTheMoney (FtM)** entity format.

## Real API Reference

| | |
|---|---|
| **API Name** | OpenSanctions Match API |
| **Maintained by** | OpenSanctions / OpenSanctions Datenbanken GmbH |
| **Docs** | https://opensanctions.org/docs/api/matching/ |
| **Entity format** | https://opensanctions.org/docs/entities/ |
| **Real endpoint** | `POST https://api.opensanctions.org/match/default` |
| **Auth** | API key (Authorization: ApiKey …) |

## Our Mock Endpoint

```
POST /api/v1/pep/match
```

### Request

Body must contain a `queries` object. Each key is a query id; the mock echoes and returns results for **`q1`**. Use `q1` for a single screening request.

```json
{
  "queries": {
    "q1": {
      "schema": "Person",
      "properties": {
        "firstName": ["Jan"],
        "lastName": ["de Vries"],
        "birthDate": ["1985"],
        "nationality": ["Netherlands"]
      }
    }
  }
}
```

- **schema**: `"Person"` or `"Company"`.
- **properties**: FollowTheMoney-style; values are **arrays** (e.g. multiple name spellings). Common keys:
  - Person: `firstName`, `lastName`, `name`, `birthDate`, `nationality`, `idNumber`, …
  - Company: `name`, `jurisdiction`, `registrationNumber`, …

### Response (200 OK)

Structure mirrors OpenSanctions: per-query id you get a **query** (echo of the request entity) and **results** (list of matching entities in FtM format).

```json
{
  "responses": {
    "q1": {
      "query": {
        "schema": "Person",
        "properties": {
          "firstName": ["Jan"],
          "lastName": ["de Vries"],
          "birthDate": ["1985"],
          "nationality": ["Netherlands"]
        }
      },
      "results": [
        {
          "id": "NK-a1b2c3d4",
          "schema": "Person",
          "caption": "Jane Smith",
          "datasets": ["pep_world"],
          "referents": ["pep-123456"],
          "first_seen": "2020-01-15T00:00:00.000Z",
          "last_change": "2025-03-11T12:00:00.000Z",
          "properties": {
            "name": ["Jane Smith"],
            "firstName": ["Jane"],
            "lastName": ["Smith"],
            "birthDate": ["1975"],
            "nationality": ["us"],
            "position": ["Politician"]
          }
        }
      ]
    }
  }
}
```

- **query**: Echo of the request entity for `q1`.
- **results**: Array of matching entities (PEP/sanctions). Each entity has:
  - **id**: FtM-style entity id (e.g. `NK-…`).
  - **schema**: `Person` or `Company`.
  - **caption**: Display name.
  - **datasets**: Source dataset(s), e.g. `pep_world`.
  - **referents**: Source system ids.
  - **first_seen**, **last_change**: ISO 8601 timestamps.
  - **properties**: Same multi-valued format as the request (e.g. `"birthDate": ["1975"]`).

The mock currently returns **one** synthetic PEP result per request (with faker-generated data). Use it to drive UI and integration tests.

### Error Response (400)

```json
{
  "errors": ["Missing required field: queries"]
}
```

## Field Mapping: OpenSanctions vs Mock

| OpenSanctions / FtM | Our mock |
|---------------------|----------|
| `schema` (Person / Company) | Same |
| `properties.*` (arrays) | Same |
| `id`, `caption`, `datasets`, `referents` | Same |
| `first_seen`, `last_change` | Same |
| Batch `queries` / `responses` | Supported for key `q1` |

### Simplifications vs Real API

1. **Single query key**: The mock only fills `responses.q1`. Send your entity under `queries.q1` for a correct echo and results.
2. **No scoring**: Real API returns scores and thresholds; the mock does not.
3. **No collections**: Real API supports e.g. `/match/sanctions` or `/match/default`; the mock has one endpoint.
4. **Synthetic hits**: The mock always returns one faker-generated PEP entity; it does not perform real matching.
5. **No auth**: No API key required.

## Seeded Test Cases

The mock uses persistence key `{{queries.q1.properties.lastName.0}}_{{queries.q1.properties.firstName.0}}`. The following cases are seeded on startup (and by `npm run seed`):

| Key (lastName_firstName) | Scenario | Results |
|--------------------------|----------|---------|
| `de Vries_Jan` | Clean — no match | `[]` |
| `Bakker_Maria` | Clean — no match | `[]` |
| `Al-Rashid_Ahmed` | Sanctions hit, matched entity has no nationality on file (ambiguous corroboration) | One sanctions entity |
| `Berg_Willem` | PEP hit — former official, name/nationality corroborate once normalized | One PEP entity |

Send `queries.q1` with matching `firstName` and `lastName` (e.g. `lastName: ["Berg"]`, `firstName: ["Willem"]`) to get the seeded response. Any other combination gets a freshly generated response (one faker PEP result).

## Troubleshooting: "Cannot POST /api/v1/pep/match" on Elastic Beanstalk

If you get this error on EB, the deployed app doesn’t have the PEP mock (old deployment). Do this:

1. **Check what’s deployed**  
   `GET http://<your-eb-url>/admin/mocks`  
   If the JSON doesn’t list an entry with `"path": "/api/v1/pep/match"`, the running version is old.

2. **Redeploy** from the repo root so the new `mocks/pep-match.json` is included:
   ```bash
   ./scripts/deploy_mock_service.sh
   ```
   Wait for the stack update to finish, then run the seed if needed:
   ```bash
   ./scripts/seed_mock_service_eb.sh
   ```

3. **Call the PEP endpoint again** — the route exists only after a deploy that includes the PEP mock.

## Usage in KYC flows

Use this mock to test PEP/sanctions screening steps (e.g. after identity verification) without calling OpenSanctions. Run the mock service and send `POST /api/v1/pep/match` with a `queries.q1` Person or Company entity; assert on `responses.q1.results` in your tests.
