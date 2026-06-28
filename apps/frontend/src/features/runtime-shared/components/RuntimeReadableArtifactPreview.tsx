import type { MouseEvent } from 'react';
import { useState } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import {
  RuntimeArtifactPreview,
  type RuntimeArtifactSnapshot,
  type RuntimeArtifactVariant,
} from './RuntimeArtifactPreview';

export type RuntimeReadableArtifactContent = {
  content?: string;
  mime_type?: string | null;
  truncated?: boolean;
};

export type RuntimeImageArtifactPointSelection = {
  artifact: RuntimeArtifactSnapshot;
  artifact_path: string;
  natural_height: number;
  natural_width: number;
  rendered_height: number;
  rendered_width: number;
  x: number;
  y: number;
};

export type RuntimeImageArtifactSelectedPoint = Pick<
  RuntimeImageArtifactPointSelection,
  'artifact_path' | 'natural_height' | 'natural_width' | 'x' | 'y'
>;

type RuntimeReadableArtifactContentPreviewProps = {
  artifact: RuntimeArtifactSnapshot;
  className?: string;
  contentTestId?: string;
  emptyContentLabel?: string;
  imagePointLabel?: string;
  label?: string;
  onSelectImagePoint?: (selection: RuntimeImageArtifactPointSelection) => void;
  preview: RuntimeReadableArtifactContent;
  selectedImagePoint?: RuntimeImageArtifactSelectedPoint | null;
};

type RuntimeReadableArtifactPreviewProps = {
  artifact: RuntimeArtifactSnapshot;
  busyLabel?: string;
  className?: string;
  contentClassName?: string;
  contentTestId?: string;
  emptyContentLabel?: string;
  errorClassName?: string;
  errorFallback?: string;
  errorTestId?: string;
  previewActionClassName?: string;
  previewActionTestId?: string;
  previewClassName?: string;
  previewTestId?: string;
  previewVariant?: RuntimeArtifactVariant;
  imagePointLabel?: string;
  onSelectImagePoint?: (selection: RuntimeImageArtifactPointSelection) => void;
  readArtifact?: (
    path: string,
    artifact: RuntimeArtifactSnapshot,
  ) => Promise<RuntimeReadableArtifactContent>;
  selectedImagePoint?: RuntimeImageArtifactSelectedPoint | null;
  shellTestId?: string;
  statusClassName?: string;
  statusTestId?: string;
  triggerClassName?: string;
};

export function RuntimeReadableArtifactPreview({
  artifact,
  busyLabel = '读取 artifact...',
  className = 'runtime-readable-artifact',
  contentClassName = 'runtime-readable-artifact-content',
  contentTestId = 'runtime-readable-artifact-content',
  emptyContentLabel = '(empty artifact)',
  errorClassName = 'runtime-readable-artifact-status error',
  errorFallback = '读取 artifact 失败',
  errorTestId = 'runtime-readable-artifact-error',
  previewActionClassName = 'runtime-readable-artifact-action',
  previewActionTestId = 'runtime-readable-artifact-action',
  previewClassName = 'runtime-artifact-preview',
  previewTestId = 'runtime-artifact-preview',
  previewVariant = 'compact',
  imagePointLabel = '点击截图补齐坐标',
  onSelectImagePoint,
  readArtifact,
  selectedImagePoint,
  shellTestId = 'runtime-readable-artifact-shell',
  statusClassName = 'runtime-readable-artifact-status',
  statusTestId = 'runtime-readable-artifact-loading',
  triggerClassName = 'runtime-readable-artifact-button',
}: RuntimeReadableArtifactPreviewProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<RuntimeReadableArtifactContent | null>(null);
  const path = String(artifact.path || '').trim();
  const canReadArtifact = Boolean(readArtifact && path);

  if (!canReadArtifact) {
    return (
      <RuntimeArtifactPreview
        artifact={artifact}
        className={previewClassName}
        testId={previewTestId}
        variant={previewVariant}
      />
    );
  }

  async function togglePreview() {
    if (!readArtifact || !path) return;
    if (preview) {
      setPreview(null);
      setError('');
      return;
    }
    setBusy(true);
    setError('');
    try {
      setPreview(await readArtifact(path, artifact));
    } catch (err) {
      setError(err instanceof Error ? err.message : errorFallback);
    } finally {
      setBusy(false);
    }
  }

  const label = artifact.title || path || artifact.kind || 'Artifact';

  return (
    <div
      className={className}
      data-artifact-id={artifact.artifact_id}
      data-artifact-path={path}
      data-testid={shellTestId}
    >
      <button
        type="button"
        aria-expanded={Boolean(preview)}
        className={triggerClassName}
        disabled={busy}
        onClick={() => void togglePreview()}
        title={path || label}
      >
        <RuntimeArtifactPreview
          actions={<UiIcon name={preview ? 'close' : 'paperclip'} />}
          actionsClassName={previewActionClassName}
          actionsElement="span"
          actionsTestId={previewActionTestId}
          artifact={artifact}
          as="span"
          className={previewClassName}
          testId={previewTestId}
          variant={previewVariant}
        />
      </button>
      {busy ? (
        <p className={statusClassName} data-testid={statusTestId}>
          {busyLabel}
        </p>
      ) : null}
      {error ? (
        <p className={errorClassName} data-testid={errorTestId}>
          {error}
        </p>
      ) : null}
      {preview ? (
        <RuntimeReadableArtifactContentPreview
          artifact={artifact}
          className={contentClassName}
          contentTestId={contentTestId}
          emptyContentLabel={emptyContentLabel}
          imagePointLabel={imagePointLabel}
          onSelectImagePoint={onSelectImagePoint}
          preview={preview}
          selectedImagePoint={selectedImagePoint}
        />
      ) : null}
    </div>
  );
}

