# Plan: Income Verification Agent + KYC Business Rules (Wwft)

## Implementation Status: COMPLETED

All 6 phases implemented and committed on branch `feature/income-verification-wwft` (commit `2428ec2`).

| Phase | Status |
|-------|--------|
| Phase 1: Income verification agent + tools + callback | DONE |
| Phase 2: Wwft business rules + risk classification in orchestrator | DONE |
| Phase 3: Backend API changes | DONE |
| Phase 4: Frontend updates | DONE |
| Phase 5: Mock service + test data | DONE |
| Phase 6: Reference documentation | DONE |
| Bonus: Renamed document_processing_agent -> identity_verification_agent | DONE |

---

## Context

The KYC system currently collects 3 documents (passport, address proof, income proof) but **only processes identity documents**. The income document is uploaded to S3 but never extracted or analyzed. There are also no real-world KYC business rules — the orchestrator simply checks identity match + PEP/sanctions + adverse media.

This plan adds:
1. Income verification via a dedicated agent (Textract + LLM analysis)
2. Dutch Wwft (Anti-Money Laundering Act) business rules for source-of-funds verification
3. A mock Dutch income registry API for cross-verification
4. An "additional documents requested" flow where the system tells the analyst what's needed and why, and the analyst can trigger re-processing after the user uploads
5. Risk classification (LOW/MEDIUM/HIGH) in the orchestrator decision

### Plan Persistence
This plan will be saved to `docs/plan-income-verification.md` in the project root before implementation begins.

### Design Decisions (confirmed with user)
- **UI updates**: Keep existing 5-second polling (already works)
- **Agent design**: New dedicated `income_verification_agent` (5th agent, new pipeline stage)
- **Re-processing**: Manual analyst trigger after additional document upload. UI captures full reasoning/context for the analyst
- **Mock APIs**: Both mock income registry API + LLM analysis of Textract-extracted text

---

## Phase 1: Income Verification Agent + Tool + Callback

**Goal**: Add the new agent, its LLM-based income analysis tool, and the DynamoDB/S3 callback.

### 1.1 New: `crew/tools/analyze_income_tool.py`

CrewAI `BaseTool` subclass following `compare_identity_tool.py` pattern (Bedrock Converse API).

**Input** (Pydantic `AnalyzeIncomeInput`):
- `case_details: str` — JSON from get_case_details
- `extracted_income_text: str` — full text from Textract
- `document_type_hint: str` — "bank_statement", "employment_contract", "salary_slip", "business_registration", "tax_return", "unknown"
- `income_registry_data: str` — JSON from verify_income API (optional, default "")

**LLM prompt** encodes Wwft business rules:
- Identify document type from text
- Extract: account holder/employer name, amounts, period, contract type, IBAN
- **Name consistency**: account holder / employee name vs applicant identity
- **Income plausibility**: flag if monthly net > EUR 10K for standard employment, inconsistent with profile
- **Document recency**: bank statements within 3 months, salary slips within 3 months, contracts still valid
- **Completeness**: enough info to verify source of funds?
- **Red flags**: large cash deposits, transfers from high-risk jurisdictions, gaps, multiple unknown sources
- Cross-reference with income registry data if provided

**Output JSON**:
```json
{
  "document_type_detected": "bank_statement|employment_contract|...",
  "income_source": "employment|self_employment|business_ownership|...",
  "income_details": {
    "employer_or_source": "Company BV",
    "monthly_income_eur": 3500,
    "annual_income_eur": 42000,
    "currency": "EUR",
    "income_frequency": "monthly"
  },
  "name_on_document": "Jan de Vries",
  "name_match": true,
  "document_date": "2026-01-15",
  "document_period": "2025-12 to 2026-01",
  "verification_result": "VERIFIED|INSUFFICIENT|SUSPICIOUS|UNREADABLE",
  "risk_indicators": ["list of flags"],
  "missing_information": ["list of missing items"],
  "plausibility_assessment": "...",
  "summary": "...",
  "requires_additional_documents": false,
  "additional_documents_needed": [
    {"document_type": "tax_return", "reason": "Income from self-employment requires tax return for verification"}
  ]
}
```

Implementation: model on `crew/tools/compare_identity_tool.py` lines 94-187 (`_compare_with_llm` using `boto3.client("bedrock-runtime").converse()`). Same model resolution pattern.

**Multi-page document handling** (important — no naive truncation):
Instead of truncating extracted text (which would lose contract details on later pages), add a **pre-processing summarization step**:
1. After Textract extraction, if text exceeds 10,000 chars, make a preliminary LLM call to summarize/extract key financial data from the full text
2. The summarization prompt instructs the LLM to extract: account holder name, employer/company name, all monetary amounts with context, dates/periods, IBAN, contract terms, and any red flags — preserving all financially relevant information regardless of page position
3. The summarized output (structured JSON) is then passed to the main analysis prompt
4. This is implemented as a private `_summarize_long_document()` method in the tool class
5. For documents under 10,000 chars, skip summarization and pass text directly

### 1.2 New: `crew/tools/verify_income_tool.py`

