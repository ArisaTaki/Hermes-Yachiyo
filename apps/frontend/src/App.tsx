import { useEffect, useState, type ReactNode } from 'react';

import { ChatView } from './views/ChatView';
import { DiagnosticsView } from './views/DiagnosticsView';
import { InstallerView } from './views/InstallerView';
import { LauncherView } from './views/LauncherView';
import { ModeSettingsView } from './views/ModeSettingsView';
import {
  ActivityAllPage,
  BubbleModePage,
  DashboardPage,
  Live2DModePage,
  OpenDesignShell,
  ProviderPage,
  ResourcesPage,
  ToolsAllPage,
  WorkspacePage,
} from './views/OpenDesignView';
import { ProactiveTtsSettingsView } from './views/ProactiveTtsSettingsView';
import { ToolCenterView } from './views/ToolCenterView';
import { AppUpdateView } from './views/AppUpdateView';
import { ROUTE_CHANGE_EVENT, currentParam, currentView } from './lib/view';

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
    return <LauncherView view={view} />;
  }

  let page: ReactNode = <DashboardPage />;
  if (view === 'chat') page = <ChatView />;
  else if (view === 'settings') page = <ModeSettingsView />;
  else if (view === 'installer') page = <InstallerView />;
  else if (view === 'diagnostics') page = <DiagnosticsView />;
  else if (view === 'tools') page = currentParam('tool') ? <ToolCenterView /> : <DiagnosticsView />;
  else if (view === 'proactive-tts') page = <ProactiveTtsSettingsView />;
  else if (view === 'app-update') page = <AppUpdateView />;
  else if (view === 'provider') page = <ProviderPage />;
  else if (view === 'bubble') page = <BubbleModePage />;
  else if (view === 'live2d') page = null;
  else if (view === 'resources') page = <ResourcesPage />;
  else if (view === 'workspace') page = <WorkspacePage />;
  else if (view === 'tools-all') page = <ToolsAllPage />;
  else if (view === 'activity-all') page = <ActivityAllPage />;

  const live2dKeepAlive = live2dVisited ? (
    <div
      key="live2d-keepalive"
      className={view === 'live2d' ? 'hy-keepalive-page' : 'hy-keepalive-page is-hidden'}
      aria-hidden={view !== 'live2d'}
    >
      <Live2DModePage active={view === 'live2d'} />
    </div>
  ) : null;

  return (
    <OpenDesignShell activeView={view}>
      {view === 'live2d' ? live2dKeepAlive : page}
      {view !== 'live2d' ? live2dKeepAlive : null}
    </OpenDesignShell>
  );
}
