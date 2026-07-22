import type { ReactNode } from 'react';

type SettingsDisclosureProps = {
  summary: string;
  description?: string;
  testId?: string;
  children: ReactNode;
};

export function SettingsDisclosure({
  summary,
  description,
  testId,
  children,
}: SettingsDisclosureProps) {
  return (
    <details className="settings-disclosure" data-testid={testId}>
      <summary className="settings-item settings-disclosure-summary">
        <span className="settings-item-info">
          <span className="settings-item-label">{summary}</span>
          {description ? <span className="settings-item-desc">{description}</span> : null}
        </span>
      </summary>
      <div className="settings-disclosure-content">{children}</div>
    </details>
  );
}