Two tools in one file, both `BaseTool` subclasses modeled on `verify_identity_tool.py`:

**VerifyIncomeUWVTool** — Calls mock UWV Polisadministratie API:
- Endpoint: `{MOCK_SERVICE_URL}/api/v1/uwv/polisadministratie/dienstverbanden`
- Input: `burgerservicenummer: str` (BSN from BRP verification)
- Returns dienstverbanden (employment records) with svLoon, werkgever, contract type
- URL resolution: `UWV_API_URL` → `MOCK_SERVICE_URL + /api/v1/uwv/polisadministratie/dienstverbanden` → `http://localhost:9000`

**VerifyBusinessKVKTool** — Calls mock KVK Basisprofiel API:
- Endpoint: `{MOCK_SERVICE_URL}/api/v1/kvk/basisprofiel`
- Input: `kvk_nummer: str` (KVK number extracted from income document or case)
- Returns business registration details (name, SBI activities, employees, owner)
- URL resolution: `KVK_API_URL` → `MOCK_SERVICE_URL + /api/v1/kvk/basisprofiel` → `http://localhost:9000`
- Only called when income source is self-employment or business ownership

### 1.3 New: `crew/update_income_result.py`

Follow exact pattern of `crew/update_document_result.py`:
- Parse task_output (TaskOutput.raw / JSON string / dict)
- Extract fields: case_id, verification_result, income_details, summary, risk_indicators, requires_additional_documents, additional_documents_needed
- Generate markdown report → upload to S3 `cases/{case_id}/income-verification-report.md`
- Write to DynamoDB `stages.incomeVerification`:
  ```json
  {
    "result": "VERIFIED|INSUFFICIENT|SUSPICIOUS|UNREADABLE",
    "incomeSource": "employment",
    "monthlyIncomeEur": 3500,
    "nameMatch": true,
    "riskIndicators": [],
    "summary": "...",
    "requiresAdditionalDocuments": false,
    "additionalDocumentsNeeded": [{"document_type": "...", "reason": "..."}],
    "updatedAt": "...",
    "reportS3": {"bucket": "...", "key": "..."}
  }
  ```

### 1.4 Modify: `crew/config/agents.yaml`

Add `income_verification_agent`:
```yaml
income_verification_agent:
  role: >
    Income & Source of Funds Verification Agent
  goal: >
    Given a caseId, fetch case details and income document files, extract text
    via Textract, optionally cross-reference with the income registry API,
    and analyze per Dutch Wwft requirements.
  backstory: >
    You are a KYC income verification specialist with expertise in Dutch Wwft.
    You analyze income proof documents (bank statements, employment contracts,
    salary slips, business registrations, tax returns). Use tools in sequence:
    get_case_details, get_case_files (find files with type "income"),
    extract_document_text (for each income doc), optionally verify_income
    (if BSN available from prior identity verification), then
    analyze_income_document with extracted text + case details + registry data.
  max_iter: 20
```

### 1.5 Modify: `crew/config/tasks.yaml`

Add `income_verification_task` (between identity_verification_task and risk_list_screening_task).

### 1.6 Modify: `crew/crew.py`

- Import `AnalyzeIncomeDocumentTool`, `VerifyIncomeUWVTool`, `VerifyBusinessKVKTool`, `update_income_result`
- Add `income_verification_agent()` method with tools: GetCaseDetailsTool, GetCaseFilesTool, ExtractDocumentTextTool, VerifyIncomeUWVTool, VerifyBusinessKVKTool, AnalyzeIncomeDocumentTool
- Add `income_verification_task()` method with callback `update_income_result`
- Update `orchestrator_task` context: add `self.income_verification_task()`
- Update `crew()` agents + tasks lists to include new agent/task in position 2 (after doc processing)

**Files**: `crew/tools/analyze_income_tool.py` (new), `crew/tools/verify_income_tool.py` (new), `crew/update_income_result.py` (new), `crew/config/agents.yaml`, `crew/config/tasks.yaml`, `crew/crew.py`

---

## Phase 2: Wwft Business Rules + Risk Classification in Orchestrator

> **Update (post-implementation)**: The risk scoring approach described in this phase was subsequently replaced with a deterministic weighted formula. Instead of the LLM-generated risk scores originally planned here, `crew/update_orchestrator_result.py` now computes a fully deterministic score (0-100) based on a weighted sum of the four agent stage results read from DynamoDB. See `docs/kyc-business-rules-and-references.md` Section 5 for the complete scoring table and breakdown.

**Goal**: Embed real Dutch KYC rules in the orchestrator and add risk classification.

### 2.1 Modify: `crew/config/agents.yaml` — orchestrator_agent

Update role to "KYC Decision Orchestrator (Wwft Compliance)". Expand backstory with:

**Approval criteria** (ALL must be true):
- Document verification: MATCH
- Income verification: VERIFIED with no risk indicators
- Risk list screening: CLEAR
- Adverse media: OK

**Risk classification rules**:
- LOW: All pass, standard NL/EU resident, employment income < EUR 10K/month
- MEDIUM: Minor discrepancies (PARTIAL_MATCH), PEP with no adverse media, self-employment/business income
- HIGH: Sanctions hit, adverse media NOK, document MISMATCH, SUSPICIOUS income, multiple risk indicators

