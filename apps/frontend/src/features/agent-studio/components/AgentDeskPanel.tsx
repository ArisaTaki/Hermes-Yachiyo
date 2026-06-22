import { useMemo, useState } from 'react';

import { useAgentDesk } from '../hooks/useAgentDesk';
import type { AgentDeskItemSnapshot } from '../../yachiyo-studio/types';

type AgentDeskPanelProps = {
  agentId: string;
  busy: boolean;
  selectedAgentReadOnly: boolean;
};

export function AgentDeskPanel({
  agentId,
  busy,
  selectedAgentReadOnly,
}: AgentDeskPanelProps) {
  const [filePath, setFilePath] = useState('');
  const [fileContent, setFileContent] = useState('');
  const {
    desk,
    error,
    loading,
    noteDraft,
    savingFile,
    savingNote,
    status,
    loadDesk,
    saveFile,
    saveNote,
    setNoteDraft,
  } = useAgentDesk(agentId);
  const items = useMemo(() => [...(desk?.items || [])].sort(compareDeskItems), [desk?.items]);
  const actionDisabled = busy || loading || savingFile || savingNote || selectedAgentReadOnly;

  if (!agentId) return null;

  async function writeFile() {
    const cleanPath = filePath.trim();
    if (!cleanPath) return;
    const saved = await saveFile(cleanPath, fileContent);
    if (saved) {
      setFilePath('');
      setFileContent('');
    }
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
