export const SCROLL_BOTTOM_THRESHOLD = 14;
export const CHAT_SIDEBAR_MIN_WIDTH = 220;
export const CHAT_SIDEBAR_BASE_MAX_WIDTH = 280;
export const CHAT_SIDEBAR_WIDE_MAX_WIDTH = 360;
export const CHAT_WIDE_VIEWPORT_WIDTH = 1500;

export function isMessageTextSelectionActive(root: HTMLElement | null) {
  if (typeof window === 'undefined') return false;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return false;
  return selectionNodeInMessageContent(selection.anchorNode, root)
    || selectionNodeInMessageContent(selection.focusNode, root);
}

export function isNearBottom(container: HTMLDivElement) {
  return container.scrollHeight - container.scrollTop - container.clientHeight <= SCROLL_BOTTOM_THRESHOLD;
}

export function responsiveChatSidebarMaxWidth() {
  if (typeof window === 'undefined') return CHAT_SIDEBAR_BASE_MAX_WIDTH;
  return window.innerWidth >= CHAT_WIDE_VIEWPORT_WIDTH
    ? CHAT_SIDEBAR_WIDE_MAX_WIDTH
    : CHAT_SIDEBAR_BASE_MAX_WIDTH;
}

export function clampChatSidebarWidth(value: number, maxWidth = responsiveChatSidebarMaxWidth()) {
  return Math.min(Math.max(value, CHAT_SIDEBAR_MIN_WIDTH), maxWidth);
}

function selectionNodeInMessageContent(node: Node | null, root: HTMLElement | null) {
  if (!node || !root) return false;
  const element = node instanceof Element ? node : node.parentElement;
  return Boolean(element && root.contains(element) && element.closest('.message-content'));
}