**Additional documents logic**:
- Income INSUFFICIENT → escalate with specific document requests + reasoning
- Income UNREADABLE → request re-upload
- Plausibility concerns → request additional proof

### 2.2 Modify: `crew/config/tasks.yaml` — orchestrator_task

Update description to include income verification in decision flow. Add `ADDITIONAL_DOCUMENTS_REQUIRED` as a possible action. Update expected_output to include `risk_classification`, `risk_score`, `additional_documents_needed`.

### 2.3 Modify: `crew/update_orchestrator_result.py`

- Add `risk_classification`, `risk_score`, `additional_documents_needed` to `orchestrator_stage` dict
- New case status mapping:
  - APPROVED → "APPROVED"
  - ADDITIONAL_DOCUMENTS_REQUIRED → "ADDITIONAL_DOCUMENTS_REQUESTED"
  - ESCALATED → "PENDING_HUMAN_REVIEW"
- Accept `ADDITIONAL_DOCUMENTS_REQUIRED` as a terminal action (alongside APPROVED/ESCALATED)

### 2.4 Modify: `crew/tools/escalate_human_tool.py`

- Add optional `additional_documents_needed: str` field to `EscalateToHumanInput`
- When populated, write `additionalDocumentsRequested` (parsed JSON array of `{document_type, reason}`) to DynamoDB item top-level
- Include document request details in SQS notification to human review queue

**Files**: `crew/config/agents.yaml`, `crew/config/tasks.yaml`, `crew/update_orchestrator_result.py`, `crew/tools/escalate_human_tool.py`

---

## Phase 3: Backend API Changes

**Goal**: Extend backend for income verification stage, additional document uploads, and re-processing trigger.

### 3.1 Modify: `backend/main.py` — New Pydantic models

```python
class AdditionalDocumentRequest(BaseModel):
    document_type: str
    reason: str

class IncomeVerificationStage(BaseModel):
    result: str = "PENDING"
    incomeSource: Optional[str] = None
    monthlyIncomeEur: Optional[float] = None
    nameMatch: Optional[bool] = None
    riskIndicators: List[str] = []
    summary: str = "Awaiting income verification"
    requiresAdditionalDocuments: bool = False
    additionalDocumentsNeeded: List[AdditionalDocumentRequest] = []
    reportS3: Optional[S3Location] = None
    updatedAt: Optional[str] = None
```

### 3.2 Modify: `backend/main.py` — Update CaseStages

Add `incomeVerification: IncomeVerificationStage`. Update `OrchestratorStage` with `risk_classification`, `risk_score`, `additional_documents_needed`.

### 3.3 New endpoint: `POST /submissions/{caseId}/upload-additional`

- Accept multipart: `document_type` (str), `reason_context` (str — why this doc was requested), `file` (UploadFile)
- Upload to S3: `cases/{caseId}/additional_{document_type}_{filename}`
- Append to `files` array in DynamoDB with type `additional_{document_type}`
- Do NOT auto-trigger re-processing (analyst controls this)
- Return success with updated file list

### 3.4 New endpoint: `POST /submissions/{caseId}/reprocess`

- Analyst-only endpoint to trigger re-processing
- Validates case has status `ADDITIONAL_DOCUMENTS_REQUESTED` or `PENDING_HUMAN_REVIEW`
- Resets status to `PROCESSING` (clears relevant stage results)
- Sends SQS message to re-trigger the agent pipeline
- Returns `{status: "reprocessing", caseId}`

### 3.5 New endpoint: `GET /submissions/{caseId}/additional-documents-needed`

- Reads `stages.orchestrator.additional_documents_needed` + `stages.incomeVerification.additionalDocumentsNeeded`
- Returns list of `{document_type, reason}` objects with full context

### 3.6 Modify: filter in `/submissions` and analytics

- Add `ADDITIONAL_DOCUMENTS_REQUESTED` to recognized statuses

**Files**: `backend/main.py`

---

## Phase 4: Frontend Updates

**Goal**: Display income stage, show additional document requests with reasoning, add upload + analyst re-trigger.

### 4.1 Modify: `frontend/src/types.ts`

- Add `IncomeVerificationStage` interface
- Add `incomeVerification?` to stages in `User` and `KycSubmission`
- Add `risk_classification?`, `risk_score?`, `additional_documents_needed?` to `OrchestratorStage`

### 4.2 Modify: `frontend/src/components/Uploader.tsx`

**In Step 3 (Verification) in-progress view**:
- Add Income & Source of Funds card (💰) between Document Verification and Adverse Media cards
- Update progress bar: 20% per stage (doc → income → adverse → risk → orchestrator)
- **New section**: When `caseStatus === 'ADDITIONAL_DOCUMENTS_REQUESTED'`:
  - Show alert box with "Additional Documents Required" heading
  - List each needed document with `document_type` and `reason` (full context for user)
  - Upload zone per requested document type
  - Submit button calls `POST /submissions/{caseId}/upload-additional`
  - After upload, show "Documents uploaded — your analyst will review and continue processing"
  - Keep polling active (status will update when analyst triggers re-processing)

