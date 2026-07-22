import type { AgentTaskSnapshot, ChatMessage } from './types';

export type ConsumerFailureKind =
  | 'approval_required'
  | 'permission_required'
  | 'cancelled'
  | 'verification_failed'
  | 'content_not_found'
  | 'app_not_found'
  | 'target_not_found'
  | 'unknown';

export type ConsumerFailurePresentation = {
  kind: ConsumerFailureKind;
  title: string;
  detail: string;
};

const FAILURE_PRESENTATIONS: Record<ConsumerFailureKind, ConsumerFailurePresentation> = {
  approval_required: {
    kind: 'approval_required',
    title: '需要你的确认',
    detail: '确认后即可继续。',
  },
  permission_required: {
    kind: 'permission_required',
    title: '需要系统权限',
    detail: '完成授权后即可重试。',
  },
  cancelled: {
    kind: 'cancelled',
    title: '任务已取消',
    detail: '任务已经停止；需要时可以重新发送。',
  },
  verification_failed: {
    kind: 'verification_failed',
    title: '结果还无法确认',
    detail: '操作可能已经发生，但结果未通过验证。建议重试或查看详情。',
  },
  content_not_found: {
    kind: 'content_not_found',
    title: '没有找到对应内容',
    detail: '没有找到可播放的匹配内容。可以换个名称，或补充歌手后重试。',
  },
  app_not_found: {
    kind: 'app_not_found',
    title: '没有找到目标应用',
    detail: '请确认应用已经安装，或换用它的完整名称。',
  },
  target_not_found: {
    kind: 'target_not_found',
    title: '没有找到操作目标',
    detail: '当前页面或窗口里没有找到要操作的对象。请打开对应界面后重试。',
  },
  unknown: {
    kind: 'unknown',
    title: '这次没有完成',
    detail: '请重试；如果仍然失败，可在 Agent Studio 查看详情。',
  },
};

export function consumerFailureText(presentation: ConsumerFailurePresentation): string {
  return `${presentation.title}\n\n${presentation.detail}`;
}

export function consumerMessageFailurePresentation(
  message: ChatMessage,
  displayContent = '',
): ConsumerFailurePresentation {
  const runStatus = String(message.metadata?.run_status || message.metadata?.workflow_status || '').toLowerCase();
  const pendingApprovalId = firstApprovalId(
    message.metadata?.pending_approval,
    message.metadata?.workflow_waiting_pending_approval,
  );
  return consumerFailurePresentation(
    [
      message.status,
      message.error,
      displayContent,
      message.progress_label,
      message.activity_events,
      message.metadata,
    ],
    {
      approvalRequired: Boolean(pendingApprovalId),
      cancelled: ['cancelled', 'canceled'].includes(String(message.status || '').toLowerCase())
        || ['cancelled', 'canceled'].includes(runStatus),
    },
  );
}

export function consumerTaskFailurePresentation(
  task: AgentTaskSnapshot,
): ConsumerFailurePresentation {
  const status = String(task.status || '').toLowerCase();
  const verificationStatus = String(task.task_progress?.latest_verification_status || '').toLowerCase();
  const hasAttemptedToolExecution = taskHasAttemptedToolExecution(task);
  return consumerFailurePresentation(
    [task],
    {
      approvalRequired: Boolean(
        task.pending_approvals?.some((approval) => (
          (approval.status || 'pending') === 'pending'
          && Boolean(String(approval.approval_id || '').trim())
        )),
      ),
      cancelled: ['cancelled', 'canceled'].includes(status),
      verificationFailed: Number(task.task_progress?.failed_verification_count || 0) > 0
        || ['failed', 'rejected', 'unverified'].includes(verificationStatus),
      verificationFailureAllowed: hasAttemptedToolExecution,
    },
  );
}

