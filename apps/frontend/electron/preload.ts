import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('hermesDesktop', {
  chooseLive2DArchive: () => ipcRenderer.invoke('hermes:chooseLive2DArchive') as Promise<string | null>,
  chooseLive2DModelDirectory: () => ipcRenderer.invoke('hermes:chooseLive2DModelDirectory') as Promise<string | null>,
  copyText: (text: string) => ipcRenderer.invoke('hermes:copyText', text) as Promise<void>,
  getBridgeUrl: () => ipcRenderer.invoke('hermes:getBridgeUrl') as Promise<string>,
  moveLauncherWindow: (deltaX: number, deltaY: number) => ipcRenderer.invoke('hermes:moveLauncherWindow', deltaX, deltaY) as Promise<boolean>,
  openDesktopMode: (mode?: string) => ipcRenderer.invoke('hermes:openDesktopMode', mode) as Promise<void>,
  openExternalUrl: (url: string) => ipcRenderer.invoke('hermes:openExternalUrl', url) as Promise<void>,
  openLauncherMenu: (mode?: string) => ipcRenderer.invoke('hermes:openLauncherMenu', mode) as Promise<void>,
  openPath: (path: string) => ipcRenderer.invoke('hermes:openPath', path) as Promise<void>,
  openView: (view: string, params?: Record<string, string>) => ipcRenderer.invoke('hermes:openView', view, params) as Promise<void>,
  quit: () => ipcRenderer.invoke('hermes:quit') as Promise<void>,
  setLauncherPointerInteractive: (mode: string, interactive: boolean) => ipcRenderer.invoke('hermes:setLauncherPointerInteractive', mode, interactive) as Promise<boolean>,
});
