import logoUrl from '../../../../../../docs/open-design/logo.png';

type ChatFullPageLoadingProps = {
  avatarUrl?: string;
  label: string;
};

export function ChatFullPageLoading({ avatarUrl, label }: ChatFullPageLoadingProps) {
  return (
    <div className="chat-full-page-loading" role="status" aria-live="polite">
      <div className="chat-full-page-avatar">
        <img src={avatarUrl || logoUrl} alt="" />
      </div>
      <div className="chat-loading-dots">
        <span /><span /><span />
      </div>
      <strong>{label}</strong>
      <span>正在准备对话...</span>
    </div>
  );
}
