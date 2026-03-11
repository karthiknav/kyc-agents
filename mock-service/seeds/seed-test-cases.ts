/**
 * Seed script — pre-populates the mock service with deterministic test data
 * for 4 KYC scenarios: clean approval, document mismatch, sanctions flag, PEP flag.
 *
 * Usage: npm run seed  (or: npx tsx seeds/seed-test-cases.ts)
 * Requires the mock service to be running on MOCK_SERVICE_PORT (default 9000).
 */

const BASE_URL = `http://localhost:${process.env.MOCK_SERVICE_PORT || '9000'}`;
const MOCK_ID = 'brp-identity-verification';

interface SeedRecord {
  key: string;
  data: Record<string, unknown>;
  description: string;
}

const testCases: SeedRecord[] = [
  // ----------------------------------------------------------------
  // Case 1: Clean Approval — all fields match, no sanctions/PEP
  // ----------------------------------------------------------------
  {
    key: 'paspoort_NL123456789',
    description: 'Case 1: Clean Approval — Jan de Vries, all fields match',
    data: {
      burgerservicenummer: '123456789',
      naam: {
        voornamen: 'Jan',
        voorvoegsel: 'de',
        geslachtsnaam: 'Vries',
        volledigeNaam: 'Jan de Vries',
      },
      geboorte: {
        datum: '1985-03-15',
        plaats: 'Amsterdam',
        land: 'Nederland',
      },
      geslacht: 'M',
      nationaliteiten: [{ nationaliteit: 'Nederlandse' }],
      document: {
        soort: 'paspoort',
        nummer: 'NL123456789',
        datumUitgifte: '2020-01-10',
        datumEindeGeldigheid: '2030-01-10',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },

  // ----------------------------------------------------------------
  // Case 2: Document Mismatch — BRP returns different name than expected
  // ----------------------------------------------------------------
  {
    key: 'paspoort_NL987654321',
    description: 'Case 2: Document Mismatch — passport registered to Maria Bakker, not Maria Jansen',
    data: {
      burgerservicenummer: '987654321',
      naam: {
        voornamen: 'Maria',
        voorvoegsel: '',
        geslachtsnaam: 'Bakker',
        volledigeNaam: 'Maria Bakker',
      },
      geboorte: {
        datum: '1990-07-22',
        plaats: 'Rotterdam',
        land: 'Nederland',
      },
      geslacht: 'V',
      nationaliteiten: [{ nationaliteit: 'Nederlandse' }],
      document: {
        soort: 'paspoort',
        nummer: 'NL987654321',
        datumUitgifte: '2019-06-01',
        datumEindeGeldigheid: '2029-06-01',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },

  // ----------------------------------------------------------------
  // Case 3: Sanctions Flag — document verification passes, but screening catches sanctions
  // ----------------------------------------------------------------
  {
    key: 'paspoort_NL555666777',
    description: 'Case 3: Sanctions Flag — Ahmed Al-Rashid, doc verification passes',
    data: {
      burgerservicenummer: '555666777',
      naam: {
        voornamen: 'Ahmed',
        voorvoegsel: '',
        geslachtsnaam: 'Al-Rashid',
        volledigeNaam: 'Ahmed Al-Rashid',
      },
      geboorte: {
        datum: '1978-11-03',
        plaats: 'Den Haag',
        land: 'Nederland',
      },
      geslacht: 'M',
      nationaliteiten: [{ nationaliteit: 'Nederlandse' }],
      document: {
        soort: 'paspoort',
        nummer: 'NL555666777',
        datumUitgifte: '2021-03-20',
        datumEindeGeldigheid: '2031-03-20',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },

  // ----------------------------------------------------------------
  // Case 4: PEP Flag — document verification passes, PEP screening needed
  // (Flagged for future work: dedicated PEP screening tool)
  // ----------------------------------------------------------------
  {
    key: 'paspoort_NL111222333',
    description: 'Case 4: PEP Flag — Willem van den Berg, former government official',
    data: {
      burgerservicenummer: '111222333',
      naam: {
        voornamen: 'Willem',
        voorvoegsel: 'van den',
        geslachtsnaam: 'Berg',
        volledigeNaam: 'Willem van den Berg',
      },
      geboorte: {
        datum: '1970-01-20',
        plaats: 'Utrecht',
        land: 'Nederland',
      },
      geslacht: 'M',
      nationaliteiten: [{ nationaliteit: 'Nederlandse' }],
      document: {
        soort: 'paspoort',
        nummer: 'NL111222333',
        datumUitgifte: '2022-09-15',
        datumEindeGeldigheid: '2032-09-15',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
];

async function seed() {
  console.log(`Seeding mock service at ${BASE_URL}...\n`);

  for (const tc of testCases) {
    console.log(`  Seeding: ${tc.description}`);
    console.log(`    Key: ${tc.key}`);

    const response = await fetch(`${BASE_URL}/admin/data/${MOCK_ID}`, {
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

  console.log('\nDone. Seeded', testCases.length, 'test case(s).');
}

seed().catch(err => {
  console.error('Seed failed:', err);
  process.exit(1);
});
