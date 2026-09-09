// Runs the application's compiled SQL against PostgreSQL WASM, not a SQL mock.
// This does not exercise psycopg connections or multi-session row locking.
import { PGlite } from "@electric-sql/pglite";

let input = "";
for await (const chunk of process.stdin) input += chunk;
const { setup, cases } = JSON.parse(input);
const db = new PGlite();
try {
  await db.exec(setup);
  const results = {};
  for (const { name, before, query, params } of cases) {
    if (before) await db.exec(before);
    // Python already applied psycopg's production placeholder conversion.
    results[name] = (await db.query(query, params)).rows;
  }
  process.stdout.write(JSON.stringify(results));
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
} finally {
  await db.close();
}