**In Step 3 (Verification) APPROVED view**:
- Add Income Verification card with green status

### 4.3 Modify: `frontend/src/components/Dashboard.tsx`

- Add Income Verification section in case detail panel
- Show risk classification badge (LOW=green, MEDIUM=orange, HIGH=red) and risk score
- Show "Additional Documents Requested" status badge
- Show list of requested documents + reasons when status is ADDITIONAL_DOCUMENTS_REQUESTED
- **Add "Re-process" button** for analyst when status is ADDITIONAL_DOCUMENTS_REQUESTED and new files have been uploaded
  - Calls `POST /submissions/{caseId}/reprocess`
  - Shows confirmation toast

### 4.4 Modify: `frontend/src/components/Escalation.tsx` (if needed)

- Add `ADDITIONAL_DOCUMENTS_REQUESTED` as a case type in escalation view
- Show document request context in escalation details

**Files**: `frontend/src/types.ts`, `frontend/src/components/Uploader.tsx`, `frontend/src/components/Dashboard.tsx`

---

## Phase 5: Mock Service + Test Data

**Goal**: Create mock income verification API and test scenarios.

### 5.1 New: `mock-service/mocks/uwv-polisadministratie.json`

Mock UWV Polisadministratie API (Dutch employment insurance registry — real schema reference).
Uses Dutch field names matching real UWV/Polisadministratie conventions.

- Endpoint: `POST /api/v1/uwv/polisadministratie/dienstverbanden`
- Request: `{ "burgerservicenummer": "123456789" }`
- Persistence key: `{{burgerservicenummer}}`
- Response schema (modeled on real UWV Polisadministratie + loonaangifte fields):
```json
{
  "burgerservicenummer": "123456789",
  "dienstverbanden": [
    {
      "werkgever": {
        "naam": "Tech Solutions BV",
        "kvkNummer": "12345678",
        "loonheffingennummer": "L1234567890"
      },
      "dienstverband": {
        "soort": "vast|tijdelijk|oproep",
        "startdatum": "2020-01-15",
        "einddatum": null,
        "beroep": "Software Engineer",
        "arbeidsuren": 40
      },
      "inkomen": {
        "svLoon": 48000,
        "brutoloonPeriode": 4000,
        "loonperiode": "maand",
        "vakantiegeld": 3840,
        "bijzondereBeloningen": 0
      },
      "periode": "2025"
    }
  ],
  "uitkeringen": [],
  "status": "GEVONDEN",
  "peildatum": "2026-03-15T10:00:00.000Z"
}
```

### 5.1b New: `mock-service/mocks/kvk-basisprofiel.json`

Mock KVK (Chamber of Commerce) Basisprofiel API for business ownership verification.
Uses **exact KVK API field names** from https://developers.kvk.nl/documentation/basisprofiel-api.

- Endpoint: `POST /api/v1/kvk/basisprofiel`
- Request: `{ "kvkNummer": "12345678" }`
- Persistence key: `{{kvkNummer}}`
- Response schema (matches real KVK Basisprofiel API):
```json
{
  "kvkNummer": "12345678",
  "naam": "Van den Berg Advies BV",
  "formeleRegistratiedatum": "2015-06-01",
  "statutaireNaam": "Van den Berg Advies B.V.",
  "handelsnamen": [{"naam": "Van den Berg Advies", "volgorde": 1}],
  "sbiActiviteiten": [
    {"sbiCode": "70221", "sbiOmschrijving": "Organisatieadviesbureaus", "indHoofdactiviteit": "Ja"}
  ],
  "eigenaar": {
    "rechtsvorm": "BeslotenVennootschap",
    "uitgebreideRechtsvorm": "Besloten Vennootschap",
    "rsin": "987654321"
  },
  "hoofdvestiging": {
    "vestigingsnummer": "123456789012",
    "eersteHandelsnaam": "Van den Berg Advies",
    "totaalWerkzamePersonen": 3,
    "adressen": [
      {
        "type": "bezoekadres",
        "straatnaam": "Herengracht",
        "huisnummer": 100,
        "postcode": "1015BS",
        "plaats": "Amsterdam"
      }
    ]
  },
  "_links": {}
}
```

See `docs/kyc-business-rules-and-references.md` for detailed schema source references.

### 5.2 Modify: `mock-service/src/data/default-test-cases.ts`

Add test cases for both UWV and KVK mocks, aligned with existing BRP/PEP personas:

**UWV Polisadministratie test cases**:

| BSN | Person | Scenario | Dienstverbanden |
|-----|--------|----------|-----------------|
| 123456789 | Jan de Vries | Clean: employed EUR 48K/yr | Tech Solutions BV, vast, 40hr, svLoon 48000 |
| 987654321 | Maria Bakker | No records found | Empty dienstverbanden, status NIET_GEVONDEN |
| 555666777 | Ahmed Al-Rashid | Suspicious: EUR 250K temp contract | International Trading GmbH, tijdelijk, svLoon 250000 |
| 111222333 | Willem van den Berg | PEP dual income: govt + zzp | Rijksoverheid (vast, 95K) + listed as zzp |

