import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

type ConfirmDialogVariant = 'default' | 'danger';

export type ConfirmDialogRequest = {
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: ConfirmDialogVariant;
  onConfirm: () => void;
};

type ConfirmDialogProps = ConfirmDialogRequest & {
  open: boolean;
  onCancel: () => void;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = '确认',
  cancelLabel = '取消',
  variant = 'default',
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  useEffect(() => {
    if (!open) return undefined;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel();
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onCancel, open]);

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="hy-confirm-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <section className={`hy-confirm-dialog ${variant}`} role="dialog" aria-modal="true" aria-labelledby="hy-confirm-title">
        <div className="hy-confirm-copy">
          <h2 id="hy-confirm-title">{title}</h2>
          {description ? <div className="hy-confirm-description">{description}</div> : null}
        </div>
        <div className="hy-confirm-actions">
          <button type="button" onClick={onCancel}>{cancelLabel}</button>
          <button type="button" className={variant === 'danger' ? 'danger-action' : 'primary-action'} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

export function useConfirmDialog() {
  const [request, setRequest] = useState<ConfirmDialogRequest | null>(null);

  const requestConfirm = useCallback((nextRequest: ConfirmDialogRequest) => {
    setRequest(nextRequest);
  }, []);

  const closeConfirmDialog = useCallback(() => {
    setRequest(null);
  }, []);

  const confirmCurrentDialog = useCallback(() => {
    const action = request?.onConfirm;
    setRequest(null);
    if (action) action();
  }, [request]);

  const confirmDialog = (
    <ConfirmDialog
      confirmLabel={request?.confirmLabel}
      cancelLabel={request?.cancelLabel}
      description={request?.description}
      onCancel={closeConfirmDialog}
      onConfirm={confirmCurrentDialog}
      open={Boolean(request)}
      title={request?.title || ''}
      variant={request?.variant}
    />
  );

  return { confirmDialog, requestConfirm, closeConfirmDialog };
}
