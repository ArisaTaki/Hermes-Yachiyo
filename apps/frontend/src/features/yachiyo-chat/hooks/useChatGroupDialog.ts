import { useState } from 'react';

import type { ChatSessionContext } from '../types';

export type ChatGroupDialogMode = 'create' | 'edit';

type OpenChatGroupSettingsOptions = {
  activeSessionContext: ChatSessionContext;
  currentSessionId: string;
  currentTitle: string;
};

export function useChatGroupDialog() {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<ChatGroupDialogMode>('create');
  const [error, setError] = useState('');
  const [name, setName] = useState('');
  const [avatarUrl, setAvatarUrl] = useState('');
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [isCreating, setIsCreating] = useState(false);

  function toggleAgent(agentId: string) {
    setError('');
    setSelectedAgentIds((current) => (
      current.includes(agentId)
        ? current.filter((item) => item !== agentId)
        : [...current, agentId]
    ));
  }

  function openCreate() {
    setMode('create');
    setOpen(true);
    setError('');
    setName('');
    setAvatarUrl('');
    setSelectedAgentIds([]);
  }

  function openEdit({
    activeSessionContext,
    currentSessionId,
    currentTitle,
  }: OpenChatGroupSettingsOptions) {
    if (!currentSessionId || activeSessionContext.conversation_kind !== 'group') return;
    const currentAgentIds = (activeSessionContext.participants || [])
      .filter((participant) => participant.kind === 'agent' && participant.id)
      .map((participant) => String(participant.id));
    setMode('edit');
    setOpen(true);
    setError('');
    setName(activeSessionContext.runnable_name || currentTitle || '');
    setAvatarUrl(activeSessionContext.avatar_url || '');
    setSelectedAgentIds(currentAgentIds);
  }

  function close() {
    setOpen(false);
    setError('');
  }

  function changeName(value: string) {
    setError('');
    setName(value);
  }

  function changeAvatarUrl(value: string) {
    setError('');
    setAvatarUrl(value);
  }

  function reportAvatarError(message: string) {
    setError(message);
  }

  function resetAfterCreate() {
    setOpen(false);
    setName('');
    setAvatarUrl('');
    setSelectedAgentIds([]);
  }

  return {
    avatarUrl,
    changeAvatarUrl,
    changeName,
    close,
    error,
    isCreating,
    mode,
    name,
    open,
    openCreate,
    openEdit,
    reportAvatarError,
    resetAfterCreate,
    selectedAgentIds,
    setError,
    setIsCreating,
    toggleAgent,
  };
}
