import {execFileSync} from "node:child_process";
import {existsSync, mkdtempSync, rmSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import process from "node:process";

const projectRoot = path.resolve(import.meta.dirname, "..");
const backendRoot = path.resolve(projectRoot, "../backend");
const outputPath = path.resolve(projectRoot, "src/lib/api/schema.d.ts");
const openapiBinary = path.resolve(projectRoot, "node_modules/.bin/openapi-typescript");
const tempDirectory = mkdtempSync(path.join(tmpdir(), "xoxoedu-openapi-"));
const openapiPath = path.join(tempDirectory, "openapi.json");

const pythonCandidates = [
  process.env.BACKEND_PYTHON,
  path.join(backendRoot, ".venv/bin/python"),
  "python3",
].filter(Boolean);

const pythonProgram = [
  "import json",
  "import pathlib",
  "import sys",
  "from app.main import app",
  "pathlib.Path(sys.argv[1]).write_text(json.dumps(app.openapi()), encoding='utf-8')",
].join(";");

function generateOpenapiDocument() {
  let lastError;

  for (const pythonPath of pythonCandidates) {
    try {
      if (pythonPath.includes(path.sep) && !existsSync(pythonPath)) {
        continue;
      }

      execFileSync(pythonPath, ["-c", pythonProgram, openapiPath], {
        cwd: backendRoot,
        stdio: "pipe",
      });
      return pythonPath;
    } catch (error) {
      lastError = error;
    }
  }

  throw new Error(
    `Failed to generate backend OpenAPI JSON. Last error: ${lastError instanceof Error ? lastError.message : String(lastError)}`,
  );
}

try {
  const pythonPath = generateOpenapiDocument();
  console.log(`Generating schema from backend app using ${pythonPath}`);
  execFileSync(openapiBinary, [openapiPath, "-o", outputPath], {
    cwd: projectRoot,
    stdio: "inherit",
  });
} finally {
  rmSync(tempDirectory, {force: true, recursive: true});
}
