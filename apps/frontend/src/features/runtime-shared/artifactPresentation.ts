export type RuntimeArtifactPresentationMode = 'consumer' | 'diagnostic';

export type RuntimeArtifactPresentationSource = {
  kind?: string | null;
  mime_type?: string | null;
  path?: string | null;
  title?: string | null;
};

export type RuntimeArtifactPresentation = {
  label: string;
  tooltip: string;
};

export const CONSUMER_ARTIFACT_READ_ERROR = '暂时无法打开这个结果，请重试。';

export function runtimeArtifactPresentation(
  artifact: RuntimeArtifactPresentationSource,
  mode: RuntimeArtifactPresentationMode = 'diagnostic',
): RuntimeArtifactPresentation {
  const title = String(artifact.title || '').trim();
  const path = String(artifact.path || '').trim();
  const kind = String(artifact.kind || '').trim();
  if (mode === 'consumer') {
    return {
      label: title || consumerArtifactKindLabel(kind, artifact.mime_type),
      tooltip: title,
    };
  }
  const label = title || path || kind || 'Artifact';
  return {
    label,
    tooltip: path || label,
  };
}

export function runtimeArtifactReadError(
  error: unknown,
  mode: RuntimeArtifactPresentationMode = 'diagnostic',
  fallback = '读取 artifact 失败',
): string {
  if (mode === 'consumer') return CONSUMER_ARTIFACT_READ_ERROR;
  if (error && typeof error === 'object') {
    const message = String((error as { message?: unknown }).message || '').trim();
    if (message) return message;
  }
  return fallback;
}

function consumerArtifactKindLabel(kind: string, mimeType: string | null | undefined): string {
  const normalizedKind = kind.toLowerCase();
  const normalizedMimeType = String(mimeType || '').toLowerCase();
  if (normalizedKind === 'image' || normalizedKind === 'screenshot' || normalizedMimeType.startsWith('image/')) {
    return normalizedKind === 'screenshot' ? '截图结果' : '图片结果';
  }
  if (normalizedKind === 'audio' || normalizedMimeType.startsWith('audio/')) return '音频结果';
  if (normalizedKind === 'video' || normalizedMimeType.startsWith('video/')) return '视频结果';
  if (
    ['document', 'file', 'json', 'markdown', 'text'].includes(normalizedKind)
    || normalizedMimeType.startsWith('text/')
    || normalizedMimeType === 'application/json'
  ) {
    return '文件结果';
  }
  return '任务结果';
}
