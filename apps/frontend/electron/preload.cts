import { contextBridge, ipcRenderer } from 'electron';

type TerminalDataPayload = { id: string; data: string };
type TerminalExitPayload = { id: string; exitCode: number; signal?: number; task?: string };

contextBridge.exposeInMainWorld('hermesDesktop', {
  chooseLive2DArchive: () => ipcRenderer.invoke('hermes:chooseLive2DArchive') as Promise<string | null>,
  chooseLive2DModelDirectory: () => ipcRenderer.invoke('hermes:chooseLive2DModelDirectory') as Promise<string | null>,
  copyText: (text: string) => ipcRenderer.invoke('hermes:copyText', text) as Promise<void>,
  getBridgeUrl: () => ipcRenderer.invoke('hermes:getBridgeUrl') as Promise<string>,
  getLauncherPointerState: (mode: string) => ipcRenderer.invoke('hermes:getLauncherPointerState', mode) as Promise<{ ok?: boolean; x?: number; y?: number; width?: number; height?: number; inside?: boolean; updated_at?: number }>,
  moveLauncherWindow: (deltaX: number, deltaY: number) => ipcRenderer.invoke('hermes:moveLauncherWindow', deltaX, deltaY) as Promise<boolean>,
  openDesktopMode: (mode?: string) => ipcRenderer.invoke('hermes:openDesktopMode', mode) as Promise<void>,
  openExternalUrl: (url: string) => ipcRenderer.invoke('hermes:openExternalUrl', url) as Promise<void>,
  openLauncherMenu: (mode?: string) => ipcRenderer.invoke('hermes:openLauncherMenu', mode) as Promise<void>,
  openPath: (path: string) => ipcRenderer.invoke('hermes:openPath', path) as Promise<void>,
  openView: (view: string, params?: Record<string, string>) => ipcRenderer.invoke('hermes:openView', view, params) as Promise<void>,
  quit: () => ipcRenderer.invoke('hermes:quit') as Promise<void>,
  removeAppBundleAndQuit: () => ipcRenderer.invoke('hermes:removeAppBundleAndQuit') as Promise<{ success?: boolean; appBundlePath?: string; error?: string }>,
  restartApp: () => ipcRenderer.invoke('hermes:restartApp') as Promise<void>,
  restartBackend: (options?: { bridgeUrl?: string }) => ipcRenderer.invoke('hermes:restartBackend', options) as Promise<{ success?: boolean; bridgeUrl?: string; error?: string }>,
  setLauncherHitRegions: (mode: string, payload: unknown) => ipcRenderer.invoke('hermes:setLauncherHitRegions', mode, payload) as Promise<boolean>,
  setLauncherPointerInteractive: (mode: string, interactive: boolean) => ipcRenderer.invoke('hermes:setLauncherPointerInteractive', mode, interactive) as Promise<boolean>,
  terminalKill: (id: string) => ipcRenderer.invoke('hermes:terminalKill', id) as Promise<boolean>,
  terminalResize: (id: string, cols: number, rows: number) => ipcRenderer.invoke('hermes:terminalResize', id, cols, rows) as Promise<boolean>,
  terminalStart: (task: string, cols: number, rows: number) => ipcRenderer.invoke('hermes:terminalStart', task, cols, rows) as Promise<{ success?: boolean; id?: string; task?: string; title?: string; error?: string }>,
  terminalWrite: (id: string, data: string) => ipcRenderer.invoke('hermes:terminalWrite', id, data) as Promise<boolean>,
  onTerminalData: (callback: (payload: TerminalDataPayload) => void) => {
    const listener = (_event: unknown, payload: TerminalDataPayload) => callback(payload);
    ipcRenderer.on('hermes:terminalData', listener);
    return () => ipcRenderer.removeListener('hermes:terminalData', listener);
  },
  onTerminalExit: (callback: (payload: TerminalExitPayload) => void) => {
    const listener = (_event: unknown, payload: TerminalExitPayload) => callback(payload);
    ipcRenderer.on('hermes:terminalExit', listener);
    return () => ipcRenderer.removeListener('hermes:terminalExit', listener);
  },
});
