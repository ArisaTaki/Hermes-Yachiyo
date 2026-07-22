import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

type ConfirmDialogVariant = 'default' | 'danger';

const EXIT_DURATION_MS = 180;
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(',');
let modalInertCount = 0;
let appRootWasInitiallyInert = false;

function acquireAppRootInert() {
  const appRoot = document.getElementById('root');
  if (!appRoot) return () => undefined;
  if (modalInertCount === 0) {
    appRootWasInitiallyInert = appRoot.hasAttribute('inert');
    if (!appRootWasInitiallyInert) appRoot.setAttribute('inert', '');
  }
  modalInertCount += 1;
  return () => {
    modalInertCount = Math.max(0, modalInertCount - 1);
    if (modalInertCount === 0 && !appRootWasInitiallyInert) appRoot.removeAttribute('inert');
  };
}

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

type ConfirmDialogContent = {
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  variant: ConfirmDialogVariant;
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
  const [isPresent, setIsPresent] = useState(open);
  const titleId = useId();
  const dialogRef = useRef<HTMLElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const lastOpenContentRef = useRef<ConfirmDialogContent>({
    title,
    description,
    confirmLabel,
    cancelLabel,
    variant,
  });

  useEffect(() => {
    if (open) {
      setIsPresent(true);
      return undefined;
    }
    if (!isPresent) return undefined;

    const exitDuration = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? 0
      : EXIT_DURATION_MS;
    const timeoutId = window.setTimeout(() => setIsPresent(false), exitDuration);
    return () => window.clearTimeout(timeoutId);
  }, [isPresent, open]);

  useEffect(() => {
    if (!open) return;
    lastOpenContentRef.current = {
      title,
      description,
      confirmLabel,
      cancelLabel,
      variant,
    };
  }, [cancelLabel, confirmLabel, description, open, title, variant]);

  useEffect(() => {
    if (!isPresent || typeof document === 'undefined') return undefined;
    const activeElement = document.activeElement;
    const releaseAppRootInert = acquireAppRootInert();
    restoreFocusRef.current = activeElement instanceof HTMLElement ? activeElement : null;

    return () => {
      releaseAppRootInert();
      const elementToRestore = restoreFocusRef.current;
      restoreFocusRef.current = null;
      if (elementToRestore?.isConnected) elementToRestore.focus({ preventScroll: true });
    };
  }, [isPresent]);

  useEffect(() => {
    if (open && isPresent) cancelButtonRef.current?.focus({ preventScroll: true });
  }, [isPresent, open]);

  const handleCancel = useCallback(() => {
    if (open) onCancel();
  }, [onCancel, open]);

  const handleConfirm = useCallback(() => {
    if (open) onConfirm();
  }, [onConfirm, open]);

  useEffect(() => {
    if (!isPresent) return undefined;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        handleCancel();
        return;
      }
      if (event.key !== 'Tab') return;

      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusableElements = Array.from(
        dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((element) => element.tabIndex >= 0);
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      if (!firstElement || !lastElement) return;

      const activeElement = document.activeElement;
      if (event.shiftKey && (activeElement === firstElement || !dialog.contains(activeElement))) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && (activeElement === lastElement || !dialog.contains(activeElement))) {
        event.preventDefault();
        firstElement.focus();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleCancel, isPresent, open]);

  if (!isPresent || typeof document === 'undefined') return null;

  const content = open
    ? { title, description, confirmLabel, cancelLabel, variant }
    : lastOpenContentRef.current;

  return createPortal(
    <div
      className={`hy-confirm-backdrop ${open ? 'is-open' : 'is-closing'}`}
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) handleCancel();
      }}
    >
      <section ref={dialogRef} className={`hy-confirm-dialog ${content.variant}`} data-testid="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="hy-confirm-copy">
          <h2 id={titleId}>{content.title}</h2>
          {content.description ? <div className="hy-confirm-description">{content.description}</div> : null}
        </div>
        <div className="hy-confirm-actions">
          <button ref={cancelButtonRef} type="button" onClick={handleCancel}>{content.cancelLabel}</button>
          <button type="button" className={content.variant === 'danger' ? 'danger-action' : 'primary-action'} data-testid="confirm-action" onClick={handleConfirm}>
            {content.confirmLabel}
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
