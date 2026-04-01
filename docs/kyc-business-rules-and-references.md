# KYC Business Rules and Reference Documentation

## Quick Look

| Item | Detail |
|------|--------|
| **What this system does** | Automates KYC (Know Your Customer) verification — the process banks must complete before opening an account. Verifies identity, income source, and screens for financial crime risk. |
| **Governing law** | Wwft — Wet ter voorkoming van witwassen en financieren van terrorisme (Dutch Anti-Money Laundering Act) |
| **EU framework** | AMLD5 (5th Anti-Money Laundering Directive) and AMLD6 |
| **Supervisor** | DNB — De Nederlandsche Bank (Dutch central bank) |
| **5 checks performed** | 1. Identity document verification (BRP) 2. Income & source of funds (UWV/KVK) 3. PEP screening 4. Sanctions screening 5. Adverse media |
| **Decision outcomes** | APPROVED / ADDITIONAL_DOCUMENTS_REQUESTED / ESCALATED (to human review) |
| **Risk tiers** | LOW = auto-approve, MEDIUM = enhanced review, HIGH = must escalate to human |
| **Mock APIs used** | BRP Personen (identity), PEP/Sanctions (OpenSanctions), UWV Polisadministratie (employment/income), KVK Basisprofiel (business registration) |

---

## Section 1: What is KYC and Why Does It Exist?

### The Problem: Money Laundering

Money laundering is the process of making illegally-obtained money appear legitimate. Criminals use banks, real estate, and businesses to "clean" money from drug trafficking, fraud, corruption, and other crimes. The United Nations estimates that 2-5% of global GDP is laundered annually.

### The Solution: Know Your Customer (KYC)

Banks are legally required to verify who their customers are before allowing them to open accounts or conduct transactions. This process is called KYC — Know Your Customer. It exists to:

1. **Prevent money laundering** — Stop criminals from using the banking system
2. **Combat terrorist financing** — Block funds flowing to terrorist organizations
3. **Detect fraud** — Identify stolen or forged identity documents
4. **Comply with law** — Avoid massive fines (ING was fined EUR 775 million in 2018 for Wwft failures)

### Dutch Law: Wwft

The Netherlands has its own anti-money laundering law called **Wwft** (pronounced roughly "way-weh-teh-eff"):

- **Full name**: Wet ter voorkoming van witwassen en financieren van terrorisme
- **English**: Act for preventing money laundering and terrorist financing
- **What it requires**: All financial institutions must perform Customer Due Diligence (CDD) — verifying identity, understanding the business relationship, and monitoring transactions
- **Who enforces it**: DNB (De Nederlandsche Bank) for banks and financial institutions

### EU Framework: AMLD5 and AMLD6

The EU Anti-Money Laundering Directives set minimum standards that all EU member states must implement:

- **AMLD5** (2018): Enhanced due diligence for high-risk countries, beneficial ownership registers, regulation of virtual currencies
- **AMLD6** (2024): Harmonized list of predicate offences, expanded liability, minimum penalties

The Dutch Wwft implements these EU directives into national law.

### Sources

- DNB Wwft introduction: https://www.dnb.nl/en/sector-information/open-book-supervision/laws-and-eu-regulations/anti-money-laundering-and-anti-terrorist-financing-act/introduction-wwft/
- DNB Leidraad Wwft (full guidance, English): https://www.dnb.nl/media/chqnfjjh/leidraad-wwft-sw-eng.pdf
- Business.gov.nl CDD guide: https://business.gov.nl/regulations/prevent-money-laundering-terrorist-financing/
- EU AMLD overview (LSEG): https://www.lseg.com/en/risk-intelligence/financial-crime-risk-management/eu-anti-money-laundering-directive
- ING fine (2018): https://www.om.nl/actueel/nieuws/2018/09/04/ing-pays-775-million-due-to-serious-shortcomings-in-money-laundering-prevention

---

## Section 2: The KYC Process — What Gets Checked

Our system performs 5 sequential checks, each handled by a dedicated AI agent. Here is what each check does and how it maps to real-world KYC:

### Check 1: Identity Document Verification

