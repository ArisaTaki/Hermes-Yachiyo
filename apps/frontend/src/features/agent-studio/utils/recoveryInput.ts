import type { RuntimeToolRecoveryAction } from '../../runtime-shared/toolRecoveryActions';
import { runtimeToolRecoveryMissingRequiredFields } from '../../runtime-shared/toolRecoveryActions';
import type { ToolCallSnapshot } from '../../yachiyo-studio/types';
import type { RunRecoveryCoordinate } from '../components/runDetailTypes';

export function runRecoveryInputPatchForAction(
  action: RuntimeToolRecoveryAction,
  coordinate: Pick<RunRecoveryCoordinate, 'x' | 'y'> | null,
  toolCall: ToolCallSnapshot,
): Record<string, unknown> | null {
  if (action.retry_input_source !== 'screen_capture_artifact') return null;
  const observedCoordinate = runRecoveryObservedCoordinateFromToolCall(toolCall);
  const patchCoordinate = coordinate || observedCoordinate;
  if (!patchCoordinate) return null;
  const inputPatch: Record<string, unknown> = {};
  if (runRecoveryActionNeedsRetryField(action, 'x')) inputPatch.x = patchCoordinate.x;
  if (runRecoveryActionNeedsRetryField(action, 'y')) inputPatch.y = patchCoordinate.y;
  return Object.keys(inputPatch).length ? inputPatch : null;
}

export function runRecoveryActionNeedsRetryField(
  action: RuntimeToolRecoveryAction,
  field: string,
): boolean {
  return (action.required_retry_fields || []).includes(field)
    || runtimeToolRecoveryMissingRequiredFields(action).includes(field);
}

export function runRecoveryObservedCoordinateFromToolCall(
  toolCall: ToolCallSnapshot,
): Pick<RunRecoveryCoordinate, 'x' | 'y'> | null {
  const observationEvidence = runRecoveryToolCallObservationEvidence(toolCall);
  const center = objectValue(observationEvidence.observed_center);
  const legacyCenter = objectValue(observationEvidence.center);
  const point = objectValue(observationEvidence.point);
  const x = runRecoveryCoordinateValue(center.x ?? legacyCenter.x ?? point.x ?? observationEvidence.x);
  const y = runRecoveryCoordinateValue(center.y ?? legacyCenter.y ?? point.y ?? observationEvidence.y);
  return x !== null && y !== null ? { x, y } : null;
}

function runRecoveryToolCallObservationEvidence(toolCall: ToolCallSnapshot): Record<string, unknown> {
  const records = [
    objectValue(toolCall.metadata),
    objectValue(toolCall.input_preview),
    objectValue(toolCall.output_preview),
  ];
  const seen = new Set<Record<string, unknown>>(records);
  for (let index = 0; index < records.length; index += 1) {
    const record = records[index];
    const nested = objectValue(record.observation_evidence);
    if (Object.keys(nested).length) return nested;
    for (const key of ['metadata', 'result', 'data']) {
      const value = objectValue(record[key]);
      if (!Object.keys(value).length || seen.has(value)) continue;
      records.push(value);
      seen.add(value);
    }
  }
  return {};
}

function runRecoveryCoordinateValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value.trim());
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
