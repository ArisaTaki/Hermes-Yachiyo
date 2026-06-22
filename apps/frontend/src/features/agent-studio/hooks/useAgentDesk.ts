import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  getYachiyoAgentDesk,
  saveYachiyoAgentDeskFile,
  saveYachiyoAgentDeskNote,
} from '../../yachiyo-studio/api';
import type { AgentDeskItemSnapshot, AgentDeskSnapshot } from '../../yachiyo-studio/types';

type DeskBusyAction = '' | 'load' | 'note' | 'file';

function deskNoteItem(desk: AgentDeskSnapshot | null): AgentDeskItemSnapshot | null {
  const notesPath = desk?.notes_path || 'desk-notes.md';
  return desk?.items?.find((item) => item.path === notesPath) || null;
}

export function useAgentDesk(agentId: string) {
  const [desk, setDesk] = useState<AgentDeskSnapshot | null>(null);
  const [noteDraft, setNoteDraft] = useState('');
  const [busyAction, setBusyAction] = useState<DeskBusyAction>('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');

  const noteItem = useMemo(() => deskNoteItem(desk), [desk]);

  const applyDesk = useCallback((nextDesk: AgentDeskSnapshot) => {
    setDesk(nextDesk);
    const nextNote = deskNoteItem(nextDesk);
    setNoteDraft(nextNote?.preview_text || '');
  }, []);

  const loadDesk = useCallback(async () => {
    if (!agentId) {
      setDesk(null);
      setNoteDraft('');
      setError('');
      setStatus('');
      return;
    }
    setBusyAction('load');
    setError('');
    try {
      applyDesk(await getYachiyoAgentDesk(agentId));
      setStatus('');
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取 Agent Desk 失败');
    } finally {
      setBusyAction('');
    }
  }, [agentId, applyDesk]);

  const saveNote = useCallback(async () => {
    if (!agentId) return;
    setBusyAction('note');
    setError('');
    try {
      applyDesk(await saveYachiyoAgentDeskNote(agentId, noteDraft));
      setStatus('Desk 便签已保存');
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存 Desk 便签失败');
    } finally {
      setBusyAction('');
    }
  }, [agentId, applyDesk, noteDraft]);

  const saveFile = useCallback(async (path: string, content: string) => {
    if (!agentId) return false;
    setBusyAction('file');
    setError('');
    try {
      applyDesk(await saveYachiyoAgentDeskFile(agentId, path, content));
      setStatus('Desk 文件已写入');
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : '写入 Desk 文件失败');
      return false;
    } finally {
      setBusyAction('');
    }
  }, [agentId, applyDesk]);

  useEffect(() => {
    void loadDesk();
  }, [loadDesk]);

  return {
    busyAction,
    desk,
    error,
    loading: busyAction === 'load',
    noteDraft,
    noteItem,
    savingFile: busyAction === 'file',
    savingNote: busyAction === 'note',
    status,
    loadDesk,
    saveFile,
    saveNote,
    setNoteDraft,
  };
}
