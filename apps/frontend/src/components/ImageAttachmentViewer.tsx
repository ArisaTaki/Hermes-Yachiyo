import { useEffect, useState } from 'react';

import { openExternalUrl } from '../lib/bridge';

export type ImageAttachment = {
  id?: string;
  kind?: string;
  name?: string;
  mime_type?: string;
  size?: number;
  url?: string;
  spoken_text?: string;
};

type Props = {
  attachment: ImageAttachment;
};

export function ImageAttachmentViewer({ attachment }: Props) {
  if (attachment.kind === 'audio' || String(attachment.mime_type || '').startsWith('audio/')) {
    return <AudioAttachmentViewer attachment={attachment} />;
  }
  return <ImagePreviewAttachment attachment={attachment} />;
}

function ImagePreviewAttachment({ attachment }: Props) {
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const name = attachment.name || '图片';
  const sizeText = formatBytes(attachment.size);
  const canPreview = Boolean(attachment.url) && !failed;

  useEffect(() => {
    if (!open) return undefined;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open]);

  return (
    <>
      <button
        className={`message-attachment ${failed ? 'is-broken' : ''}`}
        type="button"
        disabled={!attachment.url}
        title={`${name} · ${sizeText} · 点击查看大图`}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          if (canPreview) setOpen(true);
        }}
      >
        {canPreview ? (
          <img src={attachment.url} alt={name} onError={() => setFailed(true)} />
        ) : (
          <span className="message-attachment-fallback">图片预览不可用</span>
        )}
        <span>{name}</span>
      </button>

      {open && canPreview ? (
        <div
          className="image-viewer-backdrop"
          role="presentation"
          onClick={() => setOpen(false)}
        >
          <section
            className="image-viewer-modal"
            role="dialog"
            aria-modal="true"
            aria-label={name}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="image-viewer-toolbar">
              <div>
                <h2>{name}</h2>
                <p>{attachment.mime_type || 'image'} · {sizeText}</p>
              </div>
              <div className="image-viewer-actions">
                <button
                  type="button"
                  onClick={() => {
                    if (attachment.url) void openExternalUrl(attachment.url);
                  }}
                >
                  打开原图
                </button>
                <button type="button" onClick={() => setOpen(false)}>关闭</button>
              </div>
            </header>
            <div className="image-viewer-stage">
              <img src={attachment.url} alt={name} />
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}

function AudioAttachmentViewer({ attachment }: Props) {
  const name = attachment.name || '语音';
  const sizeText = formatBytes(attachment.size);
  return (
    <div className="message-audio-attachment">
      <div className="message-audio-meta">
        <strong>{name}</strong>
        <span>{attachment.mime_type || 'audio'} · {sizeText}</span>
      </div>
      {attachment.url ? (
        <audio controls preload="none" src={attachment.url}>
          当前环境不支持音频播放。
        </audio>
      ) : (
        <span className="message-attachment-fallback">语音缓存不可用</span>
      )}
      {attachment.spoken_text ? <p>{attachment.spoken_text}</p> : null}
    </div>
  );
}

function formatBytes(value?: number) {
  const size = Number(value || 0);
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size >= 1024) return `${Math.round(size / 1024)} KB`;
  return `${size} B`;
}
