# Plan: Mock Service + Government Identity Verification + Test Cases

## Overview

This plan adds government identity document verification to the KYC document processing agent using a mock Dutch BRP (Basisregistratie Personen) API.

## Components

1. **Mock Service** (`mock-service/`) — Reusable Express/TypeScript server with faker + SQLite persistence
2. **BRP Mock Endpoint** — `POST /api/v1/brp/personen/document-lookup` simulating Haal Centraal BRP Personen API
3. **Seed Data** — 4 deterministic test cases (clean approval, document mismatch, sanctions flag, PEP flag)
4. **VerifyIdentityDocumentTool** — New CrewAI tool calling the BRP API
5. **Updated CompareIdentityDocumentsTool** — Now compares 3 sources (DB, OCR, government registry)
6. **Updated Agent/Task Config** — Document processing agent includes BRP verification step

## Test Cases

| # | Person | Document | Scenario | Expected |
|---|--------|----------|----------|----------|
| 1 | Jan de Vries | NL123456789 | Clean — all match, no sanctions | APPROVED |
| 2 | Maria Jansen | NL987654321 | BRP returns "Maria Bakker" | ESCALATED (mismatch) |
| 3 | Ahmed Al-Rashid | NL555666777 | Doc matches, sanctions hit | ESCALATED (screening NOK) |
| 4 | Willem van den Berg | NL111222333 | Doc matches, PEP flag | ESCALATED (PEP) |

## Future Work

- Dedicated PEP/sanctions screening API (OpenSanctions `/match/default`) as separate tool for screening agent
