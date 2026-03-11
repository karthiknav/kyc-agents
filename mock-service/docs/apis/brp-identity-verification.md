# BRP Identity Document Verification (NL)

Mock endpoint simulating the Dutch BRP Personen API for identity document verification.

## Real API Reference

| | |
|---|---|
| **API Name** | Haal Centraal BRP Personen API |
| **Maintained by** | RvIG (Rijksdienst voor Identiteitsgegevens) |
| **Repository** | https://github.com/BRP-API/Haal-Centraal-BRP-bevragen |
| **API Docs** | https://brp-api.github.io/Haal-Centraal-BRP-bevragen/v2/redoc |
| **Real Endpoint** | `POST /personen` with `fields` parameter |
| **Auth** | mTLS + API key (government PKI) |

## Our Mock Endpoint

```
POST /api/v1/brp/personen/document-lookup
```

### Request

```json
{
  "documentType": "paspoort",       // Required. One of: paspoort, identiteitskaart, rijbewijs
  "documentNumber": "NL123456789"   // Required. The document number
}
```

### Response (200 OK)

```json
{
  "burgerservicenummer": "123456789",
  "naam": {
    "voornamen": "Jan",
    "voorvoegsel": "de",
    "geslachtsnaam": "Vries",
    "volledigeNaam": "Jan de Vries"
  },
  "geboorte": {
    "datum": "1985-03-15",
    "plaats": "Amsterdam",
    "land": "Nederland"
  },
  "geslacht": "M",
  "nationaliteiten": [
    { "nationaliteit": "Nederlandse" }
  ],
  "document": {
    "soort": "paspoort",
    "nummer": "NL123456789",
    "datumUitgifte": "2020-01-10",
    "datumEindeGeldigheid": "2030-01-10"
  },
  "status": "VERIFIED",
  "verificationTimestamp": "2025-01-15T10:00:00.000Z"
}
```

### Error Response (400)

```json
{
  "errors": ["Missing required field: documentNumber"]
}
```

## Field Mapping: Real API vs Mock

| Real BRP Field | Dutch Meaning | Our Mock Field |
|---------------|---------------|----------------|
| `burgerservicenummer` | Citizen service number (BSN) | `burgerservicenummer` |
| `naam.voornamen` | First names | `naam.voornamen` |
| `naam.voorvoegsel` | Name prefix (de, van, etc.) | `naam.voorvoegsel` |
| `naam.geslachtsnaam` | Family name | `naam.geslachtsnaam` |
| `geboorte.datum` | Birth date | `geboorte.datum` |
| `geboorte.plaats` | Birth place | `geboorte.plaats` |
| `geboorte.land` | Birth country | `geboorte.land` |
| `geslacht` | Gender (M/V/O) | `geslacht` |
| `nationaliteiten[].nationaliteit` | Nationality | `nationaliteiten[].nationaliteit` |

### Simplifications vs Real API

1. **Lookup method**: Real API uses BSN or a `fields` selector; our mock uses document type + number directly
2. **Travel documents**: Real API has a separate endpoint for reisdocumenten; we embed document details in the person response
3. **Authentication**: Real API requires mTLS with government PKI certificates; our mock has no auth
4. **Response shape**: Real API uses HAL+JSON with `_links`; our mock returns plain JSON
5. **Name structure**: We added `volledigeNaam` (full name) for convenience; the real API doesn't include this computed field

## Seeded Test Cases

| Document Number | Person | Scenario |
|----------------|--------|----------|
| `NL123456789` | Jan de Vries | Clean approval — all fields match |
| `NL987654321` | Maria Bakker | Document mismatch — registered to Bakker, not Jansen |
| `NL555666777` | Ahmed Al-Rashid | Sanctions flag — doc verification passes, screening catches |
| `NL111222333` | Willem van den Berg | PEP flag — former government official |

Run `npm run seed` to populate these test cases.