**KVK Basisprofiel test cases** (for business ownership verification):

| KVK | Person | Scenario |
|-----|--------|----------|
| 87654321 | Willem van den Berg | Van den Berg Advies BV, organisatieadvies, 3 employees |

### 5.3 Modify: `mock-service/src/server.ts`

Import and seed income test cases on startup.

### 5.4 Modify: `utils/kyc_publisher.py`

Add income file reference to `DUMMY_RECORD.files` array.

### 5.5 New: `docs/kyc-business-rules-and-references.md`

Comprehensive reference document covering:
- All mock API schema sources and why each field was chosen
- Dutch Wwft requirements for source-of-funds verification
- KYC process flow with regulatory references
- Income document types and what triggers additional document requests
- Risk classification logic rationale
- Links to original Dutch government API documentation

**Files**: `mock-service/mocks/uwv-polisadministratie.json` (new), `mock-service/mocks/kvk-basisprofiel.json` (new), `docs/kyc-business-rules-and-references.md` (new), `mock-service/src/data/default-test-cases.ts`, `mock-service/src/server.ts`, `utils/kyc_publisher.py`

---

## Phase 6: Reference Documentation

**Goal**: Document all business rules, mock API schema sources, and regulatory references so decisions are traceable.

### 6.1 New: `docs/kyc-business-rules-and-references.md`

Structure: **Quick Look at top** (1-page summary for scanning) → **Detailed deep-dives grouped by section** (for non-business users who need full context).

---

#### PART A: Quick Look (top of document)

A concise table/summary covering:
- What this system does (KYC = verifying customer identity + income + risk before opening a bank account)
- The 5 checks performed (identity docs, income/source of funds, PEP screening, sanctions, adverse media)
- What law governs this (Wwft) and who supervises (DNB)
- Decision outcomes: APPROVED / ADDITIONAL_DOCUMENTS_REQUESTED / ESCALATED
- Risk tiers at a glance: LOW (auto-approve), MEDIUM (review), HIGH (escalate)

---

#### PART B: Deep Dives (grouped sections)

**Section 1: What is KYC and Why Does It Exist?**

Explains in plain language:
- KYC = Know Your Customer. Banks must verify who you are before letting you open an account
- This exists because of money laundering — criminals try to move illegal money through banks
- The Netherlands has a law called **Wwft** (Wet ter voorkoming van witwassen en financieren van terrorisme = "Act for preventing money laundering and terrorist financing")
- The EU has directives (AMLD5, AMLD6) that all member states must follow
- **DNB** (De Nederlandsche Bank) supervises Dutch financial institutions for Wwft compliance
- If a bank fails to do proper KYC, they can be fined millions (real examples: ING fined EUR 775M in 2018)

**Sources**:
- DNB Wwft introduction: https://www.dnb.nl/en/sector-information/open-book-supervision/laws-and-eu-regulations/anti-money-laundering-and-anti-terrorist-financing-act/introduction-wwft/
- DNB Leidraad Wwft (full guidance PDF): https://www.dnb.nl/media/chqnfjjh/leidraad-wwft-sw-eng.pdf
- Business.gov.nl CDD guide: https://business.gov.nl/regulations/prevent-money-laundering-terrorist-financing/
- EU AMLD overview: https://www.lseg.com/en/risk-intelligence/financial-crime-risk-management/eu-anti-money-laundering-directive

---

**Section 2: The KYC Process — What Gets Checked**

Step-by-step explanation of our 5-agent pipeline mapped to real KYC:

1. **Identity Verification** (Identity Verification Agent)
   - What: Verify passport/ID is real and matches what the person claimed
   - Real process: Banks check MRZ (machine-readable zone), compare against BRP (government registry)
   - Our implementation: Textract OCR → BRP API lookup → LLM comparison across 3 sources
   - Decision: MATCH / PARTIAL_MATCH / MISMATCH

2. **Income & Source of Funds** (Income Verification Agent) — **NEW**
   - What: Verify where the customer's money comes from (Wwft Art. 3 obligation)
   - Why: Banks must understand the "economic rationale" of the relationship
   - Real process: Review bank statements, verify employment, check business registration
   - Our implementation: Textract OCR → UWV registry check → optional KVK check → LLM analysis
   - Decision: VERIFIED / INSUFFICIENT / SUSPICIOUS / UNREADABLE

3. **PEP Screening** (Risk List Screening Agent)
   - What: Check if the person is a Politically Exposed Person (PEP)
   - Why: PEPs are higher risk for corruption/bribery (Wwft Art. 1, AMLD Art. 3)
   - Real process: Screen against PEP databases (e.g., World-Check, Dow Jones, OpenSanctions)
   - Our implementation: Mock OpenSanctions API with FollowTheMoney entity format

4. **Sanctions Screening** (same agent)
   - What: Check against EU/UN/OFAC sanctions lists
   - Why: It's illegal to do business with sanctioned individuals/entities
   - Real process: Screen against consolidated sanctions lists

