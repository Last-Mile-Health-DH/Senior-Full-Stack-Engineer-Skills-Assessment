import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";

const files = readdirSync(new URL(".", import.meta.url))
  .filter((file) => file.endsWith(".test.mjs"))
  .map((file) => `tests/${file}`);

const result = spawnSync(process.execPath, ["--test", ...files], {
  cwd: new URL("..", import.meta.url),
  stdio: "inherit",
});

process.exit(result.status ?? 1);