| Aspect | Detail |
|--------|--------|
| **What** | Verify the passport/ID is real and matches what the person claimed |
| **Real-world process** | Banks check the MRZ (machine-readable zone on passports), compare photo, and verify against BRP (government civil registry) |
| **Our implementation** | AWS Textract OCR extracts text from uploaded documents, then BRP API lookup verifies the document exists in the government registry, then an LLM compares identity fields across 3 sources (user input, OCR extraction, government data) |
| **Agent** | Identity Verification Agent |
| **Decision values** | MATCH (all consistent), PARTIAL_MATCH (minor discrepancies), MISMATCH (significant differences) |
| **Regulatory basis** | Wwft Art. 3(2)(a): identify and verify identity using reliable, independent source |

### Check 2: Income and Source of Funds Verification

| Aspect | Detail |
|--------|--------|
| **What** | Verify where the customer's money comes from |
| **Why this matters** | Banks must understand the "economic rationale" of the relationship — why does this person need a bank account and where does their money come from? |
| **Real-world process** | Review bank statements, verify employment with UWV (employment registry), check business registration with KVK (Chamber of Commerce) |
| **Our implementation** | Textract OCR extracts text from income documents (bank statements, contracts, salary slips), UWV API verifies employment records, KVK API verifies business registration (if applicable), then LLM analyzes everything against Wwft rules |
| **Agent** | Income Verification Agent |
| **Decision values** | VERIFIED (income confirmed), INSUFFICIENT (not enough info — request more docs), SUSPICIOUS (red flags found), UNREADABLE (document quality too poor) |
| **Regulatory basis** | Wwft Art. 3(2)(d): establish source of funds; DNB guideline on economic rationale |

### Check 3: PEP Screening

| Aspect | Detail |
|--------|--------|
| **What** | Check if the person is a Politically Exposed Person |
| **Who is a PEP** | Heads of state, government ministers, members of parliament, senior military officers, judges, central bank board members, state-owned enterprise directors, and their family members and close associates |
| **Why this matters** | PEPs are at higher risk for corruption and bribery due to their positions of power |
| **Real-world process** | Screen against commercial databases (World-Check, Dow Jones) or open databases (OpenSanctions) |
| **Our implementation** | Mock OpenSanctions API using FollowTheMoney entity format |
| **Regulatory basis** | Wwft Art. 1 (PEP definition), Art. 8 (Enhanced Due Diligence for PEPs) |

### Check 4: Sanctions Screening

| Aspect | Detail |
|--------|--------|
| **What** | Check against EU, UN, and OFAC sanctions lists |
| **Why this matters** | It is illegal to provide financial services to sanctioned individuals or entities. No discretion — if there's a sanctions match, the bank MUST refuse service and report |
| **Real-world process** | Screen against consolidated sanctions lists (EU Consolidated List, UN Security Council, OFAC SDN) |
| **Our implementation** | Combined with PEP screening in the same mock API; datasets field indicates whether match is "pep_world" or "sanctions" |
| **Regulatory basis** | EU Council Regulation, Sanctiewet 1977 (Dutch Sanctions Act) |

### Check 5: Adverse Media Screening

| Aspect | Detail |
|--------|--------|
| **What** | Search public news and media for negative mentions about the person |
| **Why this matters** | Even if someone doesn't appear on any watchlist, recent news about fraud, crime, corruption, or investigations is a risk indicator |
| **Real-world process** | Commercial tools (Factiva by Dow Jones, LexisNexis) or structured web searches |
| **Our implementation** | DuckDuckGo web search with structured queries, then LLM analyzes search results for genuine adverse findings |
| **Decision values** | OK (no adverse findings), NOK (adverse media found), PENDING_REVIEW (unclear, needs human judgment) |
| **Regulatory basis** | DNB guideline: ongoing monitoring and risk assessment |

### Check 6: Final Decision (Orchestrator)

The orchestrator agent receives all 5 results and applies risk classification rules to make the final decision:

- **APPROVED**: All checks pass, risk is LOW
- **ADDITIONAL_DOCUMENTS_REQUESTED**: Income verification needs more documents (specific list provided)
- **ESCALATED**: Risk factors detected that require human judgment

---

## Section 3: Income Document Types — What We Accept and Why

Under Wwft, banks must verify the source of funds for every customer. Different income types require different documents:

### Bank Statement (Bankafschrift)

- **What it proves**: Regular income deposits, spending patterns, account ownership
- **Key fields to extract**: Account holder name, IBAN, list of transactions with descriptions, dates, amounts, ending balance
- **What we look for**: Regular salary deposits from a recognizable employer, consistent income pattern
- **Red flags**: Large unexplained cash deposits (> EUR 15,000 triggers Wwft reporting), transfers from high-risk jurisdictions (per EU high-risk third country list), sudden large incoming transfers without clear source
- **Recency requirement**: Within 3 months of submission
- **Regulatory basis**: Wwft Art. 16 (unusual transaction reporting for cash > EUR 15,000)