5. **Adverse Media** (Adverse Media Agent)
   - What: Search public news for negative mentions (fraud, crime, corruption)
   - Why: Even if someone passes all lists, recent news may reveal risk
   - Real process: Commercial tools (Factiva, LexisNexis) or web search
   - Our implementation: DuckDuckGo search + LLM analysis

6. **Final Decision** (Orchestrator Agent)
   - Combines all 5 results + applies risk classification → APPROVE / ESCALATE / REQUEST DOCS

---

**Section 3: Income Document Types — What We Accept and Why**

Detailed explanation of each income document type, what it proves, what to look for, and red flags:

| Document Type | Dutch Name | What It Proves | Key Fields to Extract | Red Flags | Recency Requirement |
|---|---|---|---|---|---|
| Bank statement | Bankafschrift | Regular income deposits, spending patterns | Account holder, IBAN, transactions, balance | Large cash deposits, transfers from high-risk countries, unexplained large sums | Within 3 months |
| Employment contract | Arbeidsovereenkomst | Employment relationship, agreed salary | Employer, employee, job title, salary, contract type (vast/tijdelijk), start date | No employer details, unrealistic salary for role | Currently valid |
| Salary slip | Loonstrook | Actual payment received | Brutoloon, nettoloon, werkgever, vakantiegeld, BSN, period | Discrepancies with contract, missing employer details | Within 3 months |
| Tax return | Belastingaangifte (IB60/IBRI) | Total declared income to tax authority | Annual income, income type (Box 1/2/3) | Income much higher/lower than claimed | Most recent fiscal year |
| Business registration | KvK-uittreksel | Business ownership, activity type | KvK nummer, company name, SBI code, registered address, owner | Shell company indicators, recently registered | Current registration |
| Self-employed income | ZZP inkomstenverklaring | Income from self-employment | Revenue, business type, client list | Single-client dependency, very high income with no employees | Within 12 months |

---

**Section 4: Mock API Schemas — Sources and Decisions**

For each mock API, explains: what real system it represents, where we got the schema, which fields we included and why, and what we simplified.

**4a. BRP Personen API (existing mock)**
- **Real system**: Basisregistratie Personen — the Dutch civil registry maintained by RvIG
- **Real API**: Haal Centraal BRP Personen API v2
- **Schema source**: GitHub OpenAPI spec at https://github.com/BRP-API/Haal-Centraal-BRP-bevragen
- **Our mock endpoint**: `POST /api/v1/brp/personen/document-lookup`
- **Simplification**: Real API uses BSN as primary lookup; we use documentType + documentNumber (simpler for our flow where we have the document, not the BSN yet)
- **Fields used and why**:
  - `burgerservicenummer` — BSN, the Dutch social security number (9 digits). We need this to cross-reference with UWV
  - `naam.voornamen`, `naam.geslachtsnaam`, `naam.volledigeNaam` — Real API nesting. Used for identity comparison
  - `geboorte.datum`, `geboorte.plaats`, `geboorte.land` — Date/place of birth for identity verification
  - `document.soort`, `document.nummer`, `document.datumEindeGeldigheid` — Document validity check
  - `status: "VERIFIED"` — Simplified; real API returns more granular status codes

