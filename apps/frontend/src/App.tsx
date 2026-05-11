import { useEffect, useState } from 'react';

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
  const [, setRouteVersion] = useState(0);

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

  const view = currentView();
  const surface = currentParam('surface');

  if (view === 'bubble-menu' || ((view === 'bubble' || view === 'live2d') && surface === 'desktop')) {
    return <LauncherView view={view} />;
  }

  let page = <DashboardPage />;
  if (view === 'chat') page = <ChatView />;
  else if (view === 'settings') page = <ModeSettingsView />;
  else if (view === 'installer') page = <InstallerView />;
  else if (view === 'diagnostics') page = <DiagnosticsView />;
  else if (view === 'tools') page = currentParam('tool') ? <ToolCenterView /> : <DiagnosticsView />;
  else if (view === 'proactive-tts') page = <ProactiveTtsSettingsView />;
  else if (view === 'app-update') page = <AppUpdateView />;
  else if (view === 'provider') page = <ProviderPage />;
  else if (view === 'bubble') page = <BubbleModePage />;
  else if (view === 'live2d') page = <Live2DModePage />;
  else if (view === 'resources') page = <ResourcesPage />;
  else if (view === 'workspace') page = <WorkspacePage />;
  else if (view === 'tools-all') page = <ToolsAllPage />;
  else if (view === 'activity-all') page = <ActivityAllPage />;

  return <OpenDesignShell activeView={view}>{page}</OpenDesignShell>;
}
