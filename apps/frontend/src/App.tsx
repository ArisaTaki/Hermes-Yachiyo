import { Suspense, lazy, useEffect, useState, type ReactNode } from 'react';

import {
  ActivityAllPage,
  ActivityDetailPage,
  BubbleModePage,
  DashboardPage,
  Live2DModePage,
  OpenDesignShell,
  ResourcesPage,
  ToolsAllPage,
  WorkspacePage,
} from './views/OpenDesignView';
import { ROUTE_CHANGE_EVENT, currentParam, currentView } from './lib/view';

const ChatView = lazy(() => import('./views/ChatView').then((module) => ({ default: module.ChatView })));
const TasksView = lazy(() => import('./views/TasksView').then((module) => ({ default: module.TasksView })));
const AgentStudioView = lazy(() =>
  import('./views/AgentStudioView').then((module) => ({ default: module.AgentStudioView })),
);
const DiagnosticsView = lazy(() =>
  import('./views/DiagnosticsView').then((module) => ({ default: module.DiagnosticsView })),
);
const ModeSettingsView = lazy(() =>
  import('./views/ModeSettingsView').then((module) => ({ default: module.ModeSettingsView })),
);
const ModelProfilesView = lazy(() =>
  import('./views/ModelProfilesView').then((module) => ({ default: module.ModelProfilesView })),
);
const ProactiveTtsSettingsView = lazy(() =>
  import('./views/ProactiveTtsSettingsView').then((module) => ({ default: module.ProactiveTtsSettingsView })),
);
const ToolCenterView = lazy(() =>
  import('./views/ToolCenterView').then((module) => ({ default: module.ToolCenterView })),
);
const AppUpdateView = lazy(() =>
  import('./views/AppUpdateView').then((module) => ({ default: module.AppUpdateView })),
);
const LauncherView = lazy(() =>
  import('./views/LauncherView').then((module) => ({ default: module.LauncherView })),
);

function RouteLoadingFallback() {
  return (
    <div className="hy-route-page hy-route-loading" aria-live="polite">
      正在加载界面...
    </div>
  );
}

export function App() {
  const view = currentView();
  const [, setRouteVersion] = useState(0);
  const [live2dVisited, setLive2dVisited] = useState(() => view === 'live2d');

  useEffect(() => {
    const refreshRoute = () => setRouteVersion((version) => version + 1);
    window.addEventListener('hashchange', refreshRoute);
    window.addEventListener('popstate', refreshRoute);
    window.addEventListener(ROUTE_CHANGE_EVENT, refreshRoute);
    return () => {
      window.removeEventListener('hashchange', refreshRoute);
      window.removeEventListener('popstate', refreshRoute);
      window.removeEventListener(ROUTE_CHANGE_EVENT, refreshRoute);
    };
  }, []);

  useEffect(() => {
    if (view === 'live2d') setLive2dVisited(true);
  }, [view]);

  const surface = currentParam('surface');

  if (view === 'bubble-menu' || ((view === 'bubble' || view === 'live2d') && surface === 'desktop')) {
    return (
      <Suspense fallback={null}>
        <LauncherView view={view} />
      </Suspense>
    );
  }

  let page: ReactNode = <DashboardPage />;
  if (view === 'chat') page = <ChatView />;
  else if (view === 'tasks') page = <TasksView />;
  else if (view === 'agents') page = <AgentStudioView />;
  else if (view === 'settings') page = <ModeSettingsView />;
  else if (view === 'diagnostics') page = <DiagnosticsView />;
  else if (view === 'tools') page = <ToolCenterView />;
  else if (view === 'proactive-tts') page = <ProactiveTtsSettingsView />;
  else if (view === 'app-update') page = <AppUpdateView />;
  else if (view === 'provider') page = <ModelProfilesView />;
  else if (view === 'bubble') page = <BubbleModePage />;
  else if (view === 'live2d') page = null;
  else if (view === 'resources') page = <ResourcesPage />;
  else if (view === 'workspace') page = <WorkspacePage />;
  else if (view === 'tools-all') page = <ToolsAllPage />;
  else if (view === 'activity-all') page = <ActivityAllPage />;
  else if (view === 'activity-detail') page = <ActivityDetailPage />;

  const shouldMountLive2d = live2dVisited || view === 'live2d';

  return (
    <OpenDesignShell activeView={view}>
      {view !== 'live2d' ? (
        <Suspense fallback={<RouteLoadingFallback />}>{page}</Suspense>
      ) : null}
      {shouldMountLive2d ? (
        <Suspense fallback={view === 'live2d' ? <RouteLoadingFallback /> : null}>
          <div
            className={view === 'live2d' ? 'hy-keepalive-page' : 'hy-keepalive-page is-hidden'}
            aria-hidden={view !== 'live2d'}
          >
            <Live2DModePage active={view === 'live2d'} />
          </div>
        </Suspense>
      ) : null}
    </OpenDesignShell>
  );
}