**4b. PEP/Sanctions Match API (existing mock)**
- **Real system**: OpenSanctions — open-source sanctions/PEP database
- **Real API**: OpenSanctions Match API (https://www.opensanctions.org/docs/api/matching/)
- **Schema source**: FollowTheMoney (FtM) entity format specification
- **Our mock endpoint**: `POST /api/v1/pep/match`
- **Fields used and why**:
  - `responses.q1.results[]` — Array of matching entities (standard FtM batch response format)
  - `datasets: ["pep_world", "sanctions"]` — Which watchlist the match came from
  - `properties.position` — PEP role (e.g., "Former Minister") — determines risk level
  - `schema: "Person"` — FtM entity type

**4c. UWV Polisadministratie API (new mock)**
- **Real system**: UWV (Uitvoeringsinstituut Werknemersverzekeringen) — Dutch Employee Insurance Agency
- **What it contains**: Every employer in NL submits monthly wage declarations (loonaangiftes) to the Polisadministratie. It contains all employment records, wages, and benefits
- **Schema source**: UWV Gegevensdiensten product catalog (https://www.uwv.nl/nl/gegevensdiensten/gegevensproducten), Dutch loonstrook (payslip) legal standards, Novum mock API patterns (https://packagist.org/packages/novum/api-uwv)
- **Our mock endpoint**: `POST /api/v1/uwv/polisadministratie/dienstverbanden`
- **Why we chose these specific fields**:
  - `dienstverbanden[]` — "employment relationships" — the core UWV data structure (one entry per employer)
  - `werkgever.naam`, `werkgever.kvkNummer` — Employer identification (allows KVK cross-check)
  - `werkgever.loonheffingennummer` — Wage tax number (unique per employer, used in all loonaangiftes)
  - `dienstverband.soort: "vast|tijdelijk|oproep"` — Contract type. "vast" = permanent, "tijdelijk" = temporary, "oproep" = on-call. Important for income stability assessment
  - `inkomen.svLoon` — "Sociaal Verzekeringsloon" (Social Insurance Wage) — THE primary income figure in the Dutch system, used for all benefit calculations. This is what UWV actually stores
  - `inkomen.brutoloonPeriode` — Gross wage per period. Standard payslip field
  - `inkomen.vakantiegeld` — Holiday allowance (legally 8% of gross annual in NL). Its presence confirms legitimate Dutch employment
  - `uitkeringen[]` — Benefits (unemployment, disability). Empty for employed people, populated for benefit recipients
  - `status: "GEVONDEN|NIET_GEVONDEN"` — Dutch for "found/not found". Using Dutch matches real UWV response patterns
- **What we simplified**: Real UWV data includes many more fields (arbeidsuren, cao, sector, risicopremie). We kept only fields relevant to income verification

**4d. KVK Basisprofiel API (new mock)**
- **Real system**: Kamer van Koophandel (Chamber of Commerce) — Dutch business registry
- **Real API**: KVK Basisprofiel API v1
- **Schema source**: **EXACT real API documentation** at https://developers.kvk.nl/documentation/basisprofiel-api (with test endpoint at https://api.kvk.nl/test/api/v1/)
- **Our mock endpoint**: `POST /api/v1/kvk/basisprofiel`
- **Note**: Our mock uses POST for consistency with other mocks; real KVK API uses GET with path parameter
- **Fields are 1:1 with real API**:
  - `kvkNummer` — 8-digit KVK registration number (real field name)
  - `naam` — Business name (real field name)
  - `formeleRegistratiedatum` — Registration date (real field name)
  - `statutaireNaam` — Statutory name (real field name)
  - `handelsnamen[]` — Trade names (real field name and structure)
  - `sbiActiviteiten[]` — SBI activity codes (Dutch NACE equivalent). `sbiCode` + `sbiOmschrijving` + `indHoofdactiviteit` — all real field names. Used to understand what the business does
  - `eigenaar.rechtsvorm` — Legal form (BeslotenVennootschap, Eenmanszaak, etc.). Real field name
  - `hoofdvestiging.vestigingsnummer` — 12-digit branch number (real field name)
  - `hoofdvestiging.totaalWerkzamePersonen` — Total employees. Real field name. Helps assess business legitimacy
  - `hoofdvestiging.adressen[]` — Address with type, straatnaam, huisnummer, postcode, plaats — all real field names

---

**Section 5: Risk Classification — How We Decide**

Explains risk tiers with concrete examples:

**LOW Risk** (auto-approve):
- All checks pass (identity MATCH, income VERIFIED, PEP CLEAR, sanctions CLEAR, media OK)
- Standard employment income from established Dutch/EU employer
- Monthly income under EUR 10,000 (reasonable for most employment)
- Example: Jan de Vries, employed at Tech Solutions BV, EUR 4,000/month, no hits anywhere

**MEDIUM Risk** (enhanced review, may auto-approve with justification):
- Minor identity discrepancies (PARTIAL_MATCH — e.g., middle name missing)
- PEP match BUT no adverse media and no sanctions → requires Enhanced Due Diligence (EDD)
- Self-employment or business ownership income (harder to verify)
- Multiple income sources
- Example: Willem van den Berg, former government official (PEP), owns consulting BV

**HIGH Risk** (must escalate to human):
- Any sanctions hit → immediate escalation (EU regulation, no discretion)
- Adverse media NOK (fraud, crime, corruption found)
- Document MISMATCH (possible fraud)
- SUSPICIOUS income (implausible amounts, unexplained sources, high-risk jurisdiction transfers)
- Multiple risk indicators from different stages
- Example: Ahmed Al-Rashid, EUR 250K temporary contract + sanctions dataset match

**Sources**: DNB risk-based approach guidelines, Wwft Art. 3 (CDD), Art. 8 (EDD for PEPs)

---

**Section 6: Additional Document Triggers — When and What to Request**

| Trigger Condition | What to Request | Why (Regulatory Basis) |
|---|---|---|
| Income doc INSUFFICIENT (can't determine source) | Specific doc based on detected income type: loonstrook for employment, KvK-uittreksel for business, belastingaangifte for mixed | Wwft Art. 3(2)(d): must establish source of funds |
| Income doc UNREADABLE (scan quality, wrong format) | Re-upload of same document in better quality | CDD completeness — can't verify what you can't read |
| Income plausibility concern (declared income doesn't match employment) | Tax return (belastingaangifte) or additional bank statements | DNB guideline: verify "economic rationale" |
| Self-employed with no business registration | KvK-uittreksel (Chamber of Commerce extract) | NL law requires all businesses to register with KvK |
| High income (>EUR 10K/month) without clear employment | Additional proof: employer reference letter, tax return, accountant statement | EDD trigger under DNB guidelines |
| Multiple income sources detected | Documentation for each source separately | Wwft: all material income sources must be verified |

---

**Section 7: Dutch Terminology Reference**

| Dutch Term | English | Where Used | Notes |
|---|---|---|---|
| burgerservicenummer (BSN) | Social Security Number | BRP, UWV | 9-digit, universal Dutch identifier |
| dienstverband | Employment relationship | UWV | One per employer |
| werkgever | Employer | UWV, loonstrook | |
| brutoloon | Gross salary | UWV, loonstrook | Before tax/deductions |
| nettoloon | Net salary | Loonstrook | After tax/deductions |
| svLoon | Social Insurance Wage | UWV | Primary income metric in Dutch system |
| vakantiegeld | Holiday allowance | UWV, loonstrook | Legally 8% of gross annual |
| loonstrook | Payslip/salary slip | Income docs | Monthly payslip from employer |
| arbeidsovereenkomst | Employment contract | Income docs | vast=permanent, tijdelijk=temporary |
| bankafschrift | Bank statement | Income docs | |
| belastingaangifte | Tax return | Income docs | Annual to Belastingdienst |
| KvK-uittreksel | Chamber of Commerce extract | KVK API | Business registration proof |
| kvkNummer | KVK Number | KVK API | 8-digit business registration number |
| vestigingsnummer | Branch number | KVK API | 12-digit, identifies specific location |
| sbiActiviteiten | SBI Activity codes | KVK API | Dutch NACE equivalent for business classification |
| rechtsvorm | Legal form | KVK API | BeslotenVennootschap, Eenmanszaak, etc. |
| Wwft | Anti-Money Laundering Act | Regulatory | Full: Wet ter voorkoming van witwassen en financieren van terrorisme |
| DNB | De Nederlandsche Bank | Regulatory | Dutch central bank, Wwft supervisor |
| zzp | Self-employed | Income category | Zelfstandige zonder personeel |

---

## File Summary

### New Files (6)
| File | Purpose |
|------|---------|
| `crew/tools/analyze_income_tool.py` | LLM income analysis tool (Bedrock Converse, Wwft rules, multi-page summarization) |
| `crew/tools/verify_income_tool.py` | UWV Polisadministratie + KVK Basisprofiel API callers |
| `crew/update_income_result.py` | DynamoDB/S3 callback for income stage |
| `mock-service/mocks/uwv-polisadministratie.json` | Mock UWV employment/income registry API (real schema) |
| `mock-service/mocks/kvk-basisprofiel.json` | Mock KVK business registration API (real schema) |
| `docs/kyc-business-rules-and-references.md` | Business rules rationale, mock schema sources, regulatory references |

### Modified Files (12)
| File | Changes |
|------|---------|
| `crew/crew.py` | Add income agent + task, update orchestrator context + crew lists |
| `crew/config/agents.yaml` | Add income_verification_agent, update orchestrator backstory with Wwft |
| `crew/config/tasks.yaml` | Add income_verification_task, update orchestrator_task |
| `crew/update_orchestrator_result.py` | Add risk_classification, risk_score, additional_documents_needed, new status |
| `crew/tools/escalate_human_tool.py` | Add additional_documents_needed field |
| `backend/main.py` | New models, 3 new endpoints, updated CaseStages |
| `frontend/src/types.ts` | Add IncomeVerificationStage, update stages types |
| `frontend/src/components/Uploader.tsx` | Income stage card, additional docs upload UI |
| `frontend/src/components/Dashboard.tsx` | Income panel, risk display, re-process button |
| `mock-service/src/data/default-test-cases.ts` | Income test cases |
| `mock-service/src/server.ts` | Seed income test cases |
| `utils/kyc_publisher.py` | Add income file to dummy record |

---

## Verification Plan

### Per-phase testing:
1. **Phase 1**: Run `python -m crew.kyc_app` locally, invoke with a test caseId that has income files. Verify Textract extraction + LLM analysis produces valid JSON. Check DynamoDB has `stages.incomeVerification`.
2. **Phase 2**: Verify orchestrator output includes `risk_classification`, `risk_score`. Test with clean case (expect APPROVED, LOW risk) and insufficient income case (expect ADDITIONAL_DOCUMENTS_REQUIRED).
3. **Phase 3**: Run backend with `uvicorn`, test new endpoints via curl/Swagger (`/docs`). Upload additional docs, verify S3 + DynamoDB updates. Test reprocess endpoint.
4. **Phase 4**: Run `npm run dev` in frontend. Submit a KYC case, verify income stage card appears. Test additional docs flow with a case in ADDITIONAL_DOCUMENTS_REQUESTED status.
5. **Phase 5**: Run `npm run dev` in mock-service. Verify `POST /api/v1/uwv/polisadministratie/dienstverbanden` returns seeded test data. Verify `POST /api/v1/kvk/basisprofiel` works. Check `GET /admin/mocks` shows all 4 registered endpoints (BRP, PEP, UWV, KVK).

6. **Phase 6**: Review `docs/kyc-business-rules-and-references.md` for completeness. Verify all source URLs are valid.

### End-to-end:
- Start mock service → start backend → start frontend → submit KYC with test persona Jan de Vries → watch all 5 stages complete → expect APPROVED
- Repeat with Maria Bakker data → expect ADDITIONAL_DOCUMENTS_REQUESTED with specific document requests shown in UI
