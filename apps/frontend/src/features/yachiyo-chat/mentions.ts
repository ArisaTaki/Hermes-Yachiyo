export type MentionParticipant = {
  kind?: 'main' | 'agent' | 'workflow' | 'group' | string;
  id?: string;
  name?: string;
  nickname?: string;
  avatar_url?: string;
};

export type MentionOption = {
  id: string;
  name: string;
  nickname?: string;
  avatar_url?: string;
  kind: 'main' | 'agent' | 'workflow';
  participants?: MentionParticipant[];
};

export type PublicTaskMentionTarget = MentionOption & {
  kind: 'agent' | 'workflow';
};

export type MentionRunnable = {
  id: string;
  name: string;
  nickname?: string;
  avatar_url?: string;
  kind: 'agent' | 'workflow' | string;
  participants?: MentionParticipant[];
  enabled?: boolean;
};

export type MentionAssistantProfile = {
  agent_nickname?: string;
  agent_avatar_url?: string;
};

export type MentionSessionContext = {
  conversation_kind?: 'main' | 'agent' | 'workflow' | 'group' | 'unassigned' | string;
  participants?: MentionParticipant[];
};

export function mentionQueryAtEnd(value: string): string | null {
  const match = String(value || '').match(/(^|[\s，。！？、；;,.!?])@([^\s@，。！？、；;,.!?]*)$/);
  return match ? match[2] : null;
}

export function mentionOptionsForQuery(
  runnables: MentionRunnable[],
  query: string | null,
  assistantProfile: MentionAssistantProfile | null,
  context?: MentionSessionContext | null,
): MentionOption[] {
  if (query === null) return [];
  const needle = query.trim().toLowerCase();
  const normalized = normalizeMentionSessionContext(context);
  let scopedRunnables = runnables;
  if (normalized.conversation_kind === 'group') {
    const groupAgentIds = new Set(
      (normalized.participants || [])
        .filter((participant) => participant.kind === 'agent')
        .map((participant) => participant.id)
        .filter(Boolean),
    );
    scopedRunnables = runnables.filter((item) => (
      item.kind === 'workflow' || (item.kind === 'agent' && groupAgentIds.has(item.id))
    ));
  }
  return allMentionOptions(scopedRunnables, assistantProfile)
    .filter((option) => {
      if (!needle) return true;
      return [
        option.name,
        option.nickname,
        option.kind === 'main' ? 'main model' : '',
        option.kind,
      ].some((value) => String(value || '').toLowerCase().includes(needle));
    })
    .slice(0, 7);
}

export function allMentionOptions(
  runnables: MentionRunnable[],
  assistantProfile: MentionAssistantProfile | null,
): MentionOption[] {
  const main: MentionOption = {
    id: 'main',
    name: '主模型',
    nickname: assistantProfile?.agent_nickname || '八千代',
    avatar_url: assistantProfile?.agent_avatar_url,
    kind: 'main',
  };
  const options: MentionOption[] = [
    main,
    ...runnables
      .filter((item) => item.kind === 'agent')
      .map(mentionOptionFromRunnable),
    ...runnables
      .filter((item) => item.kind === 'workflow')
      .map(mentionOptionFromRunnable),
  ];
  return options;
}

export function mentionKindLabel(option: MentionOption) {
  if (option.kind === 'main') return '主模型';
  if (option.kind === 'workflow') {
    const count = option.participants?.length || 0;
    return count ? `Workflow · ${count} Agents` : 'Workflow';
  }
  return 'Agent';
}

export function mentionTextForOption(option: MentionOption) {
  if (option.kind === 'main') return '@主模型 ';
  const name = option.nickname || option.name;
  if (/\s/.test(name)) return `@"${name.replace(/"/g, '\\"')}" `;
  return `@${name} `;
}

