import { type FormEvent, useEffect, useRef } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import { chooseAvatarImage } from '../../../lib/bridge';
import { readPendingAttachment } from '../attachments';
import type { ChatParticipant, AssistantProfilePayload } from '../types';
import type { ChatRunnableSummary } from '../runnables';
import { participantDisplayName, participantInitial } from '../sessionState';

const GROUP_AVATAR_MAX_BYTES = 1024 * 1024;
const GROUP_AVATAR_MAX_DATA_URL_CHARS = Math.ceil((GROUP_AVATAR_MAX_BYTES * 4) / 3) + 128;

type ChatGroupDialogProps = {
  agentRunnables: ChatRunnableSummary[];
  assistantProfile: AssistantProfilePayload | null;
  defaultGroupName: string;
  error: string;
  groupAvatarUrl: string;
  groupName: string;
  isCreating: boolean;
  mode: 'create' | 'edit';
  selectedAgentIds: string[];
  onAvatarError: (message: string) => void;
  onAvatarUrlChange: (value: string) => void;
  onClose: () => void;
  onNameChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onToggleAgent: (agentId: string) => void;
};

export function ChatGroupDialog({
  agentRunnables,
  assistantProfile,
  defaultGroupName,
  error,
  groupAvatarUrl,
  groupName,
  isCreating,
  mode,
  selectedAgentIds,
  onAvatarError,
  onAvatarUrlChange,
  onClose,
  onNameChange,
  onSubmit,
  onToggleAgent,
}: ChatGroupDialogProps) {
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const mainName = assistantProfile?.agent_name || 'Yachiyo';
  const mainNickname = assistantProfile?.agent_nickname || '八千代';
  const memberCount = selectedAgentIds.length + 1;
  const selectedParticipants: ChatParticipant[] = [
    {
      kind: 'main',
      name: mainName,
      nickname: mainNickname,
      avatar_url: assistantProfile?.agent_avatar_url,
    },
    ...selectedAgentIds
      .map((agentId) => agentRunnables.find((agent) => agent.id === agentId))
      .filter((agent): agent is ChatRunnableSummary => Boolean(agent))
      .map((agent): ChatParticipant => ({
        kind: 'agent',
        id: agent.id,
        name: agent.name,
        nickname: agent.nickname,
        avatar_url: agent.avatar_url,
      })),
  ];
  const dialogTitle = mode === 'edit' ? '群组设置' : '创建群组';
  const submittingText = mode === 'edit' ? '保存中...' : '创建中...';
  const submitText = mode === 'edit' ? '保存' : '创建';

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  function acceptAvatarValue(value: string) {
    const avatar = String(value || '').trim();
    if (!avatar) return;
    if (avatar.startsWith('data:image/') && avatar.length > GROUP_AVATAR_MAX_DATA_URL_CHARS) {
      onAvatarError('群头像不能超过 1 MB');
      return;
    }
    onAvatarUrlChange(avatar);
  }

  async function pickGroupAvatar() {
    try {
      const selection = await chooseAvatarImage();
      const avatar = typeof selection === 'string' ? selection : selection?.data_url || selection?.path || '';
      acceptAvatarValue(avatar);
    } catch (error) {
      const message = error instanceof Error ? error.message : '选择群头像失败';
      if (message.includes('桌面图片选择器')) {
        avatarInputRef.current?.click();
        return;
      }
      onAvatarError(message);
    }
  }

  async function applyAvatarFile(file: File) {
    if (!file.type.startsWith('image/')) {
      onAvatarError('请选择图片作为群头像');
      return;
    }
    if (file.size > GROUP_AVATAR_MAX_BYTES) {
      onAvatarError('群头像不能超过 1 MB');
      return;
    }
    try {
      const attachment = await readPendingAttachment(file);
      onAvatarUrlChange(attachment.data_url);
    } catch (error) {
      onAvatarError(error instanceof Error ? error.message : '读取群头像失败');
    }
  }

  return (
    <div className="chat-modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <form className="chat-group-dialog" data-testid="chat-group-dialog" role="dialog" aria-modal="true" aria-label={dialogTitle} onSubmit={onSubmit}>
        <header className="chat-group-dialog-header">
          <div>
            <strong>{dialogTitle}</strong>
            <span>{memberCount} 成员</span>
          </div>
          <button type="button" className="chat-action-btn" data-testid="chat-group-dialog-close" aria-label="关闭" title="关闭" onClick={onClose}>
            <UiIcon name="close" />
          </button>
        </header>
        <div className="chat-group-profile-fields">
          <div className="chat-group-avatar-control">
            <button
              type="button"
              className="chat-group-avatar-preview"
              data-testid="chat-group-avatar-preview"
              aria-label="选择群头像"
              title="选择群头像"
              onClick={() => void pickGroupAvatar()}
            >
              {groupAvatarUrl.trim() ? (
                chatGroupAvatarNode(groupAvatarUrl.trim(), groupName || defaultGroupName || '群组', '群')
              ) : (
                <ChatGroupAvatarStack participants={selectedParticipants} />
              )}
            </button>
            <button
              type="button"
              className="chat-group-avatar-clear"
              data-testid="chat-group-avatar-clear"
              aria-label="清除群头像"
              title="清除群头像"
              disabled={!groupAvatarUrl.trim()}
              onClick={() => onAvatarUrlChange('')}
            >
              <UiIcon name="close" />
            </button>
            <input
              ref={avatarInputRef}
              type="file"
              accept="image/*"
              data-testid="chat-group-avatar-file-input"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) void applyAvatarFile(file);
              }}
            />
          </div>
          <div className="chat-group-field-stack">
            <input
              className="chat-group-name-input"
              data-testid="chat-group-name-input"
              value={groupName}
              onChange={(event) => onNameChange(event.target.value)}
              placeholder={defaultGroupName ? `默认：${defaultGroupName}` : '群组名称'}
              maxLength={48}
              aria-label="群组名称"
            />
            <div className="chat-group-avatar-actions">
              <button type="button" className="chat-group-secondary-btn" data-testid="chat-group-avatar-select" onClick={() => void pickGroupAvatar()}>
                选择头像
              </button>
              <button type="button" className="chat-group-secondary-btn" data-testid="chat-group-avatar-clear-secondary" disabled={!groupAvatarUrl.trim()} onClick={() => onAvatarUrlChange('')}>
                清除
              </button>
            </div>
          </div>
        </div>
        {error ? <div className="chat-group-dialog-error" data-testid="chat-group-dialog-error">{error}</div> : null}
        <div className="chat-group-member-list" data-testid="chat-group-member-list">
          <label className="chat-group-member is-fixed" data-testid="chat-group-main-member">
            <input type="checkbox" checked readOnly />
            <span className="chat-group-member-avatar">{chatGroupParticipantAvatar({ kind: 'main', name: mainName, nickname: mainNickname, avatar_url: assistantProfile?.agent_avatar_url }, '月')}</span>
            <span>
              <strong>主模型</strong>
              <small>{mainNickname || mainName}</small>
            </span>
          </label>
          {agentRunnables.map((agent) => {
            const selected = selectedAgentIds.includes(agent.id);
            const participant: ChatParticipant = {
              kind: 'agent',
              id: agent.id,
              name: agent.name,
              nickname: agent.nickname,
              avatar_url: agent.avatar_url,
            };
            return (
              <label className={`chat-group-member ${selected ? 'selected' : ''}`} data-testid="chat-group-agent-member" key={agent.id}>
                <input
                  type="checkbox"
                  data-testid="chat-group-agent-member-checkbox"
                  checked={selected}
                  onChange={() => onToggleAgent(agent.id)}
                />
                <span className="chat-group-member-avatar">{chatGroupParticipantAvatar(participant, 'A')}</span>
                <span>
                  <strong>{agent.nickname || agent.name}</strong>
                  <small>{groupAgentMetaLine(agent)}</small>
                  <small className="chat-group-member-tools">{groupAgentToolLine(agent)}</small>
                  {agent.description ? <em>{agent.description}</em> : null}
                </span>
              </label>
            );
          })}
        </div>
        <footer className="chat-group-dialog-actions">
          <button type="button" className="chat-group-secondary-btn" data-testid="chat-group-dialog-cancel" onClick={onClose}>取消</button>
          <button type="submit" className="chat-group-primary-btn" data-testid="chat-group-dialog-submit" disabled={isCreating || selectedAgentIds.length === 0}>
            {isCreating ? submittingText : submitText}
          </button>
        </footer>
      </form>
    </div>
  );
}

