export type AppView =
  | 'main'
  | 'chat'
  | 'agents'
  | 'settings'
  | 'installer'
  | 'provider'
  | 'resources'
  | 'workspace'
  | 'diagnostics'
  | 'tools'
  | 'tools-all'
  | 'activity-all'
  | 'activity-detail'
  | 'app-update'
  | 'proactive-tts'
  | 'bubble'
  | 'bubble-menu'
  | 'live2d';

type RouteState = {
  view: AppView;
  params: Record<string, string>;
};

declare global {
  interface Window {
    hermesRouteLeaveGuard?: (nextView: AppView) => boolean;
  }
}

export const ROUTE_CHANGE_EVENT = 'hermes-route-change';

export function currentView(): AppView {
  return currentRoute().view;
}

export function currentParam(name: string): string {
  return currentRoute().params[name] || new URLSearchParams(window.location.search).get(name) || '';
}

export function currentRoute(): RouteState {
  const hashRoute = routeFromHash(window.location.hash);
  if (hashRoute) return hashRoute;

  const params = new URLSearchParams(window.location.search);
  const view = params.get('view') || 'main';
  return {
    view: isAppView(view) ? view : 'main',
    params: Object.fromEntries(params.entries()),
  };
}

export function navigateTo(
  view: AppView,
  extraParams: Record<string, string> = {},
  removeParams: string[] = [],
) {
  if (window.hermesRouteLeaveGuard && !window.hermesRouteLeaveGuard(view)) return;
  const current = currentRoute().params;
  const nextParams = { ...current };
  removeParams.forEach((name) => delete nextParams[name]);
  Object.entries(extraParams).forEach(([key, value]) => {
    if (value) nextParams[key] = value;
    else delete nextParams[key];
  });
  const route = routePath(view, nextParams);
  if (window.location.hash === route) return;
  window.history.pushState(null, '', route);
  window.dispatchEvent(new Event(ROUTE_CHANGE_EVENT));
}

export function routePath(view: AppView, params: Record<string, string> = {}): string {
  if (view === 'main') return '#/';
  if (view === 'settings' && params.mode) return `#/settings/${encodeURIComponent(params.mode)}`;
  if (view === 'tools' && params.tool) return `#/tools/${encodeURIComponent(params.tool)}`;
  if (view === 'agents' && params.run) return `#/agents/${encodeURIComponent(params.run)}`;
  if (view === 'provider' && params.capability) return `#/provider/${encodeURIComponent(params.capability)}`;
  if (view === 'activity-detail' && params.event_id) return `#/activity-detail/${encodeURIComponent(params.event_id)}`;
  return `#/${encodeURIComponent(view)}`;
}

function isAppView(value: string): value is AppView {
  return [
    'main',
    'chat',
    'agents',
    'settings',
    'installer',
    'provider',
    'resources',
    'workspace',
    'diagnostics',
    'tools',
    'tools-all',
    'activity-all',
    'activity-detail',
    'app-update',
    'proactive-tts',
    'bubble',
    'bubble-menu',
    'live2d',
  ].includes(value);
}

function routeFromHash(hash: string): RouteState | null {
  if (!hash || !hash.startsWith('#/')) return null;
  const parts = hash.slice(2).split('/').filter(Boolean).map((part) => decodeURIComponent(part));
  if (!parts.length) return { view: 'main', params: {} };
  const [rawView, rawMode] = parts;
  if (!isAppView(rawView)) return { view: 'main', params: {} };
  if (rawView === 'settings' && rawMode) return { view: 'settings', params: { mode: rawMode } };
  if (rawView === 'tools' && rawMode) return { view: 'tools', params: { tool: rawMode } };
  if (rawView === 'agents' && rawMode) return { view: 'agents', params: { run: rawMode } };
  if (rawView === 'provider' && rawMode) return { view: 'provider', params: { capability: rawMode } };
  if (rawView === 'activity-detail' && rawMode) return { view: 'activity-detail', params: { event_id: rawMode } };
  return { view: rawView, params: {} };
}
