# KYC Agents — Demo Walkthrough & Test Case Guide

This document walks through each pre-configured test case in the mock service, explaining exactly what happens at every agent stage, which business rules are applied, what breaks (or doesn't), and what the expected outcome is.

Use this to demo the system after deployment, verify the implementation architecturally, and understand the business flows end-to-end.

---

## System Architecture Overview

```
User submits via UI (3 docs: passport, address proof, income proof)
        |
        v
Backend API (/submit-kyc) --> S3 (docs) + DynamoDB (case) + SQS (trigger)
        |
        v
Lambda (kyc-processor) --> Bedrock AgentCore Runtime
        |
        v
    5-Agent Sequential Pipeline (CrewAI)
    +----------------------------------------------------------+
    |  Agent 1: Identity Verification                           |
    |  Agent 2: Income Verification                             |
    |  Agent 3: Risk List Screening (PEP + Sanctions)           |
    |  Agent 4: Adverse Media                                   |
    |  Agent 5: Orchestrator (Wwft decision)                    |
    +----------------------------------------------------------+
        |
        v
    Each agent writes its stage result to DynamoDB
    Frontend polls every 5s to show real-time progress
```

### Pipeline stages written to DynamoDB

```
stages:
  identityVerification:   result (MATCH/PARTIAL_MATCH/MISMATCH)
  incomeVerification:     result (VERIFIED/INSUFFICIENT/SUSPICIOUS/UNREADABLE)
  screening:
    riskListScreening:    result (CLEAR/HIT/ERROR)
    adverseMedia:         result (OK/NOK/PENDING_REVIEW)
  orchestrator:           action, risk_classification (LOW/MEDIUM/HIGH), risk_score (0-100)
```

### Case-level status values

| Status | Meaning |
|--------|---------|
| `INITIATED` | Case created, waiting for agent processing |
| `PROCESSING` | Agents are actively working on the case |
| `APPROVED` | All checks passed, case auto-approved |
| `PENDING_HUMAN_REVIEW` | Escalated to analyst — human decision required |
| `ADDITIONAL_DOCUMENTS_REQUESTED` | System needs more documents from the user |
| `REJECTED` | Analyst rejected the case |

---

## Mock APIs Involved

| Mock API | Endpoint | What It Simulates | Lookup Key |
|----------|----------|-------------------|------------|
| BRP Personen | `POST /api/v1/brp/personen/document-lookup` | Dutch civil registry (identity) | `{documentType}_{documentNumber}` |
| PEP/Sanctions | `POST /api/v1/pep/match` | OpenSanctions watchlist screening | `{lastName}_{firstName}` |
| UWV Polisadministratie | `POST /api/v1/uwv/polisadministratie/dienstverbanden` | Dutch employment/income registry | `{burgerservicenummer}` |
| KVK Basisprofiel | `POST /api/v1/kvk/basisprofiel` | Dutch Chamber of Commerce (business) | `{kvkNummer}` |

---

## Test Personas at a Glance

| Persona | BSN | Passport | Expected Outcome | Risk |
|---------|-----|----------|-------------------|------|
| Jan de Vries | 123456789 | NL123456789 | APPROVED | LOW (0) |
| Maria Bakker | 987654321 | NL987654321 | ESCALATED (identity mismatch + no income) | MEDIUM (55) |
| Ahmed Al-Rashid | 555666777 | NL555666777 | ESCALATED (sanctions hit + suspicious income) | HIGH (70) |
| Willem van den Berg | 111222333 | NL111222333 | ESCALATED (PEP — needs human EDD sign-off) | LOW (27)* |

---

## Case 1: Jan de Vries — Clean Approval (Happy Path)

**Persona**: Male, born 1985-03-15, Amsterdam. Dutch national. Software Engineer at Tech Solutions BV earning EUR 48,000/year.

**What this case demonstrates**: The complete happy path where all 5 checks pass and the system auto-approves.

### Agent 1: Identity Verification

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 1 | `get_case_details` | Fetches from DynamoDB: `identity.fullName = "Jan de Vries"`, DOB `1985-03-15`, passportNumber `NL123456789` |
| 2 | `get_case_files` | Returns 3 files: passport, address, income (S3 references) |
| 3 | `extract_document_text` | Textract OCR on passport — extracts name, DOB, document number from the document image |
| 4 | `verify_identity_document` | Calls BRP API with `{documentType: "paspoort", documentNumber: "NL123456789"}` |

**BRP mock response** (key: `paspoort_NL123456789`):

```json
{
  "burgerservicenummer": "123456789",
  "naam": { "volledigeNaam": "Jan de Vries" },
  "geboorte": { "datum": "1985-03-15", "plaats": "Amsterdam" },
  "document": { "nummer": "NL123456789", "datumEindeGeldigheid": "2030-01-10" },
  "status": "VERIFIED"
}
```

All fields match the DB record. Government confirms the document is genuine.

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 5 | `compare_identity_documents` | LLM compares 3 sources: DB record vs OCR extraction vs BRP government response |

**Result**: `comparison_result: "MATCH"` — all identity fields consistent across all 3 sources. Zero discrepancies.

**DynamoDB write**: `stages.identityVerification.result = "MATCH"`

---

### Agent 2: Income Verification

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 1 | `get_case_details` | Same case data |
| 2 | `get_case_files` | Finds file with `type: "income"` |
| 3 | `extract_document_text` | Textract OCR on income document (e.g., salary slip showing EUR 4,000/month from Tech Solutions BV) |
| 4 | `verify_income_uwv` | Calls UWV Polisadministratie API with `BSN: "123456789"` (obtained from Agent 1's BRP response) |

**UWV mock response** (key: `123456789`):

```json
{
  "burgerservicenummer": "123456789",
  "dienstverbanden": [{
    "werkgever": {
      "naam": "Tech Solutions BV",
      "kvkNummer": "12345678",
      "loonheffingennummer": "L1234567890"
    },
    "dienstverband": {
      "soort": "vast",
      "startdatum": "2020-01-15",
      "beroep": "Software Engineer",
      "arbeidsuren": 40
    },
    "inkomen": {
      "svLoon": 48000,
      "brutoloonPeriode": 4000,
      "loonperiode": "maand",
      "vakantiegeld": 3840
    }
  }],
  "uitkeringen": [],
  "status": "GEVONDEN"
}
```

Key details:
- Employer is registered with KVK (kvkNummer present) and Belastingdienst (loonheffingennummer present)
- Contract type: `vast` = permanent employment
- `vakantiegeld: 3840` (8% of gross annual) — confirms legitimate Dutch employment (legally mandatory)
- Employment since 2020 — stable 5+ year tenure

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 5 | `analyze_income_document` | LLM applies Dutch Wwft business rules to extracted text + UWV registry data |

**Wwft business rules applied**:

| Rule | Check | Result |
|------|-------|--------|
| Name consistency | "Jan de Vries" on salary slip matches DB and UWV | PASS |
| Income plausibility | EUR 4,000/month for Software Engineer — reasonable, under EUR 10K threshold | PASS |
| Document recency | Salary slip within 3 months | PASS |
| Completeness | Employer name, salary, period all present | PASS |
| Red flags | No large cash deposits, no high-risk jurisdiction transfers | PASS |
| Cross-reference | UWV confirms same employer (Tech Solutions BV), same salary (EUR 4,000/month) | PASS |

**Result**: `verification_result: "VERIFIED"`, `risk_indicators: []`, `requires_additional_documents: false`

**DynamoDB write**: `stages.incomeVerification.result = "VERIFIED"`, `monthlyIncomeEur: 4000`, `incomeSource: "employment"`

---

### Agent 3: Risk List Screening

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 1 | `get_case_details` | Fetches identity: `fullName: "Jan de Vries"` |
| 2 | `risk_list_screening` | Calls PEP/Sanctions API with `{firstName: ["Jan"], lastName: ["de Vries"], birthDate: ["1985"]}` |

**PEP mock response** (key: `de Vries_Jan`):

```json
{ "responses": { "q1": { "results": [] } } }
```

Empty results — no matches on any PEP or sanctions list.

**Result**: `result: "CLEAR"`, `pepStatus: "NOT_PEP"`, `sanctionsStatus: "NOT_SANCTIONED"`

**DynamoDB write**: `stages.screening.riskListScreening.result = "CLEAR"`

---

### Agent 4: Adverse Media

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 1 | `get_case_details` | Gets fullName |
| 2 | `search_internet` | DuckDuckGo search: `"Jan de Vries fraud crime money laundering arrest investigation adverse media"` |
| 3 | `produce_adverse_media_analysis` | LLM analyzes search results — determines that "Jan de Vries" is a very common Dutch name and results don't refer to this specific person |

**Result**: `result: "OK"` — no adverse findings about this individual

**DynamoDB write**: `stages.screening.adverseMedia.result = "OK"`

---

### Agent 5: Orchestrator (Wwft Decision)

**Receives all 4 outputs as context:**

| Check | Result | Status |
|-------|--------|--------|
| Identity | MATCH | PASS |
| Income | VERIFIED (no risk indicators) | PASS |
| PEP/Sanctions | CLEAR | PASS |
| Adverse Media | OK | PASS |

**Wwft decision rules applied**:
- All 4 checks pass --> Orchestrator Rule 3a: **APPROVE**
- Risk classification: All pass + standard NL resident + employment income EUR 4K/month --> **LOW**
- Deterministic risk score: MATCH(0) + VERIFIED/no flags(0) + CLEAR(0) + OK(0) = **0**

**Final output**:

```json
{
  "action": "APPROVED",
  "decision": "APPROVE",
  "risk_classification": "LOW",
  "risk_score": 0,
  "risk_score_breakdown": [
    {"factor": "identity_result", "value": "MATCH", "points": 0, "max": 30},
    {"factor": "income_result", "value": "VERIFIED", "points": 0, "max": 25},
    {"factor": "pep_sanctions", "value": "CLEAR", "points": 0, "max": 30},
    {"factor": "adverse_media", "value": "OK", "points": 0, "max": 15}
  ],
  "reason": ["Identity verified: MATCH across DB, OCR, and BRP",
             "Income verified: EUR 48K/yr from Tech Solutions BV confirmed by UWV",
             "PEP/Sanctions: CLEAR — no matches",
             "Adverse media: OK — no findings"],
  "additional_documents_needed": []
}
```

**DynamoDB write**: `status = "APPROVED"`, `stages.orchestrator.status = "APPROVED"`, `risk_classification = "LOW"`

**What the user sees in the UI**: All 5 stage cards turn green. Message: "Identity Verified Successfully".

---

## Case 2: Maria Bakker — Identity Mismatch + No Income Records

**Persona**: Female, born 1990-07-22, Rotterdam. Dutch national. The user submits the case as "Maria Jansen" but the passport (NL987654321) is registered to "Maria Bakker" in the government BRP registry.

**What this case demonstrates**: Identity fraud detection (name mismatch between claimed identity and government records) combined with complete absence of income records in UWV.

### Agent 1: Identity Verification

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 1-3 | `get_case_details`, `get_case_files`, `extract_document_text` | Normal flow — fetches case (DB says "Maria Jansen"), extracts passport via OCR |
| 4 | `verify_identity_document` | Calls BRP with `{documentType: "paspoort", documentNumber: "NL987654321"}` |

**BRP mock response** (key: `paspoort_NL987654321`):

```json
{
  "burgerservicenummer": "987654321",
  "naam": { "volledigeNaam": "Maria Bakker" },
  "geboorte": { "datum": "1990-07-22", "plaats": "Rotterdam" },
  "document": { "nummer": "NL987654321" },
  "status": "VERIFIED"
}
```

**The problem**: The government says passport NL987654321 belongs to **"Maria Bakker"**, but the applicant registered as **"Maria Jansen"**. Same DOB, same passport number — but different surname.

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 5 | `compare_identity_documents` | LLM compares: DB says "Jansen", BRP says "Bakker" — significant name discrepancy |

**Why this breaks (Wwft Art. 3(2)(a))**: The bank must verify identity using a reliable, independent source (BRP is the official Dutch civil registry). The government record contradicts the applicant's claimed identity. This could mean:
- Fraudulent use of another person's passport
- Unreported name change (marriage/divorce)
- Data entry error during submission

**Result**: `comparison_result: "MISMATCH"`, `discrepancies: ["name differs: DB=Maria Jansen, BRP=Maria Bakker"]`

**DynamoDB write**: `stages.identityVerification.result = "MISMATCH"`

---

### Agent 2: Income Verification

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 1-3 | Standard flow | Extracts income document text |
| 4 | `verify_income_uwv` | Calls UWV with `BSN: "987654321"` |

**UWV mock response** (key: `987654321`):

```json
{
  "burgerservicenummer": "987654321",
  "dienstverbanden": [],
  "uitkeringen": [],
  "status": "NIET_GEVONDEN"
}
```

**The problem**: `NIET_GEVONDEN` (not found) — UWV has **zero employment records** for this BSN. No dienstverbanden, no uitkeringen. This person has no verifiable employment history in the Netherlands.

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 5 | `analyze_income_document` | LLM analyzes uploaded income doc against empty UWV registry data |

**Wwft rules applied**:

| Rule | Check | Result |
|------|-------|--------|
| Cross-reference with UWV | No records exist for this BSN | FAIL — major discrepancy |
| Completeness | Cannot verify source of funds without employment records | FAIL |
| Income source | Document alone without government confirmation is insufficient | FAIL |

**Result**: `verification_result: "INSUFFICIENT"`, `requires_additional_documents: true`

```json
{
  "additional_documents_needed": [
    {"document_type": "belastingaangifte", "reason": "No UWV employment records found for this BSN. Tax return needed to verify income source."},
    {"document_type": "bankafschrift", "reason": "Bank statements showing income deposits needed as alternative proof of funds."}
  ]
}
```

---

### Agent 3: Risk List Screening

**PEP mock response** (key: `Bakker_Maria`): `results: []` — no PEP/sanctions match

**Result**: `result: "CLEAR"`

---

### Agent 4: Adverse Media

**Result**: Likely `"OK"` — common name, no specific adverse findings

---

### Agent 5: Orchestrator (Wwft Decision)

| Check | Result | Status |
|-------|--------|--------|
| Identity | **MISMATCH** | FAIL |
| Income | **INSUFFICIENT** | FAIL |
| PEP/Sanctions | CLEAR | PASS |
| Adverse Media | OK | PASS |

**Wwft decision rules applied**:
- Identity MISMATCH --> Orchestrator Rule 3d: **ESCALATE** (possible fraud — human must investigate)
- Income INSUFFICIENT --> Rule 3b would apply (request more docs), but the identity MISMATCH is more severe and overrides — a human analyst must decide whether this is fraud or a legitimate name discrepancy before requesting any further documents
- Risk classification: Deterministic score = MEDIUM, but identity MISMATCH triggers escalation
- Deterministic risk score: MISMATCH(30) + INSUFFICIENT(25) + CLEAR(0) + OK(0) = **55 (MEDIUM)**

**Final output**:

```json
{
  "action": "ESCALATED",
  "decision": "ESCALATE",
  "risk_classification": "MEDIUM",
  "risk_score": 55,
  "risk_score_breakdown": [
    {"factor": "identity_result", "value": "MISMATCH", "points": 30, "max": 30},
    {"factor": "income_result", "value": "INSUFFICIENT", "points": 25, "max": 25},
    {"factor": "pep_sanctions", "value": "CLEAR", "points": 0, "max": 30},
    {"factor": "adverse_media", "value": "OK", "points": 0, "max": 15}
  ],
  "reason": [
    "Identity MISMATCH: BRP shows 'Maria Bakker' but applicant claims 'Maria Jansen'",
    "No UWV employment records found for BSN 987654321",
    "Income verification INSUFFICIENT — cannot verify source of funds",
    "Possible identity fraud or unreported name change — requires human investigation"
  ],
  "additional_documents_needed": []
}
```

**Calls** `escalate_to_human` --> sets case status to `"PENDING_HUMAN_REVIEW"`, sends SQS notification to human review queue

**What the user sees in the UI**: Identity stage shows red MISMATCH, Income stage shows orange INSUFFICIENT. Case status shows "Escalated".

**What the analyst sees in the Dashboard**: Full reasoning displayed — identity mismatch details, no employment records, recommendation to investigate whether this is fraud or a legitimate naming discrepancy before proceeding.

---

## Case 3: Ahmed Al-Rashid — Sanctions Hit + Suspicious Income

**Persona**: Male, born 1978-11-03, Den Haag. Dutch national. Claims to work as a "Consultant" at International Trading GmbH earning EUR 250,000/year on a temporary contract.

**What this case demonstrates**: A sanctions list hit (which alone mandates refusal by law) combined with multiple suspicious income indicators — the highest-risk scenario.

### Agent 1: Identity Verification

**BRP mock response** (key: `paspoort_NL555666777`):

```json
{
  "burgerservicenummer": "555666777",
  "naam": { "volledigeNaam": "Ahmed Al-Rashid" },
  "geboorte": { "datum": "1978-11-03", "plaats": "Den Haag" },
  "document": { "nummer": "NL555666777", "datumEindeGeldigheid": "2031-03-20" },
  "status": "VERIFIED"
}
```

Name matches DB. Identity documents are clean.

**Result**: `comparison_result: "MATCH"` — identity verification passes

---

### Agent 2: Income Verification

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 1-3 | Standard flow | Extracts income document |
| 4 | `verify_income_uwv` | Calls UWV with `BSN: "555666777"` |

**UWV mock response** (key: `555666777`):

```json
{
  "burgerservicenummer": "555666777",
  "dienstverbanden": [{
    "werkgever": {
      "naam": "International Trading GmbH",
      "kvkNummer": "",
      "loonheffingennummer": ""
    },
    "dienstverband": {
      "soort": "tijdelijk",
      "startdatum": "2025-09-01",
      "einddatum": "2026-08-31",
      "beroep": "Consultant",
      "arbeidsuren": 40
    },
    "inkomen": {
      "svLoon": 250000,
      "brutoloonPeriode": 20833,
      "loonperiode": "maand",
      "vakantiegeld": 20000
    }
  }],
  "status": "GEVONDEN"
}
```

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 5 | `analyze_income_document` | LLM applies Wwft rules — finds multiple red flags |

**Wwft rules applied — every check reveals problems**:

| Rule | Check | Result | Why It's a Problem |
|------|-------|--------|--------------------|
| Income plausibility | EUR 20,833/month | **FAIL** | Exceeds EUR 10,000/month threshold. Unusual for a "Consultant" role |
| Employer registration | `kvkNummer: ""` (empty) | **FAIL** | Employer has no Dutch KVK number — not registered in the Netherlands |
| Tax registration | `loonheffingennummer: ""` (empty) | **FAIL** | Employer has no Dutch wage tax number — not registered with Belastingdienst |
| Employer type | "GmbH" (German entity form) | **FLAG** | Not a Dutch company — foreign employer paying EUR 250K raises questions |
| Contract type | `tijdelijk` (temporary) | **FLAG** | EUR 250K on a temporary contract is an unusual combination |
| Employment start | `2025-09-01` | **FLAG** | Very recent employment — started only months ago |
| Red flags | Multiple compounding indicators | **FAIL** | Unregistered foreign employer + extreme salary + temp contract + new hire |

**Result**: `verification_result: "SUSPICIOUS"`

```json
{
  "risk_indicators": [
    "Monthly income EUR 20,833 exceeds EUR 10,000 plausibility threshold",
    "Employer 'International Trading GmbH' has no Dutch KVK registration",
    "Employer has no Dutch loonheffingennummer (wage tax number)",
    "Temporary contract with unusually high salary (EUR 250K/yr)",
    "Very recent employment start date (2025-09-01)"
  ]
}
```

---

### Agent 3: Risk List Screening

**PEP mock response** (key: `Al-Rashid_Ahmed`):

```json
{
  "responses": {
    "q1": {
      "results": [{
        "id": "NK-sanctions-ahmed-001",
        "datasets": ["sanctions"],
        "referents": ["ofac-12345"],
        "properties": {
          "name": ["Ahmed Al-Rashid"],
          "nationality": ["sy"],
          "position": ["Designated under sanctions program"]
        }
      }]
    }
  }
}
```

**This is the critical finding**: `datasets: ["sanctions"]` — this is a **SANCTIONS LIST HIT**, not just a PEP match.

**Why this is critical (legal obligation)**: Under the Dutch Sanctiewet 1977 and EU Council Regulations, if a person appears on a sanctions list, the bank has **zero discretion**. It is **illegal** to provide financial services to this individual. The bank must:
1. Refuse the application immediately
2. Freeze any existing assets
3. Report to the relevant authorities (FIU-Nederland, DNB)

**Result**: `result: "HIT"`, `sanctionsStatus: "SANCTIONED"`, `datasetsMatched: ["sanctions"]`

---

### Agent 4: Adverse Media

Searches for "Ahmed Al-Rashid fraud crime money laundering..." — the sanctions designation itself may appear in news sources.

**Result**: Likely `"NOK"` or `"PENDING_REVIEW"` — adverse findings linked to sanctions designation

---

### Agent 5: Orchestrator (Wwft Decision)

| Check | Result | Status |
|-------|--------|--------|
| Identity | MATCH | PASS |
| Income | **SUSPICIOUS** (5 risk indicators) | FAIL |
| PEP/Sanctions | **HIT — SANCTIONS LIST** | CRITICAL FAIL |
| Adverse Media | NOK or PENDING_REVIEW | FAIL |

**Wwft decision rules applied**:
- Sanctions HIT --> Orchestrator Rule 3d: **immediate ESCALATE** — no discretion, EU law mandates refusal
- Income SUSPICIOUS + Sanctions HIT = compounding HIGH risk
- Risk classification: **HIGH** (sanctions alone guarantees this, income issues compound it)
- Deterministic risk score: MATCH(0) + SUSPICIOUS(25) + SANCTIONED(30) + NOK(15) = **70 (HIGH)**
  - If adverse media returns PENDING_REVIEW instead of NOK: 0+25+30+8 = 63, still HIGH

**Final output**:

```json
{
  "action": "ESCALATED",
  "decision": "ESCALATE",
  "risk_classification": "HIGH",
  "risk_score": 70,
  "risk_score_breakdown": [
    {"factor": "identity_result", "value": "MATCH", "points": 0, "max": 30},
    {"factor": "income_result", "value": "SUSPICIOUS", "points": 25, "max": 25},
    {"factor": "pep_sanctions", "value": "SANCTIONED", "points": 30, "max": 30},
    {"factor": "adverse_media", "value": "NOK", "points": 15, "max": 15}
  ],
  "reason": [
    "SANCTIONS HIT: Person appears on sanctions list (dataset: sanctions, ref: ofac-12345)",
    "Sanctiewet 1977: Bank is legally prohibited from providing services",
    "Income SUSPICIOUS: EUR 250K/yr temp contract with unregistered foreign employer",
    "Employer 'International Trading GmbH' has no Dutch KVK or tax registration",
    "Multiple compounding risk indicators across income and sanctions stages"
  ],
  "recommendation_summary": "SANCTIONS MATCH — service must be refused per EU regulation and Dutch Sanctiewet 1977. Applicant appears on sanctions list (OFAC reference ofac-12345). Additionally, income from unregistered foreign employer raises serious money laundering concerns. Recommend rejection and filing report with FIU-Nederland.",
  "additional_documents_needed": []
}
```

**Calls** `escalate_to_human` --> `status: "PENDING_HUMAN_REVIEW"`

**What the user sees in the UI**: Identity card green, Income card red (SUSPICIOUS), Sanctions card red (HIT). Case status shows "Escalated".

**What the analyst sees**: Sanctions hit is prominently displayed with OFAC reference. System recommends outright rejection. The analyst would typically reject and file a report with FIU-Nederland (Dutch Financial Intelligence Unit).

---

## Case 4: Willem van den Berg — PEP with Dual Income Sources

**Persona**: Male, born 1970-01-20, Utrecht. Dutch national. Former government minister (PEP). Currently works as Beleidsadviseur (policy advisor) at Rijksoverheid (Dutch central government) earning EUR 95K/year, and also owns Van den Berg Advies BV — a consulting firm.

**What this case demonstrates**: A Politically Exposed Person (PEP) who is NOT a criminal. PEP status doesn't mean the person is bad — it means they held/hold a position of political power and require Enhanced Due Diligence (EDD) under Wwft Art. 8. This case also demonstrates dual income source verification (government + private business).

### Agent 1: Identity Verification

**BRP mock response** (key: `paspoort_NL111222333`):

```json
{
  "burgerservicenummer": "111222333",
  "naam": { "voornamen": "Willem", "voorvoegsel": "van den", "geslachtsnaam": "Berg", "volledigeNaam": "Willem van den Berg" },
  "geboorte": { "datum": "1970-01-20", "plaats": "Utrecht" },
  "document": { "nummer": "NL111222333", "datumEindeGeldigheid": "2032-09-15" },
  "status": "VERIFIED"
}
```

Name matches DB perfectly. Identity is clean.

**Result**: `comparison_result: "MATCH"`

---

### Agent 2: Income Verification

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 1-3 | Standard flow | Extracts income document |
| 4 | `verify_income_uwv` | Calls UWV with `BSN: "111222333"` |

**UWV mock response** (key: `111222333`):

```json
{
  "burgerservicenummer": "111222333",
  "dienstverbanden": [{
    "werkgever": {
      "naam": "Rijksoverheid",
      "kvkNummer": "00000001",
      "loonheffingennummer": "L0000000001"
    },
    "dienstverband": {
      "soort": "vast",
      "startdatum": "2005-04-01",
      "einddatum": null,
      "beroep": "Beleidsadviseur",
      "arbeidsuren": 36
    },
    "inkomen": {
      "svLoon": 95000,
      "brutoloonPeriode": 7917,
      "loonperiode": "maand",
      "vakantiegeld": 7600,
      "bijzondereBeloningen": 2500
    }
  }],
  "uitkeringen": [],
  "status": "GEVONDEN"
}
```

UWV shows 1 employment record: Rijksoverheid (Dutch central government), permanent since 2005, EUR 95K/year.

**Note**: UWV only shows the government employment. But if the uploaded income document (e.g., a tax return) mentions his consulting BV with KVK number 87654321, the agent would also call:

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 5 | `verify_business_kvk` | Calls KVK API with `kvkNummer: "87654321"` (found in income document text) |

**KVK mock response** (key: `87654321`):

```json
{
  "kvkNummer": "87654321",
  "naam": "Van den Berg Advies BV",
  "formeleRegistratiedatum": "2015-06-01",
  "statutaireNaam": "Van den Berg Advies B.V.",
  "sbiActiviteiten": [{ "sbiCode": "70221", "sbiOmschrijving": "Organisatieadviesbureaus", "indHoofdactiviteit": "Ja" }],
  "eigenaar": { "rechtsvorm": "BeslotenVennootschap" },
  "hoofdvestiging": {
    "vestigingsnummer": "123456789012",
    "eersteHandelsnaam": "Van den Berg Advies",
    "totaalWerkzamePersonen": 3,
    "adressen": [{ "type": "bezoekadres", "straatnaam": "Herengracht", "huisnummer": 100, "postcode": "1015BS", "plaats": "Amsterdam" }]
  }
}
```

KVK shows: legitimate consulting BV, registered since 2015, SBI code 70221 (management consultancy), 3 employees, physical address on Herengracht in Amsterdam.

| Step | Tool Called | What Happens |
|------|-----------|-------------|
| 6 | `analyze_income_document` | LLM evaluates dual income against Wwft rules |

**Wwft rules applied**:

| Rule | Check | Result | Notes |
|------|-------|--------|-------|
| Name consistency | UWV and KVK both traceable to Willem van den Berg | PASS | |
| Income plausibility | Government EUR 7,917/month | PASS | Reasonable for senior beleidsadviseur |
| Business legitimacy | KVK registered 2015, 3 employees, real address, legitimate SBI code | PASS | Not a shell company |
| Document recency | Income docs within acceptable timeframe | PASS | |
| Red flags | None specific | PASS | |
| Multiple income sources | Government employment + private consulting BV | **FLAG** | Not a red flag per se, but triggers EDD — all material income sources must be verified separately under Wwft |

**Result**: `verification_result: "VERIFIED"`, `income_source: "employment"`, `risk_indicators: ["Multiple income sources: government employment + private consulting BV"]`

The single risk indicator is **informational** (flagging dual sources for EDD), not a disqualifying red flag. Both sources are legitimate and verifiable.

---

### Agent 3: Risk List Screening

**PEP mock response** (key: `Berg_Willem`):

```json
{
  "responses": {
    "q1": {
      "results": [{
        "id": "NK-pep-willem-001",
        "datasets": ["pep_world"],
        "properties": {
          "name": ["Willem van den Berg"],
          "nationality": ["nl"],
          "position": ["Former Minister", "Government Official"]
        }
      }]
    }
  }
}
```

**Critical distinction from Case 3**: `datasets: ["pep_world"]` — this is a **PEP match**, NOT a sanctions match.

**What PEP means**: A Politically Exposed Person is someone who holds or has held a prominent public function. This includes heads of state, ministers, members of parliament, senior military officers, judges, and their family members. PEP status is **not an accusation** — it's a risk classification that requires extra scrutiny.

**Why PEPs need extra checks (Wwft Art. 8)**: People in positions of political power have more opportunity for corruption and bribery. Banks must apply Enhanced Due Diligence:
- Establish the source of wealth and funds
- Conduct enhanced ongoing monitoring
- Obtain senior management approval for the business relationship

**Result**: `result: "HIT"`, `pepStatus: "PEP"`, `sanctionsStatus: "NOT_SANCTIONED"`, `datasetsMatched: ["pep_world"]`

---

### Agent 4: Adverse Media

Searches for "Willem van den Berg fraud crime money laundering..."

Being a former government minister, there may be general news articles, but (in our scenario) nothing specifically about criminal activity. The LLM determines mentions are factual/neutral political coverage, not adverse.

**Result**: `result: "OK"` — no adverse media about criminal activity

---

### Agent 5: Orchestrator (Wwft Decision)

| Check | Result | Status |
|-------|--------|--------|
| Identity | MATCH | PASS |
| Income | VERIFIED (1 informational indicator) | PASS (with EDD note) |
| PEP/Sanctions | **HIT — PEP only** (no sanctions) | REQUIRES EDD |
| Adverse Media | OK | PASS |

**Wwft decision rules applied**:
- Identity MATCH + Income VERIFIED + Adverse Media OK --> would normally approve
- **BUT**: PEP HIT triggers Wwft Art. 8 — Enhanced Due Diligence is legally required
- Deterministic risk score: MATCH(0) + VERIFIED/1 flag(12) + PEP_ONLY(15) + OK(0) = **27 (LOW)**
- **However**: PEP status triggers Wwft Art. 8 — Enhanced Due Diligence is legally required regardless of the numeric score
- The conservative approach (and most banks' internal policy) is to escalate PEP cases for human sign-off, even when the deterministic score is LOW

**Final output**:

```json
{
  "action": "ESCALATED",
  "decision": "ESCALATE",
  "risk_classification": "LOW",
  "risk_score": 27,
  "risk_score_breakdown": [
    {"factor": "identity_result", "value": "MATCH", "points": 0, "max": 30},
    {"factor": "income_result", "value": "VERIFIED_WITH_FLAGS", "points": 12, "max": 25},
    {"factor": "pep_sanctions", "value": "PEP_ONLY", "points": 15, "max": 30},
    {"factor": "adverse_media", "value": "OK", "points": 0, "max": 15}
  ],
  "reason": [
    "PEP match: Former Minister, Government Official (dataset: pep_world)",
    "Enhanced Due Diligence (EDD) required under Wwft Art. 8 for PEP customers",
    "Multiple income sources: government employment (EUR 95K) + consulting BV (KVK 87654321)",
    "No sanctions — PEP status is the only risk factor",
    "No adverse media found",
    "Income fully verified: Rijksoverheid employment confirmed by UWV, BV confirmed by KVK",
    "Note: Deterministic score is 27 (LOW) but case escalated because PEP requires human EDD sign-off per Wwft Art. 8"
  ],
  "recommendation_summary": "Applicant is a Politically Exposed Person (Former Minister). All identity, income, and media checks pass clean. Income verified from two sources: government employment (EUR 95K/yr, confirmed by UWV) and consulting BV (Van den Berg Advies, KVK 87654321, registered since 2015, 3 employees). No sanctions or adverse media. Deterministic risk score is LOW (27), but PEP status mandates escalation. Recommend APPROVAL with EDD documentation. Analyst should verify the consulting BV relationship doesn't create conflict of interest with former government role.",
  "additional_documents_needed": []
}
```

**Calls** `escalate_to_human` --> `status: "PENDING_HUMAN_REVIEW"`

**What the user sees in the UI**: Identity and income green, PEP/Sanctions shows orange "HIT", but the detail panel shows it's PEP only (no sanctions). Case is in review.

**What the analyst sees**: LOW risk score (27) but escalated due to PEP status. PEP flag clearly displayed with position details. All other checks pass clean. The `risk_score_breakdown` shows PEP contributed 15 points and the dual-income flag contributed 12 points. System **recommends approval with EDD documentation** — the analyst should approve but must document the EDD review in the compliance file, verify no conflict of interest between government role and consulting BV, and set up enhanced ongoing monitoring.

---

## Additional Flow: Additional Documents Requested

This flow would trigger if, for example, a user submitted an unreadable or insufficient income document.

### Trigger scenario

Imagine Jan de Vries uploaded a blurry photo of his salary slip instead of a clear scan. The income verification agent would return:

```json
{
  "verification_result": "UNREADABLE",
  "requires_additional_documents": true,
  "additional_documents_needed": [
    {"document_type": "loonstrook", "reason": "Uploaded income document was not legible. Please upload a clear scan or PDF of your most recent salary slip."}
  ]
}
```

### What happens step by step

| Step | System | Action |
|------|--------|--------|
| 1 | Income Agent | Returns `UNREADABLE` with specific document request |
| 2 | Orchestrator | Returns `action: "ADDITIONAL_DOCUMENTS_REQUIRED"` |
| 3 | DynamoDB | Case status set to `"ADDITIONAL_DOCUMENTS_REQUESTED"` |
| 4 | Frontend (Uploader) | User sees orange alert: "Additional Documents Required" with the specific document type and reason |
| 5 | User | Uploads clearer salary slip via the upload form in the UI |
| 6 | Backend | `POST /submissions/{caseId}/upload-additional` — file goes to S3, DynamoDB files array updated |
| 7 | Frontend (Dashboard) | Analyst sees the uploaded additional documents in the detail panel with download/view links |
| 8 | Analyst | **Reviews the documents manually** — no agent re-processing occurs |
| 9 | Analyst | Makes a human decision: clicks Approve, Reject, or Escalate using the existing action buttons |
| 10 | Backend | `PATCH /submissions/{caseId}/status` — updates case status to the analyst's decision |

**Important**: There is no automated re-processing of additional documents. The agents already identified what was missing. The human analyst completes the verification by reviewing what the user provided and making the final call.

---

## Summary Decision Matrix

| | Case 1: Jan de Vries | Case 2: Maria Bakker | Case 3: Ahmed Al-Rashid | Case 4: Willem van den Berg |
|---|---|---|---|---|
| **Identity** | MATCH | **MISMATCH** | MATCH | MATCH |
| **Income** | VERIFIED | **INSUFFICIENT** | **SUSPICIOUS** | VERIFIED (with note) |
| **PEP/Sanctions** | CLEAR | CLEAR | **SANCTIONS HIT** | **PEP HIT** |
| **Adverse Media** | OK | OK | NOK/PENDING | OK |
| **Decision** | **APPROVED** | **ESCALATED** | **ESCALATED** | **ESCALATED** |
| **Risk Score** | 0 | 55 | 70 | 27 |
| **Risk Level** | LOW (0) | MEDIUM (55) | HIGH (70) | LOW (27)* |
| **Case Status** | `APPROVED` | `PENDING_HUMAN_REVIEW` | `PENDING_HUMAN_REVIEW` | `PENDING_HUMAN_REVIEW` |
| **Root cause** | All clear | Wrong name on passport + no income records | Sanctions list = illegal to serve | PEP = needs human EDD sign-off |
| **Regulatory basis** | Wwft Art. 3 — standard CDD | Wwft Art. 3(2)(a) — identity verification failure | Sanctiewet 1977, EU regulation — mandatory refusal | Wwft Art. 8 — EDD for PEPs |
| **Expected analyst action** | N/A (auto-approved) | Investigate name discrepancy, request explanation or reject | Reject and report to FIU-Nederland | Approve with EDD documentation |

*Risk scores are computed deterministically using the weighted formula in `crew/update_orchestrator_result.py`. A `risk_score_breakdown` array is stored with each score for auditability.

*Willem scores LOW (27) based on the deterministic formula, but the orchestrator still escalates because PEP cases require human EDD sign-off under Wwft Art. 8 regardless of score.

---

## Regulatory Quick Reference

| Law/Regulation | What It Requires | Which Cases It Affects |
|----------------|-----------------|----------------------|
| **Wwft Art. 3** | Customer Due Diligence — verify identity and source of funds | All cases |
| **Wwft Art. 3(2)(a)** | Identity must be verified using reliable, independent source | Case 2 (BRP mismatch) |
| **Wwft Art. 3(2)(d)** | Establish source of funds in the business relationship | Cases 2, 3 (income issues) |
| **Wwft Art. 8** | Enhanced Due Diligence for PEPs | Case 4 (PEP) |
| **Wwft Art. 16** | Report unusual transactions (cash > EUR 15,000) | Potentially Case 3 |
| **Sanctiewet 1977** | Prohibition on providing services to sanctioned persons | Case 3 (sanctions hit) |
| **EU AMLD5/6** | EU-wide AML framework implemented by Wwft | All cases |

---

*Document version: 2026-04-01. See `docs/kyc-business-rules-and-references.md` for full regulatory sources and mock API schema references.*
