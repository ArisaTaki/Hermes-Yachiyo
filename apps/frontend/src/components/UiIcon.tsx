import type { ReactNode, SVGProps } from 'react';

export type UiIconName =
  | 'activity'
  | 'bubble'
  | 'chat'
  | 'check'
  | 'close'
  | 'copy'
  | 'dashboard'
  | 'diagnostics'
  | 'folder'
  | 'home'
  | 'image'
  | 'installer'
  | 'live2d'
  | 'model'
  | 'moon'
  | 'plus'
  | 'provider'
  | 'resources'
  | 'send'
  | 'settings'
  | 'sparkle'
  | 'stop'
  | 'voice'
  | 'workspace';

type UiIconProps = SVGProps<SVGSVGElement> & {
  name: UiIconName;
  title?: string;
};

export function UiIcon({ name, title, ...props }: UiIconProps) {
  return (
    <svg
      aria-hidden={title ? undefined : true}
      className={`ui-icon ${props.className || ''}`.trim()}
      fill="none"
      focusable="false"
      role={title ? 'img' : undefined}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
      viewBox="0 0 24 24"
      {...props}
    >
      {title ? <title>{title}</title> : null}
      {ICON_PATHS[name]}
    </svg>
  );
}

const ICON_PATHS: Record<UiIconName, ReactNode> = {
  activity: (
    <>
      <path d="M4 13h4l2-7 4 12 2-5h4" />
      <path d="M4 20h16" />
    </>
  ),
  bubble: (
    <>
      <path d="M7 8.5h7" />
      <path d="M7 12h5" />
      <path d="M12.5 18.5H7.8L4 21v-4.2A7 7 0 0 1 3 13V9.5A6.5 6.5 0 0 1 9.5 3h5A6.5 6.5 0 0 1 21 9.5v2.2" />
      <path d="M16 17.2c1.9.2 3.4-.8 4-2.2" />
    </>
  ),
  chat: (
    <>
      <path d="M5 5.8A4.8 4.8 0 0 1 9.8 1h4.4A4.8 4.8 0 0 1 19 5.8v4.4a4.8 4.8 0 0 1-4.8 4.8H10l-5 4v-5.1A4.8 4.8 0 0 1 5 10.2Z" />
      <path d="M9 7h6" />
      <path d="M9 10.5h4.5" />
    </>
  ),
  check: <path d="m5 12.5 4.2 4.2L19 7" />,
  close: (
    <>
      <path d="M7 7l10 10" />
      <path d="M17 7 7 17" />
    </>
  ),
  copy: (
    <>
      <rect x="8" y="8" width="11" height="11" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1" />
    </>
  ),
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="2" />
      <rect x="14" y="3" width="7" height="7" rx="2" />
      <rect x="3" y="14" width="7" height="7" rx="2" />
      <path d="M15 18h5" />
      <path d="M17.5 15.5v5" />
    </>
  ),
  diagnostics: (
    <>
      <circle cx="10.5" cy="10.5" r="6" />
      <path d="m15 15 4.5 4.5" />
      <path d="M8.2 10.4h4.6" />
      <path d="M10.5 8.1v4.6" />
    </>
  ),
  folder: (
    <>
      <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h4l2 2.2h7A2.5 2.5 0 0 1 21 9.7v6.8A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5Z" />
      <path d="M3 10h18" />
    </>
  ),
  home: (
    <>
      <path d="m4 11 8-7 8 7" />
      <path d="M6.5 10.5V20h11v-9.5" />
      <path d="M10 20v-5h4v5" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <circle cx="8" cy="9" r="1.5" />
      <path d="m4 17 5-5 3.2 3.2 2.2-2.2L20 18.5" />
    </>
  ),
  installer: (
    <>
      <path d="M12 3v10" />
      <path d="m8 9 4 4 4-4" />
      <rect x="4" y="16" width="16" height="4" rx="1.5" />
      <path d="M7 18h.1" />
    </>
  ),
  live2d: (
    <>
      <path d="M8 6.5 5.5 4" />
      <path d="M16 6.5 18.5 4" />
      <path d="M7 13c0-3.3 2.2-6 5-6s5 2.7 5 6-2.2 6-5 6-5-2.7-5-6Z" />
      <path d="M10 12h.1" />
      <path d="M14 12h.1" />
      <path d="M10.5 15c.9.6 2.1.6 3 0" />
    </>
  ),
  model: (
    <>
      <rect x="4" y="5" width="16" height="13" rx="2.5" />
      <path d="M8 5V3" />
      <path d="M16 5V3" />
      <path d="M8 10h.1" />
      <path d="M16 10h.1" />
      <path d="M9 14h6" />
      <path d="M12 18v3" />
    </>
  ),
  moon: (
    <>
      <path d="M18.5 14.4A7 7 0 0 1 9.6 5.5 7.7 7.7 0 1 0 18.5 14.4Z" />
      <path d="M17 4.5h2.2" />
      <path d="M18.1 3.4v2.2" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </>
  ),
  provider: (
    <>
      <path d="M7.5 12a4.5 4.5 0 0 1 4.5-4.5h2.5" />
      <path d="M16.5 7.5H19V5" />
      <path d="M16.5 12a4.5 4.5 0 0 1-4.5 4.5H9.5" />
      <path d="M7.5 16.5H5V19" />
      <circle cx="6" cy="6" r="2" />
      <circle cx="18" cy="18" r="2" />
    </>
  ),
  resources: (
    <>
      <path d="M4 5.5h16" />
      <path d="M4 11.5h16" />
      <path d="M4 17.5h16" />
      <path d="M7 3.5v16" />
      <path d="M17 3.5v16" />
    </>
  ),
  send: (
    <>
      <path d="M12 19V5" />
      <path d="m6.5 10.5 5.5-5.5 5.5 5.5" />
    </>
  ),
  settings: (
    <>
      <path d="M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6Z" />
      <path d="M18.2 9.2 20 7.9l-2-3.5-2.1.9a7.8 7.8 0 0 0-1.7-1L14 2h-4l-.3 2.3a7.8 7.8 0 0 0-1.7 1l-2.1-.9-2 3.5 1.9 1.3a7.4 7.4 0 0 0 0 1.7L3.9 12.2l2 3.5 2.1-.9c.5.4 1.1.8 1.7 1l.3 2.2h4l.3-2.2c.6-.2 1.2-.6 1.7-1l2.1.9 2-3.5-1.9-1.3a7.4 7.4 0 0 0 0-1.7Z" />
    </>
  ),
  sparkle: (
    <>
      <path d="M12 3l1.5 5.1L18 10l-4.5 1.9L12 17l-1.5-5.1L6 10l4.5-1.9Z" />
      <path d="M19 16l.7 2.2L22 19l-2.3.8L19 22l-.7-2.2L16 19l2.3-.8Z" />
    </>
  ),
  stop: <rect x="7" y="7" width="10" height="10" rx="1.5" />,
  voice: (
    <>
      <path d="M9 18V6l9-2v11" />
      <circle cx="6.5" cy="18" r="2.5" />
      <circle cx="15.5" cy="15" r="2.5" />
    </>
  ),
  workspace: (
    <>
      <rect x="4" y="5" width="16" height="14" rx="2.5" />
      <path d="M8 9h8" />
      <path d="M8 13h5" />
      <path d="M7 19v2" />
      <path d="M17 19v2" />
    </>
  ),
};
