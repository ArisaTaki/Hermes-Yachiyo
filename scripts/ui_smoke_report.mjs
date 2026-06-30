import fs from 'node:fs';
import path from 'node:path';

export function parseUiSmokeArgs(argv) {
  const options = { reportJson: null };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--report-json') {
      const value = argv[index + 1];
      if (!value) throw new Error('--report-json requires a path');
      options.reportJson = path.resolve(value);
      index += 1;
      continue;
    }
    throw new Error(`unknown argument: ${arg}`);
  }
  return options;
}

export function errorText(error) {
  return error instanceof Error ? error.message : String(error);
}

export function uiSmokeReportPayload({ ok, mode, stage, checks, details = {}, error }) {
  const payload = {
    ok,
    mode,
    platform: process.platform,
    stage,
    checks: { ...checks },
  };
  if (ok) {
    return { ...payload, ...details };
  }
  return {
    ...payload,
    error: error || 'unknown UI smoke failure',
    blocking_condition: 'electron_ui_smoke_failed',
  };
}

export function writeUiSmokeReport(reportJson, payload) {
  if (!reportJson) return;
  fs.mkdirSync(path.dirname(reportJson), { recursive: true });
  fs.writeFileSync(
    reportJson,
    `${JSON.stringify(payload, null, 2)}\n`,
    'utf8',
  );
}

export function safeWriteUiSmokeReport(reportJson, payload) {
  try {
    writeUiSmokeReport(reportJson, payload);
  } catch (error) {
    console.error(`failed to write UI smoke report: ${errorText(error)}`);
  }
}
