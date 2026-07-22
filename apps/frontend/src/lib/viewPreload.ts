import type { AppView } from './view';

type ViewLoader = () => Promise<unknown>;

const loadAgentStudio: ViewLoader = () => import('../views/AgentStudioView');
const viewLoaders: Partial<Record<AppView, ViewLoader>> = {
  'app-update': () => import('../views/AppUpdateView'),
  agents: loadAgentStudio,
  chat: () => import('../views/ChatView'),
  diagnostics: () => import('../views/DiagnosticsView'),
  memories: loadAgentStudio,
  provider: () => import('../views/ModelProfilesView'),
  'proactive-tts': () => import('../views/ProactiveTtsSettingsView'),
  settings: () => import('../views/ModeSettingsView'),
  skills: loadAgentStudio,
  tasks: () => import('../views/TasksView'),
  tools: () => import('../views/ToolCenterView'),
};

const preloadRequests = new Map<ViewLoader, Promise<void>>();

export function preloadView(view: AppView): Promise<void> {
  const loader = viewLoaders[view];
  if (!loader) return Promise.resolve();
  const pending = preloadRequests.get(loader);
  if (pending) return pending;

  const request = loader()
    .then(() => undefined)
    .catch(() => {
      preloadRequests.delete(loader);
    });
  preloadRequests.set(loader, request);
  return request;
}
