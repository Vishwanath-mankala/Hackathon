/**
 * Generates src/environments/environment.generated.ts from the repo-root .env.
 *
 * The browser cannot read a .env file, so the one place configuration lives has
 * to be projected into the bundle at build time. This runs from `prestart` and
 * `prebuild`, which means the API URL the app talks to and the one the backend
 * serves come from the same file — there is no second source to drift from.
 *
 * The generated file is git-ignored: it is a build artefact, not config.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, '..', '..');
const ENV_FILE = resolve(REPO_ROOT, '.env');
const OUT_FILE = resolve(HERE, '..', 'src', 'environments', 'environment.generated.ts');

const DEFAULT_API_BASE_URL = 'http://localhost:8000';

/** Minimal KEY=VALUE parser — enough for the flat file this project uses. */
function parseEnv(text) {
  const out = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;

    const eq = line.indexOf('=');
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();

    // Strip one layer of matching quotes if present.
    if (value.length >= 2 && value[0] === value.at(-1) && (value[0] === '"' || value[0] === "'")) {
      value = value.slice(1, -1);
    }
    if (key) out[key] = value;
  }
  return out;
}

let env = {};
if (existsSync(ENV_FILE)) {
  env = parseEnv(readFileSync(ENV_FILE, 'utf8'));
} else {
  console.warn(`[generate-env] No .env at ${ENV_FILE} — falling back to defaults.`);
}

// An explicit API_BASE_URL wins. Otherwise derive it from the HOST/PORT the
// backend is configured to bind, since that is what it will actually serve on.
// 0.0.0.0 is a bind address, not something a browser can connect to.
let apiBaseUrl = env.API_BASE_URL?.trim();
if (!apiBaseUrl) {
  const host = env.HOST?.trim();
  const port = env.PORT?.trim();
  const reachableHost = !host || host === '0.0.0.0' || host === '::' ? 'localhost' : host;
  apiBaseUrl = port ? `http://${reachableHost}:${port}` : DEFAULT_API_BASE_URL;
}
apiBaseUrl = apiBaseUrl.replace(/\/+$/, '');

const contents = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Written by frontend/scripts/generate-env.mjs from the repo-root .env on every
 * \`npm start\` / \`npm run build\`. Change .env, not this file.
 */
export const environment = {
  apiBaseUrl: '${apiBaseUrl}',
} as const;
`;

mkdirSync(dirname(OUT_FILE), { recursive: true });
writeFileSync(OUT_FILE, contents, 'utf8');
console.log(`[generate-env] apiBaseUrl = ${apiBaseUrl}`);
