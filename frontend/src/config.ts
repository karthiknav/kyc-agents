// Use VITE_API_BASE_URL when testing local UI against deployed API (e.g. API Gateway).
// Example: create frontend/.env.local with:
//   VITE_API_BASE_URL=https://xckfj49ipe.execute-api.us-east-1.amazonaws.com/prod
// Or run: VITE_API_BASE_URL=https://... npm run dev
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