function chatGroupAvatarNode(url: string | undefined, label: string, fallback: string) {
  return url ? <img src={url} alt={label} /> : fallback;
}

function chatGroupParticipantAvatar(participant: ChatParticipant | null | undefined, fallback = '月') {
  const label = participantDisplayName(participant) || fallback;
  return chatGroupAvatarNode(participant?.avatar_url, label, participantInitial(participant, fallback));
}

function ChatGroupAvatarStack({ participants }: { participants: ChatParticipant[] }) {
  const visible = participants.slice(0, 3);
  if (!visible.length) return <>{'W'}</>;
  return (
    <span className="chat-avatar-stack-inner" aria-hidden="true">
      {visible.map((participant, index) => (
        <span className="chat-avatar-stack-face" key={participant.id || participant.name || index}>
          {chatGroupParticipantAvatar(participant, 'A')}
        </span>
      ))}
    </span>
  );
}

function groupAgentMetaLine(agent: ChatRunnableSummary): string {
  const parts = [
    agent.name,
    agent.category ? `类别 ${agent.category}` : '',
    agent.output_contract ? `交付 ${agent.output_contract}` : '',
  ].filter(Boolean);
  return parts.join(' · ') || 'Agent';
}

function groupAgentToolLine(agent: ChatRunnableSummary): string {
  const allowedTools = new Set((agent.tool_capabilities || []).map((tool) => String(tool)));
  const approvalTools = new Set((agent.approval_required_tools || []).map((tool) => String(tool)));
  const needsApproval = (tool: string) => approvalTools.has(tool);
  const parts: string[] = [];
  if (allowedTools.has('workspace.read') || allowedTools.has('workspace.list')) parts.push('读文件');
  if (allowedTools.has('workspace.write_patch')) parts.push(needsApproval('workspace.write_patch') ? '写补丁需审批' : '写补丁');
  if (allowedTools.has('terminal.run')) parts.push(needsApproval('terminal.run') ? '终端需审批' : '终端');
  if (allowedTools.has('artifact.write')) parts.push('产物');
  return parts.length ? parts.join(' · ') : '仅对话';
}
