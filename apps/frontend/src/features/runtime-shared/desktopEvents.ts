export type RuntimeDesktopIntentSuffix =
  | 'planned'
  | 'approval_required'
  | 'completed'
  | 'unavailable';

export type RuntimeDesktopProviderSessionSuffix =
  | 'required'
  | 'started'
  | 'ready'
  | 'failed';

const RUNTIME_DESKTOP_EVENT_SCOPES = [
  'agent.desktop',
  'group.run.desktop',
  'workflow.desktop',
  'workflow.run.desktop',
];
const RUNTIME_DESKTOP_PROVIDER_SESSION_SCOPE = 'desktop.provider_session';

export function runtimeEventIsDesktopIntent(
  eventType: string,
  suffix: RuntimeDesktopIntentSuffix,
): boolean {
  return runtimeEventIsDesktopEvent(eventType, `intent_${suffix}`);
}

export function runtimeEventIsDesktopPermissionRecovery(eventType: string): boolean {
  return runtimeEventIsDesktopEvent(eventType, 'permission_recovery');
}

export function runtimeEventIsDesktopReadinessRecovered(eventType: string): boolean {
  return runtimeEventIsDesktopEvent(eventType, 'readiness_recovered');
}

export function runtimeEventIsDesktopProviderSessionEvent(
  eventType: string,
  suffix?: RuntimeDesktopProviderSessionSuffix,
): boolean {
  const type = String(eventType || '').trim();
  if (!suffix) return type.startsWith(`${RUNTIME_DESKTOP_PROVIDER_SESSION_SCOPE}.`);
  return type === `${RUNTIME_DESKTOP_PROVIDER_SESSION_SCOPE}.${suffix}`;
}

export function runtimeEventIsDailyDesktopToolEvent(eventType: string): boolean {
  return runtimeEventIsDesktopPermissionRecovery(eventType)
    || runtimeEventIsDesktopIntent(eventType, 'approval_required')
    || runtimeEventIsDesktopIntent(eventType, 'completed')
    || runtimeEventIsDesktopIntent(eventType, 'unavailable');
}

function runtimeEventIsDesktopEvent(eventType: string, eventName: string): boolean {
  const type = String(eventType || '').trim();
  return RUNTIME_DESKTOP_EVENT_SCOPES.some((scope) => type === `${scope}.${eventName}`);
}
