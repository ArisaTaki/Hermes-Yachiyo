export type LauncherRecentSession = {
  session_id?: string;
  title?: string;
  summary?: string;
  latest_status?: string;
  conversation_kind?: string;
  updated_at?: string;
};

export type LauncherPayload = {
  ok?: boolean;
  mode?: 'bubble' | 'live2d';
  chat?: {
    session_id?: string;
    is_processing?: boolean;
    empty?: boolean;
    status_label?: string;
    latest_reply?: string;
    latest_reply_full?: string;
    recent_sessions?: LauncherRecentSession[];
  };
  notification?: {
    has_unread?: boolean;
    latest_message?: { status?: string; content?: string };
  };
  tts?: {
    enabled?: boolean;
    provider?: string;
    ok?: boolean;
    message?: string;
    error?: string;
  };
  proactive?: {
    enabled?: boolean;
    has_attention?: boolean;
    session_id?: string;
    message?: string;
    result?: string;
    attention_text?: string;
    attention_source?: string;
    error?: string;
  };
  launcher?: {
    has_attention?: boolean;
    latest_status?: string;
    status_label?: string;
    latest_reply?: string;
    latest_reply_full?: string;
    avatar_url?: string;
    default_display?: string;
    expand_trigger?: string;
    show_unread_dot?: boolean;
    auto_hide?: boolean;
    opacity?: number;
    suppress_status_dot?: boolean;
    show_reply_bubble?: boolean;
    enable_quick_input?: boolean;
    click_action?: string;
    default_open_behavior?: string;
    position_anchor?: string;
    preview_url?: string;
    scale?: number;
    mouse_follow_enabled?: boolean;
    render_quality_preset?: string;
    render_fps?: number;
    render_resolution?: number;
    hit_region_precision?: string;
    renderer?: {
      enabled?: boolean;
      model_url?: string;
      reason?: string;
      scale?: number;
      idle_motion_group?: string;
      enable_expressions?: boolean;
      enable_physics?: boolean;
      expression_mappings?: Record<string, string>;
      expression_keywords?: Record<string, string>;
      expressions?: Array<{ name?: string; file?: string }>;
      motion_groups?: Record<string, Array<Record<string, unknown>>>;
    };
    resource?: {
      available?: boolean;
      state?: string;
      display_name?: string;
      status_label?: string;
      help_text?: string;
      default_assets_root_display?: string;
      renderer_entry?: string;
    };
  };
};
