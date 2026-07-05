# KYC Agent — Logical Architecture

```mermaid
flowchart TB
    subgraph OBS["Observability"]
        direction LR
        CW([CloudWatch]) ~~~ LF([Langfuse Tracing]) ~~~ EVAL([Evaluation]) ~~~ AT([Audit Trail]) ~~~ MON([Monitoring])
    end

    subgraph MAIN[" "]
        direction LR

        subgraph LEFT[" "]
            direction TB
            subgraph BYO["BYO Resources"]
                DDB[(DynamoDB\n– KYC Records)]
                S3[(S3\n– Documents / Glacier)]
            end
            subgraph KNO["Knowledge"]
                PEP[Sanctions / PEP Lists API]
                AMD[Adverse Media Feeds]
            end
            subgraph INT["Integrations"]
                HITL[HITL Applications]
                SQS[SQS – Email Escalations]
            end
        end

        subgraph TOOLS["Tools"]
            direction TB
            TX[Textract – OCR]
            BRP[BRP API\nGovt Identity Registry]
            SRCH[DuckDuckGo\nWeb Search]
        end

        subgraph KYC["KYC Agent"]
            direction TB
            ORCH["Orchestrator Agent\nCrewAI Manager"]
            subgraph AGENTS[" "]
                direction LR
                A1(["DOC\nDocument\nProcessor Agent"])
                A2(["SANC\nRisk List\nScreening Agent"])
                A3(["MEDIA\nAdverse\nMedia Agent"])
            end
            A1 --> ORCH
            A2 --> ORCH
            A3 --> ORCH
            CREWLBL["— CrewAI Framework —"]
        end

        subgraph MODELS["Models"]
            direction TB
            BR["Amazon Bedrock\nFoundation Models"]
            CS["Claude Sonnet"]
            BR --> CS
        end

        LEFT --> TOOLS
        TOOLS --> KYC
        KYC --> MODELS
        KYC --> INT
    end

    subgraph SEC["Security & Compliance"]
        direction LR
        IAM([IAM]) ~~~ GDPR([GDPR]) ~~~ AML([AML]) ~~~ GOV([Governance]) ~~~ CT([CloudTrail])
    end

    OBS -.-> MAIN
    MAIN -.-> SEC
```

---

## Changes from Prior Architecture Slide

| Aspect | Slide (Previous) | Current Implementation |
|---|---|---|
| **Model** | Mistral 3 8B (default) + Sonnet 4.5 (fallback) | **Claude Sonnet** via AWS Bedrock (model ID from SSM Parameter Store) |
| **Agents** | Orchestrator + Document Processor + Sanction Agent | Orchestrator + Document Processing + **Risk List Screening** + **Adverse Media** |
| **Pipeline** | Fan-out implied | Sequential: Doc → Risk → Media → Orchestrator |
| **OCR Tool** | Textract + Rekognition (face) | **Textract only** (no face recognition) |
| **Adverse Media** | Not shown | DuckDuckGo search + LLM analysis |
| **Govt Verification** | Not shown | Dutch BRP API |
| **Observability** | CloudWatch | CloudWatch + **Langfuse** tracing |

---

## Agent Decision Matrix

| Document | Risk List | Adverse Media | Decision |
|---|---|---|---|
| MATCH | CLEAR | OK | **APPROVED** |
| anything else | anything | anything | **ESCALATED → PENDING_HUMAN_REVIEW** |

Escalation triggers an SQS notification to the human review queue.
