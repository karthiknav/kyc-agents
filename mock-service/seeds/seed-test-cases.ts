/**
 * Seed script — pre-populates the mock service with deterministic test data
 * for BRP (4 scenarios) and PEP (4 scenarios): clean, document mismatch, sanctions, PEP.
 *
 * Use this when the mock service is already running and you want to (re)seed via HTTP
 * (e.g. from another machine or after the server was started with SEED_DEFAULT_TEST_CASES=0).
 *
 * By default the server seeds these same cases on startup; this script is for on-demand reseed.
 *
 * Usage:
 *   npm run seed
 *     → seeds http://localhost:${MOCK_SERVICE_PORT || 9000}
 *   MOCK_SERVICE_URL=https://my-app.elasticbeanstalk.com npm run seed
 *     → seeds the given base URL (e.g. Elastic Beanstalk)
 *
 * Env:
 *   MOCK_SERVICE_URL - Base URL of the mock service (no trailing slash). Overrides localhost.
 *   MOCK_SERVICE_PORT - Used only when MOCK_SERVICE_URL is not set (default 9000).
 */

import { defaultTestCases, BRP_MOCK_ID, pepTestCases, PEP_MOCK_ID } from '../src/data/default-test-cases';
const MOCK_SERVICE_URL = 'http://mock-service-env.eba-zfipxyvv.us-east-1.elasticbeanstalk.com/';
const BASE_URL =
   MOCK_SERVICE_URL?.replace(/\/$/, '') ||
  `http://localhost:${process.env.MOCK_SERVICE_PORT || '9000'}`;

async function seedMock(mockId: string, cases: Array<{ key: string; data: Record<string, unknown>; description: string }>) {
  for (const tc of cases) {
    console.log(`  Seeding: ${tc.description}`);
    console.log(`    Key: ${tc.key}`);

    const response = await fetch(`${BASE_URL}/admin/data/${mockId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key: tc.key, data: tc.data }),
    });

    if (!response.ok) {
      const text = await response.text();
      console.error(`    FAILED (${response.status}): ${text}`);
    } else {
      const result = await response.json();
      console.log(`    OK:`, result);
    }
  }
}

async function seed() {
  console.log(`Seeding mock service at ${BASE_URL}...\n`);

  console.log(`BRP (${BRP_MOCK_ID}):`);
  await seedMock(BRP_MOCK_ID, defaultTestCases);

  console.log(`\nPEP (${PEP_MOCK_ID}):`);
  await seedMock(PEP_MOCK_ID, pepTestCases);

  console.log('\nDone. Seeded', defaultTestCases.length, 'BRP +', pepTestCases.length, 'PEP test case(s).');
}

seed().catch(err => {
  console.error('Seed failed:', err);
  process.exit(1);
});
