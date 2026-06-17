import type { ChatMessage } from './types';

export function messageArtifactCount(message?: ChatMessage | null) {
  return Number(message?.metadata?.run_artifact_count || 0);
}

export function messageArtifactTitle(message?: ChatMessage | null) {
  return message?.metadata?.run_artifacts
    ?.map((artifact) => artifact.path)
    .filter(Boolean)
    .join('\n') || '查看任务产物';
}
