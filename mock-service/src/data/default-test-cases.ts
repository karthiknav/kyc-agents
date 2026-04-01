/**
 * Default test cases for mocks — shared by server (startup seed) and seed script (HTTP seed).
 */

export const BRP_MOCK_ID = 'brp-identity-verification';
export const PEP_MOCK_ID = 'pep-match';
export const UWV_MOCK_ID = 'uwv-polisadministratie';
export const KVK_MOCK_ID = 'kvk-basisprofiel';

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

// UWV Polisadministratie test cases — keys match persistenceKey: {{burgerservicenummer}}
export const uwvTestCases: DefaultTestCase[] = [
  {
    key: '123456789',
    description: 'UWV Case 1: Clean — Jan de Vries, employed at Tech Solutions BV, EUR 48K/yr',
    data: {
      burgerservicenummer: '123456789',
      dienstverbanden: [
        {
          werkgever: {
            naam: 'Tech Solutions BV',
            kvkNummer: '12345678',
            loonheffingennummer: 'L1234567890',
          },
          dienstverband: {
            soort: 'vast',
            startdatum: '2020-01-15',
            einddatum: null,
            beroep: 'Software Engineer',
            arbeidsuren: 40,
          },
          inkomen: {
            svLoon: 48000,
            brutoloonPeriode: 4000,
            loonperiode: 'maand',
            vakantiegeld: 3840,
            bijzondereBeloningen: 0,
          },
          periode: '2025',
        },
      ],
      uitkeringen: [],
      status: 'GEVONDEN',
      peildatum: '2026-03-15T10:00:00.000Z',
    },
  },
  {
    key: '987654321',
    description: 'UWV Case 2: No records — Maria Bakker, no employment found',
    data: {
      burgerservicenummer: '987654321',
      dienstverbanden: [],
      uitkeringen: [],
      status: 'NIET_GEVONDEN',
      peildatum: '2026-03-15T10:00:00.000Z',
    },
  },
  {
    key: '555666777',
    description: 'UWV Case 3: Suspicious — Ahmed Al-Rashid, EUR 250K temp contract',
    data: {
      burgerservicenummer: '555666777',
      dienstverbanden: [
        {
          werkgever: {
            naam: 'International Trading GmbH',
            kvkNummer: '',
            loonheffingennummer: '',
          },
          dienstverband: {
            soort: 'tijdelijk',
            startdatum: '2025-09-01',
            einddatum: '2026-08-31',
            beroep: 'Consultant',
            arbeidsuren: 40,
          },
          inkomen: {
            svLoon: 250000,
            brutoloonPeriode: 20833,
            loonperiode: 'maand',
            vakantiegeld: 20000,
            bijzondereBeloningen: 0,
          },
          periode: '2025',
        },
      ],
      uitkeringen: [],
      status: 'GEVONDEN',
      peildatum: '2026-03-15T10:00:00.000Z',
    },
  },
  {
    key: '111222333',
    description: 'UWV Case 4: PEP dual income — Willem van den Berg, government + zzp',
    data: {
      burgerservicenummer: '111222333',
      dienstverbanden: [
        {
          werkgever: {
            naam: 'Rijksoverheid',
            kvkNummer: '00000001',
            loonheffingennummer: 'L0000000001',
          },
          dienstverband: {
            soort: 'vast',
            startdatum: '2005-04-01',
            einddatum: null,
            beroep: 'Beleidsadviseur',
            arbeidsuren: 36,
          },
          inkomen: {
            svLoon: 95000,
            brutoloonPeriode: 7917,
            loonperiode: 'maand',
            vakantiegeld: 7600,
            bijzondereBeloningen: 2500,
          },
          periode: '2025',
        },
      ],
      uitkeringen: [],
      status: 'GEVONDEN',
      peildatum: '2026-03-15T10:00:00.000Z',
    },
  },
];

// KVK Basisprofiel test cases — keys match persistenceKey: {{kvkNummer}}
export const kvkTestCases: DefaultTestCase[] = [
  {
    key: '87654321',
    description: 'KVK Case 1: Van den Berg Advies BV — Willem van den Berg consulting firm',
    data: {
      kvkNummer: '87654321',
      naam: 'Van den Berg Advies BV',
      formeleRegistratiedatum: '2015-06-01',
      statutaireNaam: 'Van den Berg Advies B.V.',
      handelsnamen: [{ naam: 'Van den Berg Advies', volgorde: 1 }],
      sbiActiviteiten: [
        {
          sbiCode: '70221',
          sbiOmschrijving: 'Organisatieadviesbureaus',
          indHoofdactiviteit: 'Ja',
        },
      ],
      eigenaar: {
        rechtsvorm: 'BeslotenVennootschap',
        uitgebreideRechtsvorm: 'Besloten Vennootschap',
        rsin: '987654321',
      },
      hoofdvestiging: {
        vestigingsnummer: '123456789012',
        eersteHandelsnaam: 'Van den Berg Advies',
        totaalWerkzamePersonen: 3,
        adressen: [
          {
            type: 'bezoekadres',
            straatnaam: 'Herengracht',
            huisnummer: 100,
            postcode: '1015BS',
            plaats: 'Amsterdam',
          },
        ],
      },
      _links: {},
    },
  },
];