export function replaceTrailingMentionQuery(value: string, mentionText: string) {
  const match = String(value || '').match(/(^|[\s\S]*[\s，。！？、；;,.!?])@([^\s@，。！？、；;,.!?]*)$/);
  if (match) return `${match[1]}${mentionText}`;
  const spacer = value && !/[\s，。！？、；;,.!?]$/.test(value) ? ' ' : '';
  return `${value}${spacer}${mentionText}`;
}

export function activeMentions(
  input: string,
  runnables: MentionRunnable[],
  assistantProfile: MentionAssistantProfile | null,
): MentionOption[] {
  const options = allMentionOptions(runnables, assistantProfile);
  const seen = new Set<string>();
  const result: MentionOption[] = [];
  const mentionRe = /@(?:"([^"]+)"|'([^']+)'|([^\s@，。！？、；;,.!?]+))/g;
  let match: RegExpExecArray | null;
  while ((match = mentionRe.exec(input)) !== null) {
    const label = String(match[1] || match[2] || match[3] || '').toLowerCase();
    const option = options.find((candidate) => [
      candidate.name,
      candidate.nickname,
      candidate.kind === 'main' ? '主模型' : '',
      candidate.kind === 'main' ? 'main' : '',
    ].some((value) => String(value || '').toLowerCase() === label));
    if (!option) continue;
    const key = `${option.kind}-${option.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(option);
  }
  return result;
}

export function yachiyoPublicTaskTarget(
  input: string,
  runnables: MentionRunnable[],
  assistantProfile: MentionAssistantProfile | null,
): PublicTaskMentionTarget | null {
  const mentions = activeMentions(input, runnables, assistantProfile);
  if (mentions.length !== 1) return null;
  return mentions[0].kind === 'main' ? null : mentions[0] as PublicTaskMentionTarget;
}

export function yachiyoPublicTaskPrompt(input: string, target: MentionOption): string {
  let prompt = String(input || '').trim();
  uniqueStrings([target.nickname, target.name]).forEach((label) => {
    const escaped = escapeRegExp(label);
    prompt = prompt.replace(
      new RegExp(`(^|[\\s，。！？、；;,.!?])@(?:"${escaped}"|'${escaped}'|${escaped})(?=$|[\\s，。！？、；;,.!?])`, 'gi'),
      '$1',
    );
  });
  prompt = prompt.replace(/\s{2,}/g, ' ').trim();
  return prompt || String(input || '').trim();
}

export function yachiyoDailyDesktopTaskPrompt(input: string): string | null {
  const prompt = String(input || '').trim();
  if (!prompt || DESKTOP_INTENT_HELP_RE.test(prompt)) return null;
  return looksLikeDailyDesktopIntent(prompt) ? prompt : null;
}

function mentionOptionFromRunnable(item: MentionRunnable): MentionOption {
  return {
    id: item.id,
    name: item.name,
    nickname: item.nickname,
    avatar_url: item.avatar_url,
    kind: item.kind as 'agent' | 'workflow',
    participants: (item.participants || []).map((participant) => ({
      id: participant.id,
      name: participant.name,
      nickname: participant.nickname,
      avatar_url: participant.avatar_url,
      kind: participant.kind,
    })),
  };
}

function normalizeMentionSessionContext(context?: MentionSessionContext | null): MentionSessionContext {
  return {
    conversation_kind: context?.conversation_kind || 'main',
    participants: Array.isArray(context?.participants) ? context?.participants : [],
  };
}

function uniqueStrings(values: unknown[]): string[] {
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean)));
}

function escapeRegExp(value: string): string {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

const DESKTOP_INTENT_HELP_RE = /(?:怎么|如何|教程|步骤|只告诉我|不要真的|别真的|不要执行|别执行|不要操作|无需执行|不用执行)/i;
const URL_RE = /(?:https?:\/\/|www\.|[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:com|net|org|io|dev|app|ai|cn|jp|co|me|gg|tv|xyz|site|tech)\b)/i;
const LOCAL_PATH_RE = /(?:~\/|\.{1,2}\/|\/(?:Users|Applications|Volumes|tmp|var|private)\b|(?:下载|桌面|应用程序)(?:文件夹)?)/i;
const WEB_SITE_NAME_RE = new RegExp([
  'chatgpt', 'claude', 'perplexity',
  'github', 'google', '谷歌', 'youtube', 'yt',
  'bilibili', 'b站', '哔哩哔哩',
  '小红书', 'xiaohongshu', 'rednote',
  '微博', 'weibo', '知乎', 'zhihu', '豆瓣', 'douban',
  '抖音', 'douyin', 'tiktok',
  'gmail', 'google\\s*drive', 'google\\s*docs',
  '淘宝', 'taobao', '京东', 'jd', 'jingdong',
].join('|'), 'i');
const DESKTOP_APP_NAME_RE = new RegExp([
  'apple\\s*music', 'music', '音乐',
  'google\\s*chrome', 'chrome', 'chrome浏览器', '谷歌浏览器', '浏览器',
  'safari', 'finder', '访达', 'terminal', '终端', '命令行',
  'system\\s*settings', 'settings', '系统设置', '设置',
  'notes', '备忘录', 'calendar', '日历', 'reminders', '提醒事项',
  'mail', '邮件', '邮箱', 'messages', '信息', 'facetime',
  'contacts', '联系人', 'maps', '地图', 'photos', '照片',
  'preview', '预览', 'calculator', '计算器', 'app\\s*store', '应用商店',
  'activity\\s*monitor', '活动监视器', 'keychain\\s*access', '钥匙串',
  'textedit', '文本编辑', 'quicktime', 'quicktime\\s*player',
  'slack', 'discord', 'notion', 'obsidian', 'vscode', 'vs\\s*code',
  'visual\\s*studio\\s*code', 'cursor', 'arc', 'firefox', '火狐',
  'edge', 'microsoft\\s*edge', 'brave', 'spotify', 'shortcuts', '快捷指令',
  'figma', 'zoom', 'teams', 'microsoft\\s*teams',
  'word', 'microsoft\\s*word', 'excel', 'microsoft\\s*excel',
  'powerpoint', 'ppt', 'microsoft\\s*powerpoint', 'outlook',
  'telegram', 'whatsapp', 'wechat', '微信', 'qq',
  '飞书', 'feishu', 'lark', '钉钉', 'dingtalk',
  '腾讯会议', 'tencent\\s*meeting', 'iterm', 'iterm2',
  'warp', 'docker', 'xcode', 'postman', 'linear', 'raycast',
  'pycharm', 'intellij', 'idea', 'webstorm', 'goland',
].join('|'), 'i');

function looksLikeDailyDesktopIntent(prompt: string): boolean {
  const value = prompt.trim();
  if (!value) return false;
  if (/(?:打开|访问|浏览|open|visit|go to|navigate to)/i.test(value) && URL_RE.test(value)) return true;
  if (/(?:打开|访问|浏览|前往|去|open|visit|go to|navigate to)/i.test(value) && WEB_SITE_NAME_RE.test(value)) return true;
  if (/(?:(?:搜索|搜一下|搜|查一下|查查|检索)\s*\S+|(?:search|google|look up)\s+\S+)/i.test(value)) return true;
  if (/(?:当前网页|读取当前网页|网页正文|截取当前网页|browser screenshot|current page|(?:读一下|读取|阅读|提取).{0,8}(?:这个|当前)?网页)/i.test(value)) return true;
  if (/(?:截图|截屏|截个图|屏幕截图|screenshot|capture screen)/i.test(value)) return true;
  if (/(?:当前窗口是什么|当前窗口|active window|frontmost window)/i.test(value)) return true;
  if (/(?:正在运行的应用|开了哪些应用|运行的应用|running apps|what apps are running)/i.test(value)) return true;
  if (/(?:(?:列出|查看|看看|显示|读取).{0,12}(?:窗口|windows?)|(?:窗口|windows?).{0,12}(?:哪些|什么|几个|多少)|show .+ windows)/i.test(value)) return true;
  if (/(?:(?:当前音量|调[大小]音量|声音[大小]一点|静音|取消静音)|(?:volume|mute|unmute))/i.test(value)) return true;
  if (/(?:(?:复制|写入).*(?:剪贴板)|(?:copy|write).+(?:clipboard))/i.test(value)) return true;
  if (/^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:复制(?:选中|当前选中)?内容?|粘贴|全选|撤销|重做|刷新|查找|新建标签页|新标签页|打开新标签页)(?:一下|下|一次)?[?？。！!]*$/i.test(value)) return true;
  if (/^(?:copy(?: selected(?: text| content)?)?|paste|select all|undo|redo|refresh|reload|find|new tab)[.!?]*$/i.test(value)) return true;
  if (/(?:(?:退出|关闭|关掉|结束)\s*\S+|(?:quit|close|exit)\s+\S+)/i.test(value) && DESKTOP_APP_NAME_RE.test(value)) return true;
  if (/(?:(?:显示|还原|恢复|取消隐藏|隐藏|收起|最小化)\s*\S+|(?:show|unhide|restore|hide|minimi[sz]e)\s+\S+)/i.test(value) && DESKTOP_APP_NAME_RE.test(value)) return true;
  if (/(?:(?:隐藏|收起).{0,8}(?:当前|现在|前台|这个|该).{0,4}(?:应用|app|软件|程序)|hide\s+(?:the\s+)?(?:current|foreground|active|this)\s+(?:app|application))/i.test(value)) return true;
  if (/(?:(?:最小化|收起).{0,8}(?:当前|现在|前台|这个|该).{0,4}(?:窗口|window)|(?:minimi[sz]e|hide)\s+(?:the\s+)?(?:current|foreground|active|this)\s+window)/i.test(value)) return true;
  if (/(?:(?:关闭|关掉).{0,8}(?:当前|现在|前台|这个|该).{0,4}(?:窗口|window)|(?:close|dismiss)\s+(?:the\s+)?(?:current|foreground|active|this)\s+window)/i.test(value)) return true;
  if (/^(?:(?:按)\s*|(?:press)\s+)(?:command|cmd|ctrl|control|shift|alt|option|⌘|⌥|⌃)/i.test(value)) return true;
  if (/^(?:(?:输入|键入)\s*|(?:type)\s+)\S+/i.test(value)) return true;
  if (/^(?:(?:点击|双击)\s*|(?:click|double click)\s+)\d+\s*[,， ]\s*\d+/i.test(value)) return true;
  if (/(?:(?:播放|播一下|放一下)\s*\S+|(?:play)\s+\S+)/i.test(value)) return true;
  if (/(?:(?:暂停|停止播放|继续播放|恢复播放|接着播放|播放暂停|切换播放|切换暂停)(?:\s*(?:音乐|歌曲|apple\s*music|music))?|(?:下一首|上一首|切歌|来点音乐|来些音乐|来点歌|放首歌)|(?:pause|resume|continue|next|previous|skip)(?:\s+(?:music|song|apple\s*music))?)/i.test(value)) return true;
  if (/(?:(?:在\s*(?:Finder|访达)(?:中|里)?显示)|(?:show|reveal).+(?:in|with)\s+finder)/i.test(value) && LOCAL_PATH_RE.test(value)) return true;
  if (/(?:打开\s*|open\s+)/i.test(value) && LOCAL_PATH_RE.test(value)) return true;
  if (/(?:(?:开着吗|在运行吗|打开了吗)|(?:is|check).*(?:running|open))/i.test(value) && DESKTOP_APP_NAME_RE.test(value)) return true;
  if (/(?:(?:打开|启动|运行|切换到|切到|切回|回到|聚焦|激活|置前)\s*\S+|(?:focus|activate|switch to|bring up|launch|open)\s+\S+)/i.test(value) && DESKTOP_APP_NAME_RE.test(value)) return true;
  return false;
}
