/**
 * SQLite persistence layer for mock responses.
 * Ensures the same request key always returns the same generated data.
 */

import Database from 'better-sqlite3';
import path from 'path';
import fs from 'fs';

// Allow override for AWS (e.g. Elastic Beanstalk mounted volume at /var/app/data)
const DATA_DIR = process.env.MOCK_DATA_DIR || path.join(__dirname, '../../data');
const DB_PATH = path.join(DATA_DIR, 'mock-data.db');

let db: Database.Database | null = null;

function getDb(): Database.Database {
  if (!db) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    db = new Database(DB_PATH);
    db.pragma('journal_mode = WAL');
  }
  return db;
}

/**
 * Sanitize a mock ID into a valid SQLite table name.
 */
function tableName(mockId: string): string {
  return 'mock_' + mockId.replace(/[^a-zA-Z0-9]/g, '_');
}

/**
 * Ensure the table for a mock definition exists.
 */
export function ensureTable(mockId: string): void {
  const name = tableName(mockId);
  getDb().exec(`
    CREATE TABLE IF NOT EXISTS ${name} (
      persistence_key TEXT PRIMARY KEY,
      response_data TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
  `);
}

/**
 * Look up a persisted response by key. Returns the parsed response data or null.
 */
export function getPersistedResponse(mockId: string, key: string): unknown | null {
  const name = tableName(mockId);
  const row = getDb().prepare(`SELECT response_data FROM ${name} WHERE persistence_key = ?`).get(key) as
    | { response_data: string }
    | undefined;

  if (row) {
    return JSON.parse(row.response_data);
  }
  return null;
}

/**
 * Persist a generated response so future calls with the same key return the same data.
 */
export function persistResponse(mockId: string, key: string, data: unknown): void {
  const name = tableName(mockId);
  getDb()
    .prepare(`INSERT OR REPLACE INTO ${name} (persistence_key, response_data, created_at) VALUES (?, ?, ?)`)
    .run(key, JSON.stringify(data), new Date().toISOString());
}

/**
 * Get all persisted records for a mock definition.
 */
export function getAllRecords(mockId: string): Array<{ persistence_key: string; response_data: unknown; created_at: string }> {
  const name = tableName(mockId);
  ensureTable(mockId);
  const rows = getDb().prepare(`SELECT * FROM ${name} ORDER BY created_at DESC`).all() as Array<{
    persistence_key: string;
    response_data: string;
    created_at: string;
  }>;
  return rows.map(r => ({
    ...r,
    response_data: JSON.parse(r.response_data),
  }));
}

/**
 * Delete a specific persisted record.
 */
export function deleteRecord(mockId: string, key: string): boolean {
  const name = tableName(mockId);
  ensureTable(mockId);
  const result = getDb().prepare(`DELETE FROM ${name} WHERE persistence_key = ?`).run(key);
  return result.changes > 0;
}

/**
 * Manually seed a record (used by admin endpoint and seed scripts).
 */
export function seedRecord(mockId: string, key: string, data: unknown): void {
  ensureTable(mockId);
  persistResponse(mockId, key, data);
}
