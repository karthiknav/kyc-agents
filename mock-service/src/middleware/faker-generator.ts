/**
 * Faker generator middleware.
 * Generates a full response from a mock schema, resolving all {{faker.*}} expressions.
 * If a persistence key is configured, returns cached data for repeat requests.
 */

import { resolveSchema, resolvePersistenceKey, type TemplateContext } from '../utils/template';
import { ensureTable, getPersistedResponse, persistResponse } from './persistence';

export interface MockDefinition {
  id: string;
  name: string;
  description: string;
  method: string;
  path: string;
  request?: {
    body?: Record<string, any>;
  };
  response: {
    status: number;
    persistenceKey?: string;
    schema: unknown;
  };
}

/**
 * Generate (or retrieve from cache) a response for an incoming request.
 */
export function generateResponse(
  mock: MockDefinition,
  requestBody: Record<string, any>
): { status: number; data: unknown } {
  const context: TemplateContext = { requestBody };

  // If persistence is configured, check cache first
  if (mock.response.persistenceKey) {
    const key = resolvePersistenceKey(mock.response.persistenceKey, requestBody);
    ensureTable(mock.id);

    const cached = getPersistedResponse(mock.id, key);
    if (cached) {
      return { status: mock.response.status, data: cached };
    }

    // Generate new response and persist
    const data = resolveSchema(mock.response.schema, context);
    persistResponse(mock.id, key, data);
    return { status: mock.response.status, data };
  }

  // No persistence — generate fresh each time
  const data = resolveSchema(mock.response.schema, context);
  return { status: mock.response.status, data };
}
