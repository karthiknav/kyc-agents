/**
 * Dynamic router — reads JSON mock definitions from the mocks/ directory
 * and registers Express routes for each one.
 */

import { Router, Request, Response } from 'express';
import fs from 'fs';
import path from 'path';
import { globSync } from 'glob';
import { generateResponse, type MockDefinition } from '../middleware/faker-generator';
import { ensureTable } from '../middleware/persistence';

const MOCKS_DIR = path.join(__dirname, '../../mocks');

/**
 * Load all mock definitions from the mocks/ directory.
 */
export function loadMockDefinitions(): MockDefinition[] {
  const files = globSync('*.json', { cwd: MOCKS_DIR });
  const definitions: MockDefinition[] = [];

  for (const file of files) {
    const filePath = path.join(MOCKS_DIR, file);
    const content = fs.readFileSync(filePath, 'utf-8');
    try {
      const mock = JSON.parse(content) as MockDefinition;
      definitions.push(mock);
      console.log(`  Loaded mock: ${mock.name} [${mock.method} ${mock.path}]`);
    } catch (err) {
      console.error(`  Failed to parse mock definition ${file}:`, err);
    }
  }

  return definitions;
}

/**
 * Create a router with all mock endpoints registered.
 */
export function createDynamicRouter(): { router: Router; mocks: MockDefinition[] } {
  const router = Router();
  const mocks = loadMockDefinitions();

  for (const mock of mocks) {
    // Ensure persistence table exists
    ensureTable(mock.id);

    const method = mock.method.toLowerCase() as 'get' | 'post' | 'put' | 'delete' | 'patch';

    router[method](mock.path, (req: Request, res: Response) => {
      const requestBody = req.body || {};

      // Validate required fields
      if (mock.request?.body) {
        const errors: string[] = [];
        for (const [field, spec] of Object.entries(mock.request.body)) {
          if (spec.required && (requestBody[field] === undefined || requestBody[field] === null || requestBody[field] === '')) {
            errors.push(`Missing required field: ${field}`);
          }
          if (spec.enum && requestBody[field] && !spec.enum.includes(requestBody[field])) {
            errors.push(`Invalid value for ${field}: must be one of ${spec.enum.join(', ')}`);
          }
        }
        if (errors.length > 0) {
          res.status(400).json({ errors });
          return;
        }
      }

      const { status, data } = generateResponse(mock, requestBody);
      res.status(status).json(data);
    });
  }

  return { router, mocks };
}
