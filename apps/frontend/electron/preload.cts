import { contextBridge, ipcRenderer } from 'electron';

type TerminalDataPayload = { id: string; data: string };
type TerminalExitPayload = { id: string; exitCode: number; signal?: number; task?: string };
type AppUpdateDownloadProgress = {
  status: string;
  file_name?: string;
  received_bytes?: number;
  total_bytes?: number;
  percent?: number;
  error?: string;
};
type AvatarImageSelection = { path?: string; data_url?: string; file_name?: string };

contextBridge.exposeInMainWorld('ohaDesktop', {
  chooseAvatarImage: () => ipcRenderer.invoke('oha:chooseAvatarImage') as Promise<AvatarImageSelection | null>,
  chooseLive2DArchive: () => ipcRenderer.invoke('oha:chooseLive2DArchive') as Promise<string | null>,
  chooseLive2DModelDirectory: () => ipcRenderer.invoke('oha:chooseLive2DModelDirectory') as Promise<string | null>,
  chooseTtsVoiceArchive: () => ipcRenderer.invoke('oha:chooseTtsVoiceArchive') as Promise<string | null>,
  chooseSkillSources: () => ipcRenderer.invoke('oha:chooseSkillSources') as Promise<string[]>,
  copyText: (text: string) => ipcRenderer.invoke('oha:copyText', text) as Promise<void>,
  cancelAppUpdateDownload: () => ipcRenderer.invoke('oha:cancelAppUpdateDownload') as Promise<unknown>,
  checkAppUpdate: () => ipcRenderer.invoke('oha:checkAppUpdate') as Promise<unknown>,
  downloadAppUpdate: () => ipcRenderer.invoke('oha:downloadAppUpdate') as Promise<unknown>,
  getAppUpdateInfo: () => ipcRenderer.invoke('oha:getAppUpdateInfo') as Promise<unknown>,
  getBridgeUrl: () => ipcRenderer.invoke('oha:getBridgeUrl') as Promise<string>,
  getBridgeToken: () => ipcRenderer.invoke('oha:getBridgeToken') as Promise<string>,
  getLauncherPointerState: (mode: string) => ipcRenderer.invoke('oha:getLauncherPointerState', mode) as Promise<{ ok?: boolean; x?: number; y?: number; width?: number; height?: number; inside?: boolean; updated_at?: number }>,
  moveLauncherWindow: (deltaX: number, deltaY: number) => ipcRenderer.invoke('oha:moveLauncherWindow', deltaX, deltaY) as Promise<boolean>,
  openDesktopMode: (mode?: string) => ipcRenderer.invoke('oha:openDesktopMode', mode) as Promise<void>,
  openExternalUrl: (url: string) => ipcRenderer.invoke('oha:openExternalUrl', url) as Promise<void>,
  openLauncherMenu: (mode?: string) => ipcRenderer.invoke('oha:openLauncherMenu', mode) as Promise<void>,
  openPath: (path: string) => ipcRenderer.invoke('oha:openPath', path) as Promise<void>,
  openView: (view: string, params?: Record<string, string>) => ipcRenderer.invoke('oha:openView', view, params) as Promise<void>,
  quit: () => ipcRenderer.invoke('oha:quit') as Promise<void>,
  removeAppBundleAndQuit: () => ipcRenderer.invoke('oha:removeAppBundleAndQuit') as Promise<{ success?: boolean; appBundlePath?: string; error?: string }>,
  restartApp: () => ipcRenderer.invoke('oha:restartApp') as Promise<void>,
  installAppUpdate: (dmgPath?: string) => ipcRenderer.invoke('oha:installAppUpdate', dmgPath) as Promise<unknown>,
  restartBackend: (options?: { bridgeUrl?: string }) => ipcRenderer.invoke('oha:restartBackend', options) as Promise<{ success?: boolean; bridgeUrl?: string; error?: string }>,
  setLauncherHitRegions: (mode: string, payload: unknown) => ipcRenderer.invoke('oha:setLauncherHitRegions', mode, payload) as Promise<boolean>,
  setLauncherPointerInteractive: (mode: string, interactive: boolean) => ipcRenderer.invoke('oha:setLauncherPointerInteractive', mode, interactive) as Promise<boolean>,
  terminalKill: (id: string) => ipcRenderer.invoke('oha:terminalKill', id) as Promise<boolean>,
  terminalResize: (id: string, cols: number, rows: number) => ipcRenderer.invoke('oha:terminalResize', id, cols, rows) as Promise<boolean>,
  terminalStart: (task: string, cols: number, rows: number) => ipcRenderer.invoke('oha:terminalStart', task, cols, rows) as Promise<{ success?: boolean; id?: string; task?: string; title?: string; error?: string }>,
  terminalWrite: (id: string, data: string) => ipcRenderer.invoke('oha:terminalWrite', id, data) as Promise<boolean>,
  onTerminalData: (callback: (payload: TerminalDataPayload) => void) => {
    const listener = (_event: unknown, payload: TerminalDataPayload) => callback(payload);
    ipcRenderer.on('oha:terminalData', listener);
    return () => ipcRenderer.removeListener('oha:terminalData', listener);
  },
  onTerminalExit: (callback: (payload: TerminalExitPayload) => void) => {
    const listener = (_event: unknown, payload: TerminalExitPayload) => callback(payload);
    ipcRenderer.on('oha:terminalExit', listener);
    return () => ipcRenderer.removeListener('oha:terminalExit', listener);
  },
  onAppUpdateDownloadProgress: (callback: (payload: AppUpdateDownloadProgress) => void) => {
    const listener = (_event: unknown, payload: AppUpdateDownloadProgress) => callback(payload);
    ipcRenderer.on('oha:appUpdateDownloadProgress', listener);
    return () => ipcRenderer.removeListener('oha:appUpdateDownloadProgress', listener);
  },
});
