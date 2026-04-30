import { useEffect, useState } from 'react';

import { ChatView } from './views/ChatView';
import { DiagnosticsView } from './views/DiagnosticsView';
import { InstallerView } from './views/InstallerView';
import { LauncherView } from './views/LauncherView';
import { MainView } from './views/MainView';
import { ModeSettingsView } from './views/ModeSettingsView';
import { ROUTE_CHANGE_EVENT, currentView } from './lib/view';

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

  if (view === 'chat') return <ChatView />;
  if (view === 'settings') return <ModeSettingsView />;
  if (view === 'installer') return <InstallerView />;
  if (view === 'diagnostics') return <DiagnosticsView />;
  if (view === 'bubble' || view === 'bubble-menu' || view === 'live2d') return <LauncherView view={view} />;
  return <MainView />;
}
