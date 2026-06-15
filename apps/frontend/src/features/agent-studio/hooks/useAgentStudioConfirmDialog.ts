import { useCallback, useState } from 'react';

export type AgentStudioConfirmDialogState = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

export function useAgentStudioConfirmDialog() {
  const [confirmDialog, setConfirmDialog] = useState<AgentStudioConfirmDialogState | null>(null);

  const showConfirmDialog = useCallback((nextConfirm: AgentStudioConfirmDialogState) => {
    setConfirmDialog(nextConfirm);
  }, []);

  const closeConfirmDialog = useCallback(() => {
    setConfirmDialog(null);
  }, []);

  const confirmCurrentDialog = useCallback(() => {
    const action = confirmDialog?.onConfirm;
    setConfirmDialog(null);
    if (action) action();
  }, [confirmDialog]);

  return {
    closeConfirmDialog,
    confirmCurrentDialog,
    confirmDialog,
    showConfirmDialog,
  };
}