function taskHasAttemptedToolExecution(task: AgentTaskSnapshot): boolean {
  const toolCallShowsExecution = task.tool_calls?.some((toolCall) => {
    const status = String(toolCall.status || '').trim().toLowerCase();
    if (['running', 'completed', 'succeeded', 'success', 'failed', 'error'].includes(status)) {
      return true;
    }
    return !status && Boolean(String(toolCall.started_at || toolCall.completed_at || '').trim());
  });
  if (toolCallShowsExecution) return true;

  return Boolean(task.recent_events?.some((event) => {
    const eventType = String(event.event_type || '').trim().toLowerCase();
    if ([
      'agent.tool.started',
      'agent.tool.call',
      'agent.tool.completed',
      'agent.tool.failed',
      'tool.started',
      'tool.completed',
      'tool.succeeded',
      'tool.failed',
    ].includes(eventType)) {
      return true;
    }
    return /^(?:agent|group\.run|workflow(?:\.run)?)\.desktop\.intent_(?:completed|unverified)$/.test(eventType);
  }));
}

function consumerFailurePresentation(
  values: unknown[],
  hints: {
    approvalRequired?: boolean;
    cancelled?: boolean;
    verificationFailed?: boolean;
    verificationFailureAllowed?: boolean;
  } = {},
): ConsumerFailurePresentation {
  if (hints.cancelled) return FAILURE_PRESENTATIONS.cancelled;
  if (hints.approvalRequired) return FAILURE_PRESENTATIONS.approval_required;

  const signals = collectFailureSignals(values);
  const matches = (pattern: RegExp) => signals.some((signal) => pattern.test(signal));

  if (matches(
    /\b(?:permission[_ -]?(?:required|denied|missing|error)|missing[_ -]?permissions?|permission[_ -]?targets?)\b|\b(?:accessibility|automation|screen[_ -]?recording|microphone|camera)\b.{0,32}\b(?:permission|access|authorization)\b|\b(?:permission|access|authorization)\b.{0,32}\b(?:required|denied|missing|accessibility|automation|screen[_ -]?recording|microphone|camera)\b|辅助功能权限|自动化权限|屏幕录制权限|麦克风权限|相机权限|需要授权|权限(?:不足|未授予|被拒绝)/iu,
  )) {
    return FAILURE_PRESENTATIONS.permission_required;
  }
  if (hints.verificationFailureAllowed !== false && hints.verificationFailed) {
    return FAILURE_PRESENTATIONS.verification_failed;
  }
  if (matches(/\b(?:cancelled|canceled|aborted|user[_ -]?cancelled)\b|已取消|被取消|停止执行/iu)) {
    return FAILURE_PRESENTATIONS.cancelled;
  }
  if (
    hints.verificationFailureAllowed !== false
    && matches(/\b(?:verification[_ -]?(?:failed|rejected)|failed[_ -]?verification|unverified)\b|验证失败|未通过验证|无法确认结果/iu)
  ) {
    return FAILURE_PRESENTATIONS.verification_failed;
  }

  const technicalConfigurationFailure = matches(
    /\b(?:provider|profile|source|model|tool[_ -]?call)[\w:./-]*.{0,48}\b(?:not[_ -]?found|missing|unavailable|invalid|failed)\b|(?:供应商|模型(?:配置)?|配置源|来源|工具调用).{0,36}(?:不存在|未找到|缺失|无效|失败)/iu,
  );
  const appNotFound = matches(
    /\b(?:app|application|bundle)[_ -]?(?:not[_ -]?found|not[_ -]?installed|missing|unavailable)\b|\b(?:app|application|bundle)\b.{0,48}\b(?:could not be found|cannot be found|can't be found|not found|not installed|missing|unavailable)\b|(?:应用|软件)(?:未安装|不存在|未找到|找不到|不可用)|(?:未安装|不存在|未找到|找不到).{0,16}(?:应用|软件)/iu,
  );
  if (appNotFound) return FAILURE_PRESENTATIONS.app_not_found;

  const strongContentNoMatch = matches(
    /(?:\b(?:content|media|library)[_ -]?(?:not[_ -]?found|no[_ -]?match)\b)|(?:\b(?:library|catalog)\b.{0,96}\b(?:did not contain|does not contain|didn't contain|did not provide (?:an? |one )?(?:unambiguous )?(?:exact )?match)\b)|(?:\b(?:song|track|album|playlist|library item|playback content)\b.{0,64}\b(?:not[_ -]?found|no[_ -]?(?:match|result)s?|could not find|unable to (?:find|play)|couldn't (?:find|play))\b)|(?:\b(?:not[_ -]?found|no[_ -]?(?:match|result)s?|could not find|unable to (?:find|play)|couldn't (?:find|play))\b.{0,64}\b(?:song|track|album|playlist|library item)\b)|(?:(?:歌曲|音乐|曲目|专辑|播放列表|媒体内容).{0,48}(?:未找到|没找到|没有找到|找不到|无匹配|没有匹配|未搜到|搜索不到|无法播放|未能播放|没能(?:直接)?播放))|(?:(?:未找到|没找到|没有找到|找不到|无匹配|没有匹配|未搜到|搜索不到|无法播放|未能播放|没能(?:直接)?播放).{0,48}(?:歌曲|音乐|曲目|专辑|播放列表|媒体内容))/iu,
  );
  if (strongContentNoMatch && !technicalConfigurationFailure) {
    return FAILURE_PRESENTATIONS.content_not_found;
  }
  const targetNotFound = matches(
    /\b(?:target|window|button|element|control|menu|tab|field)[\w:./ -]*.{0,40}\b(?:not[_ -]?found|missing|unavailable)\b|\b(?:could not find|cannot find|can't find|unable to find)\b.{0,48}\b(?:target|window|button|element|control|menu|tab|field)\b|(?:目标|窗口|按钮|控件|菜单|输入框).{0,32}(?:未找到|找不到|无法找到|不存在|不可用)|(?:未找到|找不到|无法找到).{0,32}(?:目标|窗口|按钮|控件|菜单|输入框)/iu,
  );
  if (targetNotFound && !technicalConfigurationFailure) {
    return FAILURE_PRESENTATIONS.target_not_found;
  }

  const hasMediaContext = matches(/\b(?:music|media|library|content|song|track|album|playlist|playback)\b|音乐|媒体|内容|资料库|歌曲|曲目|专辑|播放列表|播放/iu);
  const hasMediaNoMatch = matches(
    /\b(?:no[_ -]?(?:match|result)s?|zero results?|no playable match(?:es)?|no matching (?:item|content)|not[_ -]?found|content[_ -]?not[_ -]?found|library[_ -]?no[_ -]?match|media[_ -]?no[_ -]?match|did not contain|does not contain|didn't contain|could not (?:find|play)|unable to play|couldn't play)\b|未找到|没找到|没有找到|无匹配|没有匹配|未搜到|没搜到|搜索不到|无法播放|未能播放|没能(?:直接)?播放/iu,
  );
  if (hasMediaContext && hasMediaNoMatch && !technicalConfigurationFailure) {
    return FAILURE_PRESENTATIONS.content_not_found;
  }

  return FAILURE_PRESENTATIONS.unknown;
}

function firstApprovalId(...values: unknown[]): string {
  for (const value of values) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
    const approvalId = String((value as Record<string, unknown>).approval_id || '').trim();
    if (approvalId) return approvalId;
  }
  return '';
}

function collectFailureSignals(values: unknown[]): string[] {
  const signals: string[] = [];
  const seen = new WeakSet<object>();
  const visit = (value: unknown, key = '', depth = 0) => {
    if (signals.length >= 160 || value === null || value === undefined || depth > 6) return;
    if (typeof value === 'string' || typeof value === 'number') {
      const text = String(value).trim();
      if (text) signals.push(`${key ? `${key}:` : ''}${text}`.slice(0, 640).toLowerCase());
      return;
    }
    if (typeof value === 'boolean') {
      if (value && key) signals.push(key.toLowerCase());
      return;
    }
    if (typeof value !== 'object' || seen.has(value)) return;
    seen.add(value);
    if (Array.isArray(value)) {
      value.slice(0, 40).forEach((item) => visit(item, key, depth + 1));
      return;
    }
    Object.entries(value as Record<string, unknown>)
      .slice(0, 80)
      .forEach(([childKey, childValue]) => visit(childValue, childKey, depth + 1));
  };
  values.forEach((value) => visit(value));
  return signals;
}
