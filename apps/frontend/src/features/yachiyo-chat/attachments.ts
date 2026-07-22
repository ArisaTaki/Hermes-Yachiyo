import type {
  ChatE2EImageDetail,
  ChatMessage,
  PendingAttachment,
} from './types';

export const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;

export type DesktopImageSelection = {
  mime_type?: string;
  file_name?: string;
  data_url?: string;
  size?: number;
};

export function withResolvedAttachmentUrls(messages: ChatMessage[], baseUrl: string): ChatMessage[] {
  return messages.map((message) => {
    if (!message.attachments?.length) return message;
    return {
      ...message,
      attachments: message.attachments.map((attachment) => ({
        ...attachment,
        url: resolveAttachmentUrl(attachment.url, baseUrl),
      })),
    };
  });
}

export function resolveAttachmentUrl(url: string | undefined, baseUrl: string) {
  if (!url) return '';
  if (/^https?:\/\//i.test(url) || url.startsWith('data:')) return url;
  if (!url.startsWith('/')) return url;
  return `${baseUrl}${url}`;
}

export function clipboardImageFiles(data: DataTransfer | null) {
  if (!data) return [];
  const files: File[] = [];
  for (const item of Array.from(data.items || [])) {
    if (item.kind !== 'file' || !item.type.startsWith('image/')) continue;
    const file = item.getAsFile();
    if (file) files.push(file);
  }
  if (files.length) return files;
  return Array.from(data.files || []).filter((file) => file.type.startsWith('image/'));
}

function fileFromImageDataUrl(dataUrl: string, name: string, fallbackMimeType: string): File | null {
  const commaIndex = dataUrl.indexOf(',');
  if (!dataUrl.startsWith('data:image/') || commaIndex < 0) return null;
  try {
    const metadata = dataUrl.slice(5, commaIndex);
    const declaredMimeType = String(metadata.split(';')[0] || '').trim().toLowerCase();
    const mimeType = declaredMimeType || fallbackMimeType;
    if (!mimeType.startsWith('image/')) return null;
    let payload = dataUrl.slice(commaIndex + 1);
    let buffer: ArrayBuffer;
    if (metadata.split(';').some((part) => part.trim().toLowerCase() === 'base64')) {
      payload = decodeURIComponent(payload.replace(/\s/g, ''));
      const binary = atob(payload);
      buffer = new ArrayBuffer(binary.length);
      const bytes = new Uint8Array(buffer);
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    } else {
      const bytes = new TextEncoder().encode(decodeURIComponent(payload));
      buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    }
    return new File([buffer], name, { type: mimeType });
  } catch {
    return null;
  }
}

export async function fileFromE2EImageDetail(detail: ChatE2EImageDetail | undefined): Promise<File | null> {
  if (!detail) return null;
  const mimeType = String(detail.mime_type || detail.mimeType || 'image/png').trim() || 'image/png';
  const name = String(detail.name || 'e2e-image.png').trim() || 'e2e-image.png';
  const dataUrl = String(detail.data_url || detail.dataUrl || '').trim()
    || (detail.base64 ? `data:${mimeType};base64,${String(detail.base64).trim()}` : '');
  if (!dataUrl.startsWith('data:image/')) return null;
  return fileFromImageDataUrl(dataUrl, name, mimeType);
}

export async function fileFromDesktopImageSelection(selection: DesktopImageSelection | undefined): Promise<File | null> {
  if (!selection) return null;
  const mimeType = String(selection.mime_type || 'image/png').trim() || 'image/png';
  const name = String(selection.file_name || 'desktop-image.png').trim() || 'desktop-image.png';
  const dataUrl = String(selection.data_url || '').trim();
  if (!dataUrl.startsWith('data:image/')) return null;
  if (Number(selection.size || 0) > MAX_ATTACHMENT_BYTES) {
    throw new Error(`图片 ${name} 超过 8 MB`);
  }
  return fileFromImageDataUrl(dataUrl, name, mimeType);
}

export function readPendingAttachment(file: File): Promise<PendingAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`读取图片失败：${file.name || '未命名'}`));
    reader.onload = async () => {
      const dataUrl = typeof reader.result === 'string' ? reader.result : '';
      if (!dataUrl.startsWith('data:image/')) {
        reject(new Error('只支持图片附件'));
        return;
      }
      let dimensions: { width: number; height: number };
      try {
        dimensions = await loadImageDimensions(dataUrl);
      } catch {
        reject(new Error(`无法读取图片尺寸：${file.name || '未命名'}`));
        return;
      }
      if (dimensions.width < 16 || dimensions.height < 16) {
        reject(new Error('图片尺寸过小，容易被上游视觉模型判定为不可处理；请换用正常尺寸的截图或图片。'));
        return;
      }
      resolve({
        id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
        name: file.name || 'pasted-image.png',
        mime_type: file.type || 'image/png',
        size: file.size,
        width: dimensions.width,
        height: dimensions.height,
        data_url: dataUrl,
      });
    };
    reader.readAsDataURL(file);
  });
}

export function loadImageDimensions(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth || image.width, height: image.naturalHeight || image.height });
    image.onerror = () => reject(new Error('image load failed'));
    image.src = dataUrl;
  });
}