### Employment Contract (Arbeidsovereenkomst)

- **What it proves**: Employment relationship exists, agreed salary terms
- **Key fields to extract**: Employer name, employee name, job title, start date, salary amount, salary frequency, contract type (vast = permanent, tijdelijk = temporary, oproep = on-call)
- **What we look for**: Contract is with a real, registered employer (can cross-check with KVK), salary is reasonable for the role
- **Red flags**: No employer identification details, salary unrealistically high for stated role, contract with a company in a high-risk jurisdiction
- **Recency requirement**: Must be currently valid (not expired)

### Salary Slip (Loonstrook)

- **What it proves**: Actual payment was received (not just promised in a contract)
- **Key fields to extract**: Werkgever (employer), werknemer (employee), brutoloon (gross salary), nettoloon (net salary), vakantiegeld (holiday allowance — legally 8% in NL), BSN, pay period
- **What we look for**: Employer matches contract, amounts match contract, BSN matches applicant
- **Red flags**: Discrepancies between loonstrook and arbeidsovereenkomst, missing employer details, no BSN
- **Recency requirement**: Within 3 months
- **Dutch legal standard**: All Dutch employers must provide monthly loonstroken per the Wet op de loonbelasting

### Tax Return (Belastingaangifte / IB60 / IBRI)

- **What it proves**: Total declared income to the Dutch tax authority (Belastingdienst)
- **Key fields to extract**: Annual income, income type (Box 1: work and housing, Box 2: substantial interest, Box 3: savings and investments)
- **What we look for**: Declared income consistent with other documents, income type matches claimed source
- **Red flags**: Income much higher or lower than shown on loonstroken/bank statements, income primarily from Box 3 (may indicate wealth from investments rather than employment)
- **Recency requirement**: Most recent fiscal year
- **Note**: Since 2013, the Belastingdienst issues IBRI (Inkomensverklaring Basisregistratie Inkomens) instead of IB60. It shows only total income, not breakdown by box.

### Business Registration (KvK-uittreksel)

- **What it proves**: A business is legally registered in the Netherlands, its activity type, and ownership
- **Key fields to extract**: KvK nummer (8-digit registration number), company name, SBI activity code (Dutch NACE equivalent — describes what the business does), registration date, legal form (BV, eenmanszaak, etc.), number of employees, registered address
- **What we look for**: Business actually exists and is active, activity type matches claimed business, registration date is not suspiciously recent
- **Red flags**: Very recently registered (< 6 months) with high claimed income, shell company indicators (no employees, no physical address, vague activity description), registered at a known "virtual office" address
- **Recency requirement**: Current registration (not deregistered)
- **Source**: KVK Handelsregister (Trade Register), accessible via KVK API

### Self-Employed Income (ZZP)

- **What it proves**: Income from self-employment (ZZP = Zelfstandige Zonder Personeel = self-employed without employees)
- **Key fields to extract**: Revenue, business type, client list if available
- **What we look for**: KVK registration exists, income declared to Belastingdienst, bank statements show business income
- **Red flags**: Single-client dependency (may actually be disguised employment), very high income with no employees or visible business activity
- **Recency requirement**: Within 12 months
- **Additional requirements**: ZZP income typically requires multiple supporting documents (KvK-uittreksel + bank statements + tax return) for adequate verification

---

## Section 4: Mock API Schemas — Sources and Decisions

This section documents exactly where each mock API schema comes from, what real system it represents, why specific fields were chosen, and what was simplified.

### 4a. BRP Personen API (Existing Mock)

| Aspect | Detail |
|--------|--------|
| **Real system** | Basisregistratie Personen (BRP) — the Dutch civil registry maintained by RvIG (Rijksdienst voor Identiteitsgegevens) |
| **Real API** | Haal Centraal BRP Personen API v2 |
| **Schema source** | OpenAPI specification on GitHub: https://github.com/BRP-API/Haal-Centraal-BRP-bevragen |
| **Our mock endpoint** | `POST /api/v1/brp/personen/document-lookup` |
| **Mock location** | `mock-service/mocks/brp-identity-verification.json` |

