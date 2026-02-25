export interface StarterPrompt {
  label: string;
  description: string;
  spec: string;
}

export const STARTER_PROMPTS: StarterPrompt[] = [
  {
    label: "Health check endpoint",
    description: "A simple API health endpoint with tests",
    spec: "Add a health check endpoint at GET /api/health that returns JSON with: server status (ok/error), database connection status (connected/disconnected), server uptime in seconds, and current timestamp. Include unit tests.",
  },
  {
    label: "Add logging middleware",
    description: "Structured request logging",
    spec: "Add request logging middleware that logs: HTTP method, path, status code, response time in ms, and request ID. Use structured JSON logging. Include tests.",
  },
  {
    label: "CRUD endpoint",
    description: "Full REST resource with validation",
    spec: "Create a complete CRUD API for a resource with: list (GET), create (POST), read (GET /:id), update (PUT /:id), delete (DELETE /:id). Include input validation, error handling, and tests.",
  },
  {
    label: "Auth middleware",
    description: "JWT authentication with tests",
    spec: "Add JWT authentication middleware that: validates Bearer tokens from the Authorization header, extracts user ID, rejects expired tokens with 401, and makes the user available to downstream handlers. Include tests.",
  },
];
