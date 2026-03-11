/**
 * Template interpolation engine.
 * Resolves expressions like {{request.fieldName}}, {{now}}, and {{faker.*}} in mock response schemas.
 */

import { faker } from '@faker-js/faker';

/**
 * Resolve a single template expression (the content between {{ and }}).
 */
function resolveExpression(expr: string, context: TemplateContext): unknown {
  const trimmed = expr.trim();

  // {{now}} — current ISO timestamp
  if (trimmed === 'now') {
    return new Date().toISOString();
  }

  // {{request.*}} — value from the incoming request body (supports nested paths, e.g. request.queries.q1)
  if (trimmed.startsWith('request.')) {
    const path = trimmed.slice('request.'.length);
    return getNested(context.requestBody, path) ?? '';
  }

  // {{faker.*}} — delegate to faker resolver
  if (trimmed.startsWith('faker.')) {
    return resolveFaker(trimmed);
  }

  // Unknown expression — return as-is
  return `{{${trimmed}}}`;
}

/**
 * Resolve a faker expression like "faker.person.firstName" or "faker.string.numeric(9)".
 */
function resolveFaker(expr: string): unknown {
  // Strip "faker." prefix
  const path = expr.slice('faker.'.length);

  // Check for function call syntax: e.g. "string.numeric(9)" or "helpers.arrayElement(['M','V','O'])"
  const funcCallMatch = path.match(/^(.+?)\((.+)\)$/);

  if (funcCallMatch) {
    const methodPath = funcCallMatch[1];
    const argsStr = funcCallMatch[2];

    const method = resolveNestedProperty(faker, methodPath);
    if (typeof method === 'function') {
      try {
        // Parse the argument — handle arrays, numbers, strings
        const arg = parseArgument(argsStr);
        return method.call(faker, arg);
      } catch {
        return `{{${expr}}}`;
      }
    }
  }

  // No parentheses — treat as property or zero-arg method
  const prop = resolveNestedProperty(faker, path);
  if (typeof prop === 'function') {
    return prop.call(faker);
  }
  if (prop !== undefined) {
    return prop;
  }

  return `{{${expr}}}`;
}

/**
 * Parse a function argument string. Handles:
 * - Numbers: 9, 3.14
 * - Strings: 'hello', "hello"
 * - Arrays: ['a','b','c']
 */
function parseArgument(argStr: string): unknown {
  const trimmed = argStr.trim();

  // Number
  if (/^\d+(\.\d+)?$/.test(trimmed)) {
    return Number(trimmed);
  }

  // JSON-like (arrays, objects) — normalize single quotes to double
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    const normalized = trimmed.replace(/'/g, '"');
    return JSON.parse(normalized);
  }

  // Quoted string
  if ((trimmed.startsWith("'") && trimmed.endsWith("'")) ||
      (trimmed.startsWith('"') && trimmed.endsWith('"'))) {
    return trimmed.slice(1, -1);
  }

  return trimmed;
}

/**
 * Get a nested property from an object by dotted path. E.g. getNested(body, "queries.q1").
 */
function getNested(obj: unknown, path: string): unknown {
  if (obj == null) return undefined;
  const parts = path.split('.');
  let current: unknown = obj;
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

/**
 * Resolve a dotted property path on an object. E.g. "person.firstName" on faker.
 */
function resolveNestedProperty(obj: any, path: string): unknown {
  const parts = path.split('.');
  let current = obj;
  for (const part of parts) {
    if (current == null) return undefined;
    current = current[part];
  }
  return current;
}

export interface TemplateContext {
  requestBody?: Record<string, any>;
}

/**
 * Recursively walk a schema object and resolve all {{...}} template expressions.
 * Returns a new object with all templates replaced by their resolved values.
 */
export function resolveSchema(schema: unknown, context: TemplateContext): unknown {
  if (typeof schema === 'string') {
    // Check if the entire string is a single template expression
    const fullMatch = schema.match(/^\{\{(.+?)\}\}$/);
    if (fullMatch) {
      return resolveExpression(fullMatch[1], context);
    }

    // Otherwise replace inline expressions (may be mixed with literal text)
    return schema.replace(/\{\{(.+?)\}\}/g, (_match, expr) => {
      const resolved = resolveExpression(expr, context);
      return String(resolved);
    });
  }

  if (Array.isArray(schema)) {
    return schema.map(item => resolveSchema(item, context));
  }

  if (schema !== null && typeof schema === 'object') {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(schema as Record<string, unknown>)) {
      result[key] = resolveSchema(value, context);
    }
    return result;
  }

  // Numbers, booleans, null — return as-is
  return schema;
}

/**
 * Resolve the persistence key template using request body values.
 * Supports nested paths, e.g. {{queries.q1.properties.lastName.0}}.
 */
export function resolvePersistenceKey(template: string, requestBody: Record<string, any>): string {
  return template.replace(/\{\{([^}]+)\}\}/g, (_match, path) => {
    const key = path.trim();
    const value = getNested(requestBody, key);
    return value !== undefined && value !== null ? String(value) : key;
  });
}