**How our mock differs from the real API**:
- Real API uses BSN (burgerservicenummer) as the primary lookup key
- Our mock uses documentType + documentNumber (because in our flow, we have the document first, not the BSN)
- Real API has many more fields (verblijfplaats, ouders, kinderen, partners). We only include identity-relevant fields

**Fields used and why**:

| Field | Real API Name | Why We Include It |
|-------|--------------|-------------------|
| `burgerservicenummer` | Same | The Dutch 9-digit social security number. We need this to cross-reference with UWV employment records |
| `naam.voornamen` | Same | First names — for identity comparison |
| `naam.geslachtsnaam` | Same | Family name — for identity comparison |
| `naam.volledigeNaam` | Same | Full name as registered — primary comparison field |
| `geboorte.datum` | Same | Date of birth — key identity field |
| `geboorte.plaats` | Same | Place of birth — secondary identity field |
| `geboorte.land` | Same | Country of birth |
| `document.soort` | Same | Document type (paspoort, identiteitskaart, rijbewijs) |
| `document.nummer` | Same | Document number — links to the physical document |
| `document.datumEindeGeldigheid` | Same | Expiry date — we check the document hasn't expired |
| `status` | Simplified | Real API doesn't have a simple status field; we added "VERIFIED" for clarity |

### 4b. PEP/Sanctions Match API (Existing Mock)

| Aspect | Detail |
|--------|--------|
| **Real system** | OpenSanctions — an open-source international sanctions and PEP database |
| **Real API** | OpenSanctions Match API |
| **Schema source** | API documentation at https://www.opensanctions.org/docs/api/matching/ and FollowTheMoney entity format |
| **Our mock endpoint** | `POST /api/v1/pep/match` |
| **Mock location** | `mock-service/mocks/pep-match.json` |

**Fields used and why**:

| Field | Source Format | Why We Include It |
|-------|-------------|-------------------|
| `responses.q1.results[]` | Standard FtM batch response | Array of matching entities — the core response structure |
| `id` | FtM entity ID | Unique identifier for the matched entity (e.g., "NK-pep-willem-001") |
| `schema` | FtM schema | Always "Person" in our case — identifies the entity type |
| `caption` | FtM field | Display name of the matched entity |
| `datasets` | FtM field | Critical field — tells us WHICH list matched: "pep_world" (PEP database) or "sanctions" (sanctions list). This determines the risk level |
| `properties.name` | FtM property | Full name(s) of the entity |
| `properties.position` | FtM property | PEP role (e.g., "Former Minister", "Government Official") — helps assess risk severity |
| `properties.nationality` | FtM property | Nationality — relevant for jurisdiction assessment |

### 4c. UWV Polisadministratie API (New Mock)

