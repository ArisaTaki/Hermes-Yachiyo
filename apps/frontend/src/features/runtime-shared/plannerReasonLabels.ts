const PLANNER_REASON_LABELS: Record<string, string> = {
  clear_daily_desktop_intent: '日常桌面意图',
  planner_auto_code_context_read: '自动读取代码上下文',
  planner_builtin_data_analysis: '内置数据分析',
  planner_desktop_app_discovery: '桌面应用发现',
  planner_desktop_operation: '桌面操作',
  planner_fallback_clipboard: '剪贴板操作',
  planner_fallback_code_diagnostic: '代码诊断补充',
  planner_fallback_communication_send: '通信应用发送',
  planner_fallback_current_page_find: '当前页面查找',
  planner_fallback_data_analysis_file_open: '打开数据文件',
  planner_fallback_data_analysis_spreadsheet_app: '打开表格应用',
  planner_fallback_dynamic_browser_context: '动态浏览器上下文',
  planner_fallback_file_access: '文件访问',
  planner_fallback_information_capture: '信息采集',
  planner_fallback_media_playback: '媒体播放',
  planner_fallback_schedule: '日程/提醒操作',
  planner_fallback_schedule_context_app_item: '读取日程应用条目',
  planner_fallback_system_control: '系统控制',
  planner_fallback_web_research: '网页研究',
  planner_followup_artifact_write: '写入产物后继续',
  planner_followup_communication_observed_compose: '观察输入框后继续发信',
  planner_followup_desktop_observed_action: '观察 UI 后继续执行',
  planner_followup_note_write: '写入笔记后继续',
  planner_followup_verify_code_changes: '验证代码修改',
  planner_policy_gate: '策略审批检查',
  planner_prefetch_communication_context: '预取通信上下文',
  planner_prefetch_data_source: '预取数据源',
  planner_prefetch_desktop_content: '预取桌面内容',
  planner_prefetch_file_scope: '预取文件范围',
  planner_prefetch_information_capture_context: '预取信息采集上下文',
  planner_prefetch_report_context: '预取报告素材',
  planner_prefetch_schedule_context: '预取日程上下文',
  planner_prefetch_web_context: '预取网页上下文',
  planner_replan_fallback_recovery: '失败后恢复规划',
  planner_replan_runtime_recovery_action: 'Runtime 恢复动作',
  planner_selected_foreground_operation: '前台操作',
};

export function runtimePlannerReasonLabel(reason: string | null | undefined): string {
  const clean = String(reason || '').trim();
  if (!clean) return '';
  const known = PLANNER_REASON_LABELS[clean];
  if (known) return known;
  return clean
    .replace(/^planner_/, '')
    .replace(/_/g, ' ')
    .trim();
}

