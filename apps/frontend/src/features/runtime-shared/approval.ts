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
  return '工具调用';
}