| Aspect | Detail |
|--------|--------|
| **Real system** | UWV (Uitvoeringsinstituut Werknemersverzekeringen) — the Dutch Employee Insurance Agency |
| **What it contains** | The Polisadministratie is the central Dutch employment registry. Every employer in the Netherlands submits monthly wage declarations (loonaangiftes) to the UWV. It contains records of all employment relationships, wages, and social insurance contributions |
| **Schema sources** | UWV Gegevensdiensten product catalog (https://www.uwv.nl/nl/gegevensdiensten/gegevensproducten), Dutch payslip (loonstrook) legal standards, Novum Innovation Lab mock API (https://packagist.org/packages/novum/api-uwv) |
| **Our mock endpoint** | `POST /api/v1/uwv/polisadministratie/dienstverbanden` |
| **Mock location** | `mock-service/mocks/uwv-polisadministratie.json` |

**Why the UWV Polisadministratie?**
The Polisadministratie is THE authoritative source for employment and income data in the Netherlands. When a bank needs to verify someone's employment income, this is the government registry they would ideally check. It's more reliable than documents the customer provides (which could be forged).

**Fields used and why**:

| Field | Why We Include It | Source/Standard |
|-------|-------------------|----------------|
| `burgerservicenummer` | Lookup key — links to BRP identity | Standard Dutch identifier |
| `dienstverbanden[]` | "Employment relationships" — one entry per employer. This IS the core UWV data structure | UWV Polisadministratie structure |
| `werkgever.naam` | Employer name — cross-reference with income documents | Loonaangifte field |
| `werkgever.kvkNummer` | Employer's KVK number — allows cross-check with KVK business registry | Loonaangifte field |
| `werkgever.loonheffingennummer` | Employer's wage tax number — unique identifier used in all loonaangiftes, confirms employer is registered with Belastingdienst | Loonaangifte mandatory field |
| `dienstverband.soort` | Contract type: "vast" (permanent), "tijdelijk" (temporary), "oproep" (on-call). Critical for assessing income stability | UWV classification |
| `dienstverband.startdatum` | Employment start date — tenure affects income reliability assessment | Loonaangifte field |
| `dienstverband.beroep` | Job title/occupation — for plausibility check (does the salary match the role?) | Loonaangifte field |
| `inkomen.svLoon` | Sociaal Verzekeringsloon (Social Insurance Wage) — THE primary income figure in the Dutch system. This is what UWV actually stores and uses for all benefit calculations. More authoritative than self-reported income | Core UWV metric |
| `inkomen.brutoloonPeriode` | Gross wage per pay period — standard payslip field, allows monthly income calculation | Loonstrook standard |
| `inkomen.loonperiode` | Pay frequency: "maand" (monthly), "4-weken" (4-weekly), "week" (weekly) | Loonaangifte field |
| `inkomen.vakantiegeld` | Holiday allowance — legally 8% of gross annual salary in the Netherlands. Its presence confirms legitimate Dutch employment (all Dutch employers must pay this) | Dutch law (Wet minimumloon) |
| `uitkeringen[]` | Benefits (unemployment, disability). Empty for employed people. If populated, indicates the person receives government benefits rather than employment income | UWV benefit records |
| `status` | "GEVONDEN" (found) or "NIET_GEVONDEN" (not found). Using Dutch matches real UWV response patterns | UWV convention |
| `peildatum` | Reference date of the data — indicates when this information was last updated | UWV standard field |

**What we simplified**: Real UWV Polisadministratie data includes many additional fields: arbeidsuren (working hours), CAO (collective labor agreement), sector code, risicopremiegroep (risk premium group), indicatie premiekorting (premium discount indicator), and detailed historical records per period. We kept only fields directly relevant to KYC income verification.

### 4d. KVK Basisprofiel API (New Mock)

| Aspect | Detail |
|--------|--------|
| **Real system** | Kamer van Koophandel (KVK) — the Dutch Chamber of Commerce |
| **What it contains** | The Handelsregister (Trade Register) — all businesses registered in the Netherlands. Every business must register with the KVK by law |
| **Real API** | KVK Basisprofiel API v1 |
| **Schema source** | **EXACT real API documentation** at https://developers.kvk.nl/documentation/basisprofiel-api |
| **Test endpoint** | Real test environment available at https://api.kvk.nl/test/api/v1/ (test key: l7xx1f2691f2520d487b902f4e0b57a0b197) |
| **Our mock endpoint** | `POST /api/v1/kvk/basisprofiel` |
| **Mock location** | `mock-service/mocks/kvk-basisprofiel.json` |

**Important**: Our mock uses POST for consistency with other mock endpoints. The real KVK API uses GET with the KVK number as a path parameter (`GET /v1/basisprofielen/{kvkNummer}`).

**Fields are 1:1 with the real KVK API** (these are the exact field names from the official documentation):

| Field | Real API Field Name | Why We Include It |
|-------|-------------------|-------------------|
| `kvkNummer` | Identical | 8-digit KVK registration number — the primary business identifier in NL |
| `naam` | Identical | Business name as registered |
| `formeleRegistratiedatum` | Identical | When the business was registered — recent registration with high claimed income is a red flag |
| `statutaireNaam` | Identical | Statutory/legal name (may differ from trade name) |
| `handelsnamen[]` | Identical structure | Trade names — a business may operate under different names |
| `sbiActiviteiten[]` | Identical structure | SBI activity codes (Standaard Bedrijfsindeling — the Dutch equivalent of EU NACE classification). Tells us what the business actually does. Fields: `sbiCode`, `sbiOmschrijving` (description), `indHoofdactiviteit` (is it the main activity?) |
| `eigenaar.rechtsvorm` | Identical | Legal form: BeslotenVennootschap (BV = private limited company), NaamlozeVennootschap (NV = public company), Eenmanszaak (sole proprietorship), etc. |
| `eigenaar.uitgebreideRechtsvorm` | Identical | Full description of legal form |
| `eigenaar.rsin` | Identical | RSIN (Rechtspersonen en Samenwerkingsverbanden Identificatienummer) — legal entity identifier |
| `hoofdvestiging.vestigingsnummer` | Identical | 12-digit branch number identifying the main location |
| `hoofdvestiging.eersteHandelsnaam` | Identical | Primary trade name at this location |
| `hoofdvestiging.totaalWerkzamePersonen` | Identical | Total number of employees — helps assess if the business is real (a "consulting company" with EUR 500K revenue but 0 employees might be suspicious) |
| `hoofdvestiging.adressen[]` | Identical structure | Business address with `type` (bezoekadres/postadres), `straatnaam`, `huisnummer`, `postcode`, `plaats` — all real field names |

**Source**: https://developers.kvk.nl/documentation/basisprofiel-api

---

## Section 5: Risk Classification — How We Decide

Under Wwft, banks must take a "risk-based approach" — the level of scrutiny applied should match the risk level of the customer. Our system uses a **deterministic weighted scoring formula** to classify each case into one of three tiers. The score is computed in `crew/update_orchestrator_result.py` by reading the prior 4 agent stage results from DynamoDB (not from LLM output), ensuring the risk score is fully reproducible and auditable.

### Deterministic Scoring Formula

The risk score is the sum of four weighted factors (0-100 scale):

| Factor | Max Weight | LOW (0 pts) | MEDIUM | HIGH (max pts) |
|--------|-----------|-------------|--------|----------------|
| Identity result | 30 | MATCH: 0 | PARTIAL_MATCH: 15 | MISMATCH: 30 |
| Income result | 25 | VERIFIED (no flags): 0 | VERIFIED (with flags): 12 | INSUFFICIENT / SUSPICIOUS / UNREADABLE: 25 |
| PEP/Sanctions | 30 | CLEAR: 0 | PEP only: 15 | SANCTIONED: 30 |
| Adverse media | 15 | OK: 0 | PENDING_REVIEW: 8 | NOK: 15 |

**Score = sum of all factor points.** A `risk_score_breakdown` array is stored alongside the score, showing exactly how each factor contributed. This breakdown is available in DynamoDB and the orchestrator report for full auditability.

### Classification Thresholds

| Score Range | Classification | Action |
|-------------|---------------|--------|
| 0-30 | LOW | Auto-approve |
| 31-60 | MEDIUM | Enhanced review |
| 61-100 | HIGH | Must escalate to human |

**Note**: The classification drives the default action, but the orchestrator agent may still escalate cases that score LOW or MEDIUM based on business rules. For example, PEP cases always require human EDD sign-off under Wwft Art. 8, regardless of the numeric score.

### LOW Risk (Auto-approve)

**Criteria** (ALL must be true):
- Identity verification: MATCH (all documents consistent)
- Income verification: VERIFIED with no risk indicators
- PEP screening: CLEAR (no PEP match)
- Sanctions screening: CLEAR (no sanctions match)
- Adverse media: OK (no adverse findings)

**What happens**: Case is automatically approved. No human review needed.

**Example**: Jan de Vries — MATCH(0) + VERIFIED/no flags(0) + CLEAR(0) + OK(0) = **score 0, LOW**. Dutch citizen, employed at Tech Solutions BV (KVK-registered, 50+ employees), earning EUR 4,000/month. All documents match, no PEP/sanctions hits, no adverse media.

### MEDIUM Risk (Enhanced Review)

**Criteria** (any of these):
- Minor identity discrepancies (PARTIAL_MATCH — e.g., middle name missing, slight spelling variation)
- PEP match BUT no adverse media AND no sanctions hit
- Self-employment or business ownership income (inherently harder to verify)
- Multiple risk indicators that sum to 31-60

**What happens**: May be auto-approved with documented justification, or escalated for human review depending on the specific combination of factors. PEP matches always require Enhanced Due Diligence (EDD) under Wwft Art. 8.

**Example**: Maria Bakker — MISMATCH(30) + INSUFFICIENT(25) + CLEAR(0) + OK(0) = **score 55, MEDIUM**. Identity mismatch between claimed name ("Maria Jansen") and BRP record ("Maria Bakker"), plus no UWV employment records found. Despite the MEDIUM score, this case is escalated because identity MISMATCH requires human investigation.

### HIGH Risk (Must Escalate)

**Criteria** (any of these):
- ANY sanctions hit (no discretion — EU regulation requires refusal)
- Adverse media: NOK (fraud, crime, corruption found in news)
- Multiple compounding risk indicators scoring above 60

**What happens**: Case is immediately escalated to a human analyst. The system provides all collected evidence, the deterministic score breakdown, and a recommendation, but a human must make the final decision.

**Example**: Ahmed Al-Rashid — MATCH(0) + SUSPICIOUS(25) + SANCTIONED(30) + NOK(15) = **score 70, HIGH**. EUR 250,000/year on a temporary contract with International Trading GmbH (a company not registered in NL), AND a match on the sanctions dataset, AND adverse media findings. Multiple HIGH risk indicators — must be reviewed by a human analyst.

### Score Examples Across Test Cases

| Persona | Identity | Income | PEP/Sanctions | Adverse Media | Total | Classification |
|---------|----------|--------|---------------|---------------|-------|----------------|
| Jan de Vries | 0 (MATCH) | 0 (VERIFIED, no flags) | 0 (CLEAR) | 0 (OK) | **0** | LOW |
| Maria Bakker | 30 (MISMATCH) | 25 (INSUFFICIENT) | 0 (CLEAR) | 0 (OK) | **55** | MEDIUM |
| Ahmed Al-Rashid | 0 (MATCH) | 25 (SUSPICIOUS) | 30 (SANCTIONED) | 15 (NOK) | **70** | HIGH |
| Willem van den Berg | 0 (MATCH) | 12 (VERIFIED, 1 flag) | 15 (PEP only) | 0 (OK) | **27** | LOW* |

*Willem scores LOW (27) based on the deterministic formula, but the orchestrator still escalates this case because PEP status requires human EDD sign-off under Wwft Art. 8. The score reflects the data; the escalation action is a separate business rule decision.

### Regulatory Basis

- DNB risk-based approach: https://www.dnb.nl/media/chqnfjjh/leidraad-wwft-sw-eng.pdf (Chapter 4)
- Wwft Art. 3: Customer Due Diligence obligations
- Wwft Art. 8: Enhanced Due Diligence for PEPs
- Sanctiewet 1977: Dutch sanctions compliance

---

## Section 6: Additional Document Triggers — When and What to Request

When the income verification agent determines that the provided documents are insufficient, it specifies exactly which additional documents are needed and why. The orchestrator includes this in its decision, and the system shows it to both the user and the analyst.

| Trigger Condition | What to Request | Regulatory Basis |
|-------------------|-----------------|------------------|
| Income document is INSUFFICIENT (can't determine source of funds) | Specific document based on detected income type: loonstrook for employment, KvK-uittreksel for business, belastingaangifte for mixed income | Wwft Art. 3(2)(d): institutions must establish the source of funds used in the business relationship |
| Income document is UNREADABLE (poor scan quality, wrong format, corrupted file) | Re-upload of the same document in better quality (clear scan, legible text, correct orientation) | CDD completeness — verification is impossible if the document cannot be read |
| Income plausibility concern (declared income doesn't match employment type or level) | Tax return (belastingaangifte) or additional bank statements covering a longer period | DNB guideline: institutions must verify the "economic rationale" of the business relationship |
| Self-employed with no business registration proof | KvK-uittreksel (Chamber of Commerce extract) | All businesses in NL must register with KVK. Absence of registration for claimed self-employment is a significant red flag |
| High income (>EUR 10,000/month) without clear employment basis | Additional proof: employer reference letter (werkgeversverklaring), tax return, or accountant's statement | EDD trigger under DNB guidelines — high income without clear source requires enhanced verification |
| Multiple income sources detected in documents | Separate documentation for each income source | Wwft: all material income sources must be independently verified |
| Bank statement shows large cash deposits (>EUR 15,000) | Explanation and documentation of cash source | Wwft Art. 16: cash transactions above EUR 15,000 must be reported to FIU-Nederland |

### The Additional Documents Flow

1. Income Verification Agent analyzes the document and determines it's insufficient
2. Agent specifies exactly which documents are needed, with a reason for each
3. Orchestrator includes this in its ADDITIONAL_DOCUMENTS_REQUIRED decision
4. System updates case status to ADDITIONAL_DOCUMENTS_REQUESTED
5. User sees the specific document requests in the UI with clear explanations
6. User uploads the requested documents
7. Analyst reviews the new documents and triggers re-processing
8. The full pipeline runs again with the updated document set

---

## Section 7: Dutch Terminology Reference

All mock APIs use Dutch field names to match real Dutch government and institutional APIs. This table provides translations:

### Identity and Personal Data

| Dutch Term | English Translation | Where Used | Notes |
|------------|-------------------|------------|-------|
| burgerservicenummer (BSN) | Citizen Service Number (Social Security Number) | BRP, UWV | 9-digit number, universal Dutch identifier for government services |
| naam | Name | BRP, KVK | |
| voornamen | First names | BRP | May include multiple given names |
| geslachtsnaam | Family name | BRP | Surname/last name |
| voorvoegsel | Name prefix | BRP | Dutch name prefixes like "van", "de", "van den" |
| volledigeNaam | Full name | BRP | Complete registered name |
| geboorte | Birth | BRP | Object containing datum, plaats, land |
| geslacht | Gender | BRP | M/V/O (Male/Female/Other) |
| nationaliteiten | Nationalities | BRP | Array — a person may hold multiple |

### Employment and Income

| Dutch Term | English Translation | Where Used | Notes |
|------------|-------------------|------------|-------|
| dienstverband | Employment relationship | UWV | One record per employer |
| werkgever | Employer | UWV, loonstrook | |
| werknemer | Employee | Loonstrook | |
| brutoloon | Gross salary | UWV, loonstrook | Before tax and deductions |
| nettoloon | Net salary | Loonstrook | After all deductions |
| svLoon | Social Insurance Wage | UWV | THE primary income metric in the Dutch system — basis for all social insurance calculations |
| vakantiegeld | Holiday allowance | UWV, loonstrook | Legally 8% of gross annual salary in NL |
| loonstrook | Payslip / salary slip | Income documents | Monthly payslip issued by employer |
| loonheffingennummer | Wage tax number | UWV | Unique per employer, used in all wage declarations |
| arbeidsovereenkomst | Employment contract | Income documents | vast = permanent, tijdelijk = temporary, oproep = on-call |
| loonaangifte | Wage declaration | UWV system | Monthly submission by employers to UWV |
| uitkering | Benefit payment | UWV | Government benefit (unemployment, disability, etc.) |
| bankafschrift | Bank statement | Income documents | |
| belastingaangifte | Tax return | Income documents | Annual submission to Belastingdienst |

### Business and Registration

| Dutch Term | English Translation | Where Used | Notes |
|------------|-------------------|------------|-------|
| KvK-uittreksel | Chamber of Commerce extract | KVK API | Business registration proof |
| kvkNummer | KVK Number | KVK API | 8-digit business registration number |
| vestigingsnummer | Branch/establishment number | KVK API | 12-digit, identifies a specific business location |
| handelsnamen | Trade names | KVK API | Names under which business operates |
| sbiActiviteiten | SBI Activity codes | KVK API | Standaard Bedrijfsindeling — Dutch business classification (equivalent to EU NACE) |
| sbiOmschrijving | SBI Description | KVK API | Human-readable description of the business activity |
| rechtsvorm | Legal form | KVK API | BeslotenVennootschap (BV), NaamlozeVennootschap (NV), Eenmanszaak, etc. |
| statutaireNaam | Statutory name | KVK API | Legal name as registered in articles of association |
| formeleRegistratiedatum | Formal registration date | KVK API | When the business was registered |
| hoofdvestiging | Main establishment | KVK API | Primary business location |
| totaalWerkzamePersonen | Total working persons | KVK API | Number of employees at the establishment |
| Handelsregister | Trade Register | KVK system | The actual registry maintained by KVK |

### Regulatory and Legal

| Dutch Term | English Translation | Where Used | Notes |
|------------|-------------------|------------|-------|
| Wwft | Anti-Money Laundering Act | Regulatory framework | Wet ter voorkoming van witwassen en financieren van terrorisme |
| DNB | De Nederlandsche Bank | Supervisor | Dutch central bank — supervises banks for Wwft compliance |
| Belastingdienst | Tax Authority | Tax returns | Dutch IRS equivalent |
| zzp | Self-employed (without employees) | Income category | Zelfstandige Zonder Personeel |
| Sanctiewet | Sanctions Act | Regulatory | Dutch implementation of EU/UN sanctions |
| FIU-Nederland | Financial Intelligence Unit | Reporting | Receives unusual transaction reports under Wwft |
| Rijksoverheid | Central government | General | Netherlands national government |

---

## Document Version History

| Date | Change |
|------|--------|
| 2026-04-01 | Initial version — created as part of income verification feature implementation |
| 2026-04-01 | Updated Section 5: replaced LLM-guessed risk scores with deterministic weighted scoring formula; added scoring table, breakdown, and test case score examples |
