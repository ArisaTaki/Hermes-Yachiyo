import { useMemo, useState, type ChangeEvent, type DragEvent } from 'react';

import { useAgentDesk } from '../hooks/useAgentDesk';
import type { AgentDeskItemSnapshot } from '../../yachiyo-studio/types';

type AgentDeskPanelProps = {
  agentId: string;
  busy: boolean;
  selectedAgentReadOnly: boolean;
};

const AGENT_DESK_IMPORT_MAX_BYTES = 256 * 1024;
const AGENT_DESK_TEXT_EXTENSIONS = new Set([
  'csv',
  'json',
  'log',
  'md',
  'mdx',
  'txt',
  'xml',
  'yaml',
  'yml',
]);

export function AgentDeskPanel({
  agentId,
  busy,
  selectedAgentReadOnly,
}: AgentDeskPanelProps) {
  const [filePath, setFilePath] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [draggingDeskFile, setDraggingDeskFile] = useState(false);
  const [importingFiles, setImportingFiles] = useState(false);
  const [importStatus, setImportStatus] = useState('');
  const {
    desk,
    error,
    loading,
    noteDraft,
    savingFile,
    savingNote,
    status,
    triggeringFileEvent,
    loadDesk,
    saveFile,
    saveNote,
    triggerFileEvent,
    setNoteDraft,
  } = useAgentDesk(agentId);
  const items = useMemo(() => [...(desk?.items || [])].sort(compareDeskItems), [desk?.items]);
  const actionDisabled = (
    busy
    || loading
    || savingFile
    || savingNote
    || triggeringFileEvent
    || importingFiles
    || selectedAgentReadOnly
  );

  if (!agentId) return null;

  async function writeFile() {
    const cleanPath = filePath.trim();
    if (!cleanPath) return;
    const saved = await saveFile(cleanPath, fileContent);
    if (saved) {
      await triggerFileEvent(cleanPath, 'modified');
      setFilePath('');
      setFileContent('');
    }
  }

  async function importDeskFiles(fileList: FileList | File[] | null) {
    const files = Array.from(fileList || []);
    if (!files.length || actionDisabled) return;
    setImportingFiles(true);
    setImportStatus('');
    const skipped: string[] = [];
    let imported = 0;
    try {
      for (const file of files) {
        if (file.size > AGENT_DESK_IMPORT_MAX_BYTES) {
          skipped.push(`${file.name}: 超过 ${formatBytes(AGENT_DESK_IMPORT_MAX_BYTES)}`);
          continue;
        }
        if (!isDeskImportTextFile(file)) {
          skipped.push(`${file.name}: 非文本文件`);
          continue;
        }
        const path = deskImportPath(file);
        let content = '';
        try {
          content = await file.text();
        } catch {
          skipped.push(`${file.name}: 读取失败`);
          continue;
        }
        const saved = await saveFile(path, content);
        if (saved) {
          imported += 1;
          await triggerFileEvent(path, 'created');
        }
      }
    } finally {
      setDraggingDeskFile(false);
      setImportingFiles(false);
    }
    setImportStatus(importStatusMessage(imported, skipped));
  }

  function handleDeskImportSelect(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.currentTarget.files || []);
    event.currentTarget.value = '';
    void importDeskFiles(files);
  }

  function handleDeskDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (!actionDisabled) setDraggingDeskFile(true);
  }

  function handleDeskDragLeave(event: DragEvent<HTMLDivElement>) {
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDraggingDeskFile(false);
  }

  function handleDeskDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    if (actionDisabled) {
      setDraggingDeskFile(false);
      return;
    }
    void importDeskFiles(event.dataTransfer.files);
  }

  return (
    <section className="agent-desk-panel" data-testid="agent-desk-panel" aria-label="Agent Desk">
      <div className="section-heading-row compact agent-desk-heading">
        <div>
          <h3>Agent Desk</h3>
          <p>{desk?.root_path || 'Workspace'}</p>
        </div>
        <button
          type="button"
          className="hy-btn hy-btn-ghost"
          data-testid="agent-desk-refresh"
          disabled={busy || loading}
          onClick={() => void loadDesk()}
        >
          {loading ? '刷新中' : '刷新'}
        </button>
      </div>

      {selectedAgentReadOnly ? (
        <div className="agent-inline-note">系统 Agent 的 Desk 只读。</div>
      ) : null}
      {error ? <div className="agent-inline-note warn">{error}</div> : null}
      {status ? <div className="agent-inline-note">{status}</div> : null}
      {importStatus ? (
        <div className="agent-inline-note" data-testid="agent-desk-import-status">
          {importStatus}
        </div>
      ) : null}

      <label>
        <span>Desk Notes</span>
        <textarea
          className="hy-input agent-desk-note"
          data-testid="agent-desk-note"
          value={noteDraft}
          readOnly={selectedAgentReadOnly}
          onChange={(event) => setNoteDraft(event.target.value)}
        />
      </label>
      <div className="agent-desk-actions">
        <button
          type="button"
          className="hy-btn hy-btn-primary"
          data-testid="agent-desk-save-note"
          disabled={actionDisabled}
          onClick={() => void saveNote()}
        >
          {savingNote ? '保存中' : '保存便签'}
        </button>
      </div>

      <div
        className={`agent-desk-dropzone${draggingDeskFile ? ' dragging' : ''}`}
        data-testid="agent-desk-dropzone"
        onDragOver={handleDeskDragOver}
        onDragLeave={handleDeskDragLeave}
        onDrop={handleDeskDrop}
      >
        <div>
          <strong>Desk Import</strong>
          <span>Text, Markdown, JSON · imports/</span>
        </div>
        <label className="hy-btn hy-btn-ghost">
          <input
            data-testid="agent-desk-file-import"
            disabled={actionDisabled}
            multiple
            type="file"
            onChange={handleDeskImportSelect}
          />
          {importingFiles ? '导入中' : '选择文件'}
        </label>
      </div>

      <div className="agent-desk-file-writer">
        <label>
          <span>File Path</span>
          <input
            className="hy-input"
            data-testid="agent-desk-file-path"
            value={filePath}
            readOnly={selectedAgentReadOnly}
            placeholder="inputs/brief.md"
            onChange={(event) => setFilePath(event.target.value)}
          />
        </label>
        <label>
          <span>Content</span>
          <textarea
            className="hy-input agent-desk-file-content"
            data-testid="agent-desk-file-content"
            value={fileContent}
            readOnly={selectedAgentReadOnly}
            onChange={(event) => setFileContent(event.target.value)}
          />
        </label>
        <div className="agent-desk-actions">
          <button
            type="button"
            className="hy-btn hy-btn-ghost"
            data-testid="agent-desk-save-file"
            disabled={actionDisabled || !filePath.trim()}
            onClick={() => void writeFile()}
          >
            {savingFile ? '写入中' : '写入文件'}
          </button>
        </div>
      </div>

      <div className="agent-desk-list" data-testid="agent-desk-item-list">
        {items.length ? items.map((item) => (
          <DeskItemRow item={item} key={item.path} />
        )) : (
          <div className="agent-inline-note">Desk 暂无文件。</div>
        )}
      </div>
    </section>
  );
}

