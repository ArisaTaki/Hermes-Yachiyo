#!/usr/bin/env node
/** Measure Vite entry closures from its manifest and enforce release budgets. */

import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import zlib from 'node:zlib';


const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULT_DIST = path.join(PROJECT_ROOT, 'apps', 'frontend', 'dist');

const BUDGETS = {
  freeze: {
    boot_js_raw: 560_000,
    boot_js_gzip: 150_000,
    boot_css_raw: 375_000,
    boot_css_gzip: 60_000,
    studio_incremental_raw: 665_000,
    studio_incremental_gzip: 175_000,
    boot_plus_studio_raw: 1_570_000,
    boot_plus_studio_gzip: 375_000,
    max_js_chunk_raw: 600_000,
  },
  target: {
    boot_js_raw: 420_000,
    boot_js_gzip: 115_000,
    boot_css_raw: 375_000,
    boot_css_gzip: 60_000,
    studio_incremental_raw: 450_000,
    studio_incremental_gzip: 130_000,
    boot_plus_studio_raw: 1_245_000,
    boot_plus_studio_gzip: 305_000,
    max_js_chunk_raw: 450_000,
  },
};

function parseArgs(argv) {
  const args = {
    dist: DEFAULT_DIST,
    manifest: '',
    mode: 'freeze',
    reportJson: '',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    const value = argv[index + 1];
    if (item === '--dist' && value) {
      args.dist = path.resolve(value);
      index += 1;
    } else if (item === '--manifest' && value) {
      args.manifest = path.resolve(value);
      index += 1;
    } else if (item === '--mode' && value) {
      args.mode = value;
      index += 1;
    } else if (item === '--report-json' && value) {
      args.reportJson = path.resolve(value);
      index += 1;
    } else {
      throw new Error(`Unknown or incomplete argument: ${item}`);
    }
  }
  if (!(args.mode in BUDGETS)) {
    throw new Error(`Unknown budget mode: ${args.mode}`);
  }
  if (!args.manifest) args.manifest = path.join(args.dist, 'manifest.json');
  return args;
}

function readManifest(manifestPath) {
  const payload = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error(`Vite manifest must be an object: ${manifestPath}`);
  }
  return payload;
}

function bootEntryKey(manifest) {
  if (manifest['index.html']?.isEntry) return 'index.html';
  const entries = Object.entries(manifest)
    .filter(([, value]) => value?.isEntry === true)
    .map(([key]) => key);
  if (entries.length !== 1) {
    throw new Error(`Expected one Vite entry, found ${entries.length}`);
  }
  return entries[0];
}

function studioEntryKey(manifest) {
  const exact = 'src/views/AgentStudioView.tsx';
  if (manifest[exact]) return exact;
  const matches = Object.keys(manifest).filter((key) => key.endsWith('/AgentStudioView.tsx'));
  if (matches.length !== 1) {
    throw new Error(`Expected one AgentStudio dynamic entry, found ${matches.length}`);
  }
  return matches[0];
}

function staticClosure(manifest, entryKey) {
  const closure = new Set();
  const pending = [entryKey];
  while (pending.length) {
    const key = pending.pop();
    if (!key || closure.has(key)) continue;
    const entry = manifest[key];
    if (!entry) throw new Error(`Manifest import is missing: ${key}`);
    closure.add(key);
    for (const importedKey of entry.imports || []) pending.push(importedKey);
  }
  return closure;
}

function filesForClosure(manifest, closure) {
  const js = new Set();
  const css = new Set();
  for (const key of closure) {
    const entry = manifest[key];
    if (typeof entry?.file === 'string' && entry.file.endsWith('.js')) js.add(entry.file);
    for (const cssFile of entry?.css || []) {
      if (typeof cssFile === 'string' && cssFile.endsWith('.css')) css.add(cssFile);
    }
  }
  return { js, css };
}

function compressedSizes(buffer) {
  return {
    raw: buffer.length,
    gzip: zlib.gzipSync(buffer, { level: 9 }).length,
    brotli: zlib.brotliCompressSync(buffer, {
      params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 11 },
    }).length,
  };
}

