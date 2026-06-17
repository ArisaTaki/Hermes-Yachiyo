import type { ReactNode } from 'react';

import { ConfirmDialog } from '../../../components/ConfirmDialog';
import type { AgentStudioConfirmDialogState } from '../hooks/useAgentStudioConfirmDialog';
import type { StudioTab } from '../studioTabs';
import { AgentStudioChrome } from './AgentStudioChrome';

type AgentStudioPageFrameProps = {
  children: ReactNode;
  confirmDialog: AgentStudioConfirmDialogState | null;
  error: string;
  loading: boolean;
  status: string;
  tab: StudioTab;
  onActivateTab: (tab: StudioTab) => void;
  onBack: () => void;
  onCancelConfirmDialog: () => void;
  onConfirmCurrentDialog: () => void;
};

export function AgentStudioPageFrame({
  children,
  confirmDialog,
  error,
  loading,
  status,
  tab,
  onActivateTab,
  onBack,
  onCancelConfirmDialog,
  onConfirmCurrentDialog,
}: AgentStudioPageFrameProps) {
  return (
    <section className="agent-studio-page hy-route-page">
      <AgentStudioChrome
        error={error}
        loading={loading}
        status={status}
        tab={tab}
        onActivateTab={onActivateTab}
        onBack={onBack}
      />

      {children}

      <ConfirmDialog
        confirmLabel={confirmDialog?.confirmLabel}
        description={confirmDialog?.description}
        onCancel={onCancelConfirmDialog}
        onConfirm={onConfirmCurrentDialog}
        open={Boolean(confirmDialog)}
        title={confirmDialog?.title || ''}
        variant={confirmDialog?.variant}
      />
    </section>
  );
}