export function RuntimeReadableArtifactContentPreview({
  artifact,
  className = 'runtime-readable-artifact-content',
  contentTestId = 'runtime-readable-artifact-content',
  emptyContentLabel = '(empty artifact)',
  imagePointLabel = '点击截图补齐坐标',
  label = artifact.title || artifact.path || artifact.kind || 'Artifact',
  onSelectImagePoint,
  preview,
  selectedImagePoint,
}: RuntimeReadableArtifactContentPreviewProps) {
  const path = String(artifact.path || '').trim();
  const imagePreviewSrc = runtimeArtifactImagePreviewSource(preview, artifact);
  const selectedPoint = selectedImagePoint && (!selectedImagePoint.artifact_path || selectedImagePoint.artifact_path === path)
    ? selectedImagePoint
    : null;
  const selectedPointStyle = selectedPoint
    ? runtimeImageArtifactPointStyle(selectedPoint)
    : undefined;
  const selectableImage = Boolean(onSelectImagePoint);

  function handleImagePointSelection(event: MouseEvent<HTMLImageElement>) {
    if (!onSelectImagePoint) return;
    const selection = runtimeImageArtifactPointSelection(event, artifact, path);
    if (selection) onSelectImagePoint(selection);
  }

  if (imagePreviewSrc) {
    return (
      <div
        className={`runtime-readable-artifact-image-frame${selectableImage ? ' is-selectable' : ''}`}
        data-coordinate-pick-enabled={selectableImage ? 'true' : 'false'}
        data-selected-x={selectedPoint?.x ?? ''}
        data-selected-y={selectedPoint?.y ?? ''}
        data-testid={`${contentTestId}-point-frame`}
      >
        <img
          alt={label}
          className={`${className} runtime-readable-artifact-image`}
          data-testid={contentTestId}
          onClick={handleImagePointSelection}
          src={imagePreviewSrc}
        />
        {selectedPoint && selectedPointStyle ? (
          <span
            aria-hidden="true"
            className="runtime-readable-artifact-image-marker"
            data-testid={`${contentTestId}-point-marker`}
            style={selectedPointStyle}
          />
        ) : null}
        {selectableImage ? (
          <small
            className="runtime-readable-artifact-image-point"
            data-testid={`${contentTestId}-point-label`}
          >
            {selectedPoint ? `${selectedPoint.x}, ${selectedPoint.y}` : imagePointLabel}
          </small>
        ) : null}
      </div>
    );
  }

  return (
    <pre className={className} data-testid={contentTestId}>
      {preview.content || emptyContentLabel}
    </pre>
  );
}

function runtimeArtifactImagePreviewSource(
  preview: RuntimeReadableArtifactContent,
  artifact: RuntimeArtifactSnapshot,
) {
  const mimeType = String(preview.mime_type || artifact.mime_type || '').trim();
  const content = String(preview.content || '').trim();
  if (!mimeType.startsWith('image/') || !content) return '';
  if (content.startsWith('data:image/')) return content;
  return `data:${mimeType};base64,${content}`;
}

function runtimeImageArtifactPointSelection(
  event: MouseEvent<HTMLImageElement>,
  artifact: RuntimeArtifactSnapshot,
  path: string,
): RuntimeImageArtifactPointSelection | null {
  const image = event.currentTarget;
  const rect = image.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const naturalWidth = image.naturalWidth || Math.round(rect.width);
  const naturalHeight = image.naturalHeight || Math.round(rect.height);
  if (!naturalWidth || !naturalHeight) return null;
  const relativeX = clampNumber(event.clientX - rect.left, 0, rect.width);
  const relativeY = clampNumber(event.clientY - rect.top, 0, rect.height);
  return {
    artifact,
    artifact_path: path,
    natural_height: naturalHeight,
    natural_width: naturalWidth,
    rendered_height: rect.height,
    rendered_width: rect.width,
    x: Math.round((relativeX / rect.width) * Math.max(0, naturalWidth - 1)),
    y: Math.round((relativeY / rect.height) * Math.max(0, naturalHeight - 1)),
  };
}

function runtimeImageArtifactPointStyle(point: RuntimeImageArtifactSelectedPoint) {
  const naturalWidth = Number(point.natural_width || 0);
  const naturalHeight = Number(point.natural_height || 0);
  if (!naturalWidth || !naturalHeight) return undefined;
  return {
    left: `${(Number(point.x || 0) / Math.max(1, naturalWidth - 1)) * 100}%`,
    top: `${(Number(point.y || 0) / Math.max(1, naturalHeight - 1)) * 100}%`,
  };
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