function fileMetrics(dist, files) {
  const orderedFiles = [...files].sort();
  const result = { files: orderedFiles, raw: 0, gzip: 0, brotli: 0 };
  for (const relativeFile of orderedFiles) {
    const absoluteFile = path.resolve(dist, relativeFile);
    const relativeToDist = path.relative(dist, absoluteFile);
    if (relativeToDist.startsWith(`..${path.sep}`) || path.isAbsolute(relativeToDist)) {
      throw new Error(`Manifest asset escapes dist: ${relativeFile}`);
    }
    const sizes = compressedSizes(fs.readFileSync(absoluteFile));
    result.raw += sizes.raw;
    result.gzip += sizes.gzip;
    result.brotli += sizes.brotli;
  }
  return result;
}

function combinedMetrics(js, css) {
  return {
    raw: js.raw + css.raw,
    gzip: js.gzip + css.gzip,
    brotli: js.brotli + css.brotli,
  };
}

function maxJsChunk(dist, manifest) {
  const jsFiles = new Set(
    Object.values(manifest)
      .map((entry) => entry?.file)
      .filter((file) => typeof file === 'string' && file.endsWith('.js')),
  );
  const measured = [...jsFiles].map((file) => ({
    file,
    ...compressedSizes(fs.readFileSync(path.resolve(dist, file))),
  }));
  measured.sort((left, right) => right.raw - left.raw || left.file.localeCompare(right.file));
  return measured[0] || { file: '', raw: 0, gzip: 0, brotli: 0 };
}

function buildReport({ dist, manifestPath, manifest, mode }) {
  const bootKey = bootEntryKey(manifest);
  const studioKey = studioEntryKey(manifest);
  const bootClosure = staticClosure(manifest, bootKey);
  const studioClosure = staticClosure(manifest, studioKey);
  const studioIncrementalClosure = new Set(
    [...studioClosure].filter((key) => !bootClosure.has(key)),
  );
  const bootFiles = filesForClosure(manifest, bootClosure);
  const studioFiles = filesForClosure(manifest, studioIncrementalClosure);
  const bootJs = fileMetrics(dist, bootFiles.js);
  const bootCss = fileMetrics(dist, bootFiles.css);
  const studioJs = fileMetrics(dist, studioFiles.js);
  const studioCss = fileMetrics(dist, studioFiles.css);
  const studioTotal = combinedMetrics(studioJs, studioCss);
  const bootTotal = combinedMetrics(bootJs, bootCss);
  const bootPlusStudio = {
    raw: bootTotal.raw + studioTotal.raw,
    gzip: bootTotal.gzip + studioTotal.gzip,
    brotli: bootTotal.brotli + studioTotal.brotli,
  };
  const largestChunk = maxJsChunk(dist, manifest);
  const limits = BUDGETS[mode];
  const actuals = {
    boot_js_raw: bootJs.raw,
    boot_js_gzip: bootJs.gzip,
    boot_css_raw: bootCss.raw,
    boot_css_gzip: bootCss.gzip,
    studio_incremental_raw: studioTotal.raw,
    studio_incremental_gzip: studioTotal.gzip,
    boot_plus_studio_raw: bootPlusStudio.raw,
    boot_plus_studio_gzip: bootPlusStudio.gzip,
    max_js_chunk_raw: largestChunk.raw,
  };
  const checks = Object.entries(limits).map(([metric, limit]) => ({
    metric,
    actual: actuals[metric],
    limit,
    ok: actuals[metric] <= limit,
  }));
  return {
    ok: checks.every((check) => check.ok),
    mode,
    manifest: path.relative(PROJECT_ROOT, manifestPath) || path.basename(manifestPath),
    entries: { boot: bootKey, studio: studioKey },
    boot: {
      js: bootJs,
      css: bootCss,
      total: bootTotal,
    },
    studio_incremental: {
      js: studioJs,
      css: studioCss,
      total: studioTotal,
    },
    boot_plus_studio: bootPlusStudio,
    max_js_chunk: largestChunk,
    limits,
    checks,
  };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const manifest = readManifest(args.manifest);
  const report = buildReport({
    dist: args.dist,
    manifestPath: args.manifest,
    manifest,
    mode: args.mode,
  });
  const output = `${JSON.stringify(report, null, 2)}\n`;
  process.stdout.write(output);
  if (args.reportJson) {
    fs.mkdirSync(path.dirname(args.reportJson), { recursive: true });
    fs.writeFileSync(args.reportJson, output, 'utf8');
  }
  process.exitCode = report.ok ? 0 : 1;
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 2;
}
