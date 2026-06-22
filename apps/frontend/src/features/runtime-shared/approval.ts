export function formatApprovalInput(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return String(value || '');
  }
}

export function approvalPreviewRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function approvalPreviewValue(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  }
  return '';
}

export function runtimeToolDisplayLabel(toolName: string): string {
  const tool = String(toolName || '').trim();
  if (tool === 'terminal.run') return '运行终端命令';
  if (tool === 'workspace.write_patch') return '写入工作区文件';
  if (tool === 'workspace.read' || tool === 'workspace.list') return '读取工作区';
  if (tool === 'artifact.write') return '生成产物';
  if (tool === 'workflow.approval') return 'Workflow 人工确认';
  if (tool === 'group.approval') return '群组人工确认';
  if (tool === 'screen.capture') return '截取屏幕';
  if (tool === 'desktop.active_window') return '读取当前窗口';
  if (tool === 'app.open') return '打开应用';
  if (tool === 'app.focus') return '聚焦应用';
  if (tool === 'media.apple_music_play') return '播放 Apple Music';
  if (tool === 'desktop.hotkey') return '发送快捷键';
  if (tool === 'desktop.type_text') return '输入前台文字';
  if (tool === 'browser.open_url') return '打开网页';
  if (tool === 'browser.current_page') return '读取当前网页';
  if (tool === 'browser.click') return '点击网页元素';
  if (tool === 'browser.type_text') return '填写网页输入';
  if (tool === 'browser.extract_text') return '提取网页文本';
  if (tool === 'browser.screenshot') return '截取网页';
  return '工具调用';
}

export function runtimeToolDisplayLabelOrName(toolName: string): string {
  const tool = String(toolName || '').trim();
  const display = runtimeToolDisplayLabel(tool);
  if (display !== '工具调用') return display;
  if (runtimeToolLooksInternalId(tool)) return display;
  return tool || display;
}

export function runtimeToolFamily(toolName: string): string {
  const tool = String(toolName || '').trim();
  if (
    tool === 'screen.capture'
    || tool === 'desktop.active_window'
    || tool === 'app.open'
    || tool === 'app.focus'
    || tool === 'media.apple_music_play'
    || tool === 'desktop.hotkey'
    || tool === 'desktop.type_text'
  ) {
    return 'desktop';
  }
  if (tool.startsWith('browser.')) return 'browser';
  if (tool.startsWith('workspace.')) return 'workspace';
  if (tool.startsWith('terminal.')) return 'terminal';
  if (tool.startsWith('memory.')) return 'memory';
  if (tool.startsWith('skill.')) return 'skill';
  if (tool.startsWith('artifact.')) return 'artifact';
  if (tool.startsWith('future_task.')) return 'future_task';
  return 'tool';
}

function runtimeToolLooksInternalId(toolName: string): boolean {
  return /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/i.test(toolName)
    || /^[a-z][a-z0-9]+(?:_[a-z0-9]+)+$/i.test(toolName);
}
