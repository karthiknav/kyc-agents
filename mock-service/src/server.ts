/**
 * Mock Service — Express entrypoint.
 * Loads mock definitions from mocks/ directory and exposes admin routes.
 */

import express from 'express';
import { createDynamicRouter } from './routes/dynamic-router';
import { getAllRecords, deleteRecord, seedRecord } from './middleware/persistence';

const PORT = parseInt(process.env.MOCK_SERVICE_PORT || '9000', 10);

const app = express();
app.use(express.json());

// Load and register all mock endpoints
console.log('Loading mock definitions...');
const { router, mocks } = createDynamicRouter();
app.use(router);

// ------------------------------------------------------------------
// Admin / Utility Endpoints
// ------------------------------------------------------------------

/** List all registered mock endpoints */
app.get('/admin/mocks', (_req, res) => {
  res.json(
    mocks.map(m => ({
      id: m.id,
      name: m.name,
      description: m.description,
      method: m.method,
      path: m.path,
    }))
  );
});

/** List all persisted records for a mock */
app.get('/admin/data/:mockId', (req, res) => {
  const { mockId } = req.params;
  const mock = mocks.find(m => m.id === mockId);
  if (!mock) {
    res.status(404).json({ error: `Mock '${mockId}' not found` });
    return;
  }
  const records = getAllRecords(mockId);
  res.json({ mockId, count: records.length, records });
});

/** Delete a specific persisted record */
app.delete('/admin/data/:mockId/:key', (req, res) => {
  const { mockId, key } = req.params;
  const deleted = deleteRecord(mockId, key);
  if (deleted) {
    res.json({ deleted: true, mockId, key });
  } else {
    res.status(404).json({ error: `Record '${key}' not found in mock '${mockId}'` });
  }
});

/** Manually seed a record (for test cases) */
app.post('/admin/data/:mockId', (req, res) => {
  const { mockId } = req.params;
  const { key, data } = req.body;
  if (!key || !data) {
    res.status(400).json({ error: 'Request body must include "key" and "data"' });
    return;
  }
  seedRecord(mockId, key, data);
  res.status(201).json({ seeded: true, mockId, key });
});

// ------------------------------------------------------------------
// Start
// ------------------------------------------------------------------

app.listen(PORT, () => {
  console.log(`\nMock service running on http://localhost:${PORT}`);
  console.log(`Admin: GET http://localhost:${PORT}/admin/mocks`);
  console.log(`Registered ${mocks.length} mock endpoint(s)\n`);
});
