#!/usr/bin/env node
/**
 * Re-sync text files from Lovable into frontend-reimagined/.
 * Requires LOVABLE_API_KEY. Skips public/favicon.ico (binary).
 */
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const root = join(repoRoot, "frontend-reimagined");
const manifest = JSON.parse(
  readFileSync(join(root, ".lovable-manifest.json"), "utf8"),
);
const { project_id: projectId, paths } = manifest;
const ref = process.env.LOVABLE_REF ?? "7b2f2acbceb506f1181bad3a00b76f411f3070fb";
const key = process.env.LOVABLE_API_KEY;
if (!key) {
  console.error("LOVABLE_API_KEY is required");
  process.exit(1);
}

const failures = [];
let written = 0;

for (const path of paths) {
  const dest = join(root, path);
  if (path === "public/favicon.ico") continue;
  try {
    const url = `https://api.lovable.dev/v1/projects/${projectId}/files/${encodeURIComponent(path)}?ref=${ref}`;
    const res = await fetch(url, { headers: { "Lovable-API-Key": key } });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const text = await res.text();
    mkdirSync(dirname(dest), { recursive: true });
    writeFileSync(dest, text);
    written++;
    console.log("ok", path);
  } catch (e) {
    failures.push({ path, error: String(e) });
    console.error("fail", path, e);
  }
}

console.log(JSON.stringify({ written, failures }, null, 2));
process.exit(failures.length ? 1 : 0);