function DeskItemRow({ item }: { item: AgentDeskItemSnapshot }) {
  return (
    <div className={`agent-desk-item ${item.kind}`}>
      <div>
        <strong>{item.path}</strong>
        <span>{deskItemKindLabel(item.kind)} · {formatBytes(item.size_bytes)}</span>
      </div>
      {item.preview_text ? <p>{item.preview_text}</p> : null}
    </div>
  );
}

function compareDeskItems(a: AgentDeskItemSnapshot, b: AgentDeskItemSnapshot) {
  if (a.kind === 'note' && b.kind !== 'note') return -1;
  if (b.kind === 'note' && a.kind !== 'note') return 1;
  if (a.kind === 'directory' && b.kind === 'file') return -1;
  if (b.kind === 'directory' && a.kind === 'file') return 1;
  return a.path.localeCompare(b.path);
}

function deskImportPath(file: File) {
  return `imports/${safeDeskImportName(file.name || 'untitled.txt')}`;
}

function safeDeskImportName(name: string) {
  const cleaned = name.replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, '-').replace(/^\.+/, '').trim();
  return cleaned || 'untitled.txt';
}

function isDeskImportTextFile(file: File) {
  if (file.type.startsWith('text/')) return true;
  if (['application/json', 'application/xml'].includes(file.type)) return true;
  const extension = file.name.split('.').pop()?.toLowerCase() || '';
  return AGENT_DESK_TEXT_EXTENSIONS.has(extension);
}

function importStatusMessage(imported: number, skipped: string[]) {
  const parts: string[] = [];
  if (imported) parts.push(`已导入 ${imported} 个文件`);
  if (skipped.length) {
    const preview = skipped.slice(0, 2).join('；');
    parts.push(`跳过 ${skipped.length} 个文件：${preview}${skipped.length > 2 ? '；...' : ''}`);
  }
  return parts.join('。');
}

function deskItemKindLabel(kind: AgentDeskItemSnapshot['kind']) {
  if (kind === 'directory') return 'Directory';
  if (kind === 'note') return 'Note';
  return 'File';
}

function formatBytes(value: number | null | undefined) {
  if (value === null || value === undefined) return '-';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
