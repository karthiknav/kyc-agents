/**
 * Seed script — pre-populates the mock service with deterministic test data
 * for 4 KYC scenarios: clean approval, document mismatch, sanctions flag, PEP flag.
 *
 * Use this when the mock service is already running and you want to (re)seed via HTTP
 * (e.g. from another machine or after the server was started with SEED_DEFAULT_TEST_CASES=0).
 *
 * By default the server seeds these same cases on startup; this script is for on-demand reseed.
 *
 * Usage: npm run seed  (or: npx tsx seeds/seed-test-cases.ts)
 * Requires the mock service to be running on MOCK_SERVICE_PORT (default 9000).
 */

import { defaultTestCases, BRP_MOCK_ID } from '../src/data/default-test-cases';

const BASE_URL = `http://localhost:${process.env.MOCK_SERVICE_PORT || '9000'}`;

async function seed() {
  console.log(`Seeding mock service at ${BASE_URL}...\n`);

  for (const tc of defaultTestCases) {
    console.log(`  Seeding: ${tc.description}`);
    console.log(`    Key: ${tc.key}`);

    const response = await fetch(`${BASE_URL}/admin/data/${BRP_MOCK_ID}`, {
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

  console.log('\nDone. Seeded', defaultTestCases.length, 'test case(s).');
}

seed().catch(err => {
  console.error('Seed failed:', err);
  process.exit(1);
});
