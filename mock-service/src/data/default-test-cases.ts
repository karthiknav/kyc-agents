/**
 * Default test cases for mocks — shared by server (startup seed) and seed script (HTTP seed).
 */

export const BRP_MOCK_ID = 'brp-identity-verification';
export const PEP_MOCK_ID = 'pep-match';
export const TEXTRACT_MOCK_ID = 'textract-extract';

export interface DefaultTestCase {
  key: string;
  data: Record<string, unknown>;
  description: string;
}

export const defaultTestCases: DefaultTestCase[] = [
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
  {
    key: 'paspoort_123456789',
    description: 'Case 1: Clean Approval — Jan de Vries, all fields match (no NL prefix)',
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
        nummer: '123456789',
        datumUitgifte: '2020-01-10',
        datumEindeGeldigheid: '2030-01-10',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
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
  {
    key: 'paspoort_987654321',
    description: 'Case 2: Document Mismatch — passport registered to Maria Bakker, not Maria Jansen (no NL prefix)',
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
        nummer: '987654321',
        datumUitgifte: '2019-06-01',
        datumEindeGeldigheid: '2029-06-01',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
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
  {
    key: 'paspoort_555666777',
    description: 'Case 3: Sanctions Flag — Ahmed Al-Rashid, doc verification passes (no NL prefix)',
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
        nummer: '555666777',
        datumUitgifte: '2021-03-20',
        datumEindeGeldigheid: '2031-03-20',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
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
  {
    key: 'paspoort_111222333',
    description: 'Case 4: PEP Flag — Willem van den Berg, former government official (no NL prefix)',
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
        nummer: '111222333',
        datumUitgifte: '2022-09-15',
        datumEindeGeldigheid: '2032-09-15',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },

  // ----------------------------------------------------------------
  // Rijbewijs cases (driving license) — same scenarios, different documentType
  // Keys match persistenceKey: {{documentType}}_{{documentNumber}}
  // ----------------------------------------------------------------
  {
    key: 'rijbewijs_NL123456789',
    description: 'Case 1 (Rijbewijs): Clean Approval — Jan de Vries, all fields match',
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
        soort: 'rijbewijs',
        nummer: 'NL123456789',
        datumUitgifte: '2020-01-10',
        datumEindeGeldigheid: '2030-01-10',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
  {
    key: 'rijbewijs_123456789',
    description: 'Case 1 (Rijbewijs): Clean Approval — Jan de Vries, all fields match (no NL prefix)',
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
        soort: 'rijbewijs',
        nummer: '123456789',
        datumUitgifte: '2020-01-10',
        datumEindeGeldigheid: '2030-01-10',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
  {
    key: 'rijbewijs_NL987654321',
    description: 'Case 2 (Rijbewijs): Document Mismatch — driving license registered to Maria Bakker, not Maria Jansen',
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
        soort: 'rijbewijs',
        nummer: 'NL987654321',
        datumUitgifte: '2019-06-01',
        datumEindeGeldigheid: '2029-06-01',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
  {
    key: 'rijbewijs_987654321',
    description: 'Case 2 (Rijbewijs): Document Mismatch — driving license registered to Maria Bakker, not Maria Jansen (no NL prefix)',
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
        soort: 'rijbewijs',
        nummer: '987654321',
        datumUitgifte: '2019-06-01',
        datumEindeGeldigheid: '2029-06-01',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
  {
    key: 'rijbewijs_NL555666777',
    description: 'Case 3 (Rijbewijs): Sanctions Flag — Ahmed Al-Rashid, doc verification passes',
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
        soort: 'rijbewijs',
        nummer: 'NL555666777',
        datumUitgifte: '2021-03-20',
        datumEindeGeldigheid: '2031-03-20',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
  {
    key: 'rijbewijs_555666777',
    description: 'Case 3 (Rijbewijs): Sanctions Flag — Ahmed Al-Rashid, doc verification passes (no NL prefix)',
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
        soort: 'rijbewijs',
        nummer: '555666777',
        datumUitgifte: '2021-03-20',
        datumEindeGeldigheid: '2031-03-20',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
  {
    key: 'rijbewijs_NL111222333',
    description: 'Case 4 (Rijbewijs): PEP Flag — Willem van den Berg, former government official',
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
        soort: 'rijbewijs',
        nummer: 'NL111222333',
        datumUitgifte: '2022-09-15',
        datumEindeGeldigheid: '2032-09-15',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
  {
    key: 'rijbewijs_111222333',
    description: 'Case 4 (Rijbewijs): PEP Flag — Willem van den Berg, former government official (no NL prefix)',
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
        soort: 'rijbewijs',
        nummer: '111222333',
        datumUitgifte: '2022-09-15',
        datumEindeGeldigheid: '2032-09-15',
      },
      status: 'VERIFIED',
      verificationTimestamp: '2025-01-15T10:00:00.000Z',
    },
  },
];

// Textract mock test cases — keys match persistenceKey: {{full_name}} (the person's full name from identity.fullName)
// These are returned when USE_TEXTRACT_MOCK=1 and real Textract times out.
// OCR data matches the identity fields in the BRP test cases above so comparisons resolve correctly.
export interface TextractTestCase {
  key: string;       // full name, e.g. "Jan de Vries"
  data: Record<string, unknown>;
  description: string;
}

function makeOcrData(lines: string[]): Record<string, unknown> {
  return {
    document_type: '',
    s3_key: 'seeded',
    mock: true,
    pages: [{ page: 1, lines }],
    full_text: lines.join('\n'),
    block_count: lines.length,
  };
}

export const textractTestCases: TextractTestCase[] = [
  {
    key: 'Jan de Vries',
    description: 'Case 1: Jan de Vries — identity document OCR (paspoort / rijbewijs)',
    data: makeOcrData([
      'NEDERLAND',
      'PASPOORT / PASSPORT',
      'Naam / Surname: DE VRIES',
      'Voornamen / Given names: JAN',
      'Nationaliteit / Nationality: NEDERLANDSE',
      'Geboorteplaats / Place of birth: AMSTERDAM',
      'Geboortedatum / Date of birth: 15 MRT 1985',
      'Documentnummer / Document number: NL123456789',
      'Geslacht / Sex: M',
      'Geldig tot / Date of expiry: 10 JAN 2030',
      'Afgegeven te / Place of issue: AMSTERDAM',
    ]),
  },
  {
    key: 'Maria Bakker',
    description: 'Case 2: Maria Bakker — identity document OCR (paspoort / rijbewijs)',
    data: makeOcrData([
      'NEDERLAND',
      'PASPOORT / PASSPORT',
      'Naam / Surname: BAKKER',
      'Voornamen / Given names: MARIA',
      'Nationaliteit / Nationality: NEDERLANDSE',
      'Geboorteplaats / Place of birth: ROTTERDAM',
      'Geboortedatum / Date of birth: 22 JUL 1990',
      'Documentnummer / Document number: NL987654321',
      'Geslacht / Sex: V',
      'Geldig tot / Date of expiry: 01 JUN 2029',
      'Afgegeven te / Place of issue: ROTTERDAM',
    ]),
  },
  {
    key: 'Ahmed Al-Rashid',
    description: 'Case 3: Ahmed Al-Rashid — identity document OCR (paspoort / rijbewijs)',
    data: makeOcrData([
      'NEDERLAND',
      'PASPOORT / PASSPORT',
      'Naam / Surname: AL-RASHID',
      'Voornamen / Given names: AHMED',
      'Nationaliteit / Nationality: NEDERLANDSE',
      'Geboorteplaats / Place of birth: DEN HAAG',
      'Geboortedatum / Date of birth: 03 NOV 1978',
      'Documentnummer / Document number: NL555666777',
      'Geslacht / Sex: M',
      'Geldig tot / Date of expiry: 20 MRT 2031',
      'Afgegeven te / Place of issue: DEN HAAG',
    ]),
  },
  {
    key: 'Willem van den Berg',
    description: 'Case 4: Willem van den Berg — identity document OCR (paspoort / rijbewijs)',
    data: makeOcrData([
      'NEDERLAND',
      'PASPOORT / PASSPORT',
      'Naam / Surname: VAN DEN BERG',
      'Voornamen / Given names: WILLEM',
      'Nationaliteit / Nationality: NEDERLANDSE',
      'Geboorteplaats / Place of birth: UTRECHT',
      'Geboortedatum / Date of birth: 20 JAN 1970',
      'Documentnummer / Document number: NL111222333',
      'Geslacht / Sex: M',
      'Geldig tot / Date of expiry: 15 SEP 2032',
      'Afgegeven te / Place of issue: UTRECHT',
    ]),
  },
];

// PEP match test cases — keys match persistenceKey: {{queries.q1.properties.lastName.0}}_{{queries.q1.properties.firstName.0}}
export interface PepTestCase {
  key: string;
  data: Record<string, unknown>;
  description: string;
}

export const pepTestCases: PepTestCase[] = [
  {
    key: 'de Vries_Jan',
    description: 'PEP Case 1: Clean — Jan de Vries, no PEP/sanctions match',
    data: {
      responses: {
        q1: {
          query: {
            schema: 'Person',
            properties: {
              firstName: ['Jan'],
              lastName: ['de Vries'],
              birthDate: ['1985'],
              nationality: ['Netherlands'],
            },
          },
          results: [],
        },
      },
    },
  },
  {
    key: 'Bakker_Maria',
    description: 'PEP Case 2: Clean — Maria Bakker, no match',
    data: {
      responses: {
        q1: {
          query: {
            schema: 'Person',
            properties: {
              firstName: ['Maria'],
              lastName: ['Bakker'],
              birthDate: ['1990'],
              nationality: ['Netherlands'],
            },
          },
          results: [],
        },
      },
    },
  },
  {
    key: 'Al-Rashid_Ahmed',
    description: 'PEP Case 3: Sanctions hit — Ahmed Al-Rashid',
    data: {
      responses: {
        q1: {
          query: {
            schema: 'Person',
            properties: {
              firstName: ['Ahmed'],
              lastName: ['Al-Rashid'],
              birthDate: ['1978'],
              nationality: ['Netherlands'],
            },
          },
          results: [
            {
              id: 'NK-sanctions-ahmed-001',
              schema: 'Person',
              caption: 'Ahmed Al-Rashid',
              datasets: ['sanctions'],
              referents: ['ofac-12345'],
              first_seen: '2020-06-01T00:00:00.000Z',
              last_change: '2025-01-15T10:00:00.000Z',
              properties: {
                name: ['Ahmed Al-Rashid'],
                firstName: ['Ahmed'],
                lastName: ['Al-Rashid'],
                birthDate: ['1978'],
                nationality: ['sy'],
                position: ['Designated under sanctions program'],
              },
            },
          ],
        },
      },
    },
  },
  {
    key: 'Berg_Willem',
    description: 'PEP Case 4: PEP hit — Willem van den Berg, former government official',
    data: {
      responses: {
        q1: {
          query: {
            schema: 'Person',
            properties: {
              firstName: ['Willem'],
              lastName: ['Berg'],
              birthDate: ['1970'],
              nationality: ['Netherlands'],
            },
          },
          results: [
            {
              id: 'NK-pep-willem-001',
              schema: 'Person',
              caption: 'Willem van den Berg',
              datasets: ['pep_world'],
              referents: ['pep-nl-789012'],
              first_seen: '2019-03-10T00:00:00.000Z',
              last_change: '2025-01-15T10:00:00.000Z',
              properties: {
                name: ['Willem van den Berg'],
                firstName: ['Willem'],
                lastName: ['Berg', 'van den Berg'],
                birthDate: ['1970'],
                nationality: ['nl'],
                position: ['Former Minister', 'Government Official'],
              },
            },
          ],
        },
      },
    },
  },
];
