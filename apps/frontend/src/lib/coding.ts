import { apiGet, apiPatch, apiPost } from './bridge';

const DRAFT_STORAGE_KEY = 'hermes.coding.pendingDraft';
export const CODING_REPO_STORAGE_KEY = 'hermes.coding.repoPath';

export type ProviderAvailability =
  | 'available'
  | 'not_installed'
  | 'not_authenticated'
  | 'subscription_required'
  | 'unsupported_platform'
  | 'misconfigured'
  | 'disabled_by_user'
  | 'unknown_error'
  | string;

export type CodingProviderStatus = {
  id: string;
  display_name: string;
  role: 'coding' | 'review' | 'design' | 'mock' | string;
  availability: ProviderAvailability;
  version?: string;
  executable_path?: string;
  blocking_reason?: string;
  install_hint?: string;
  auth_hint?: string;
  docs_url?: string;
  can_install_from_ui?: boolean;
  can_open_docs?: boolean;
  installable?: boolean;
  installed?: boolean;
  auth_required?: boolean;
  actions?: CodingProviderAction[];
  install_progress?: Record<string, unknown>;
  risk_level?: 'low' | 'medium' | 'high' | string;
  capabilities?: Record<string, unknown>;
};

export type CodingProviderAction = {
  id: 'install' | 'upgrade' | 'auth' | string;
  label: string;
  kind?: 'command' | 'terminal' | 'noop' | string;
  available?: boolean;
  command_preview?: string;
  confirmation?: string;
};

export type CodingJobStatus =
  | 'draft'
  | 'planning'
  | 'blocked'
  | 'awaiting_approval'
  | 'running'
  | 'reviewing'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | string;

export type CodingJobBlocker = {
  provider_id?: string;
  reason?: string;
  message?: string;
  suggested_actions?: Array<{ type?: string; label?: string; payload?: Record<string, unknown> }>;
};

export type CodingJob = {
  ok?: boolean;
  job_id: string;
  status: CodingJobStatus;
  user_request: string;
  repo_path: string;
  task_type: string;
  preferred_provider?: string;
  selected_provider?: string;
  review_strategy?: string;
  selected_review_provider?: string;
  design_mode?: string;
  writable_scopes?: string[];
  readonly_scopes?: string[];
  branch_name?: string;
  original_branch?: string;
  risk_level?: 'low' | 'medium' | 'high' | string;
  requires_approval?: boolean;
  plan_summary?: string;
  blockers?: CodingJobBlocker[];
  fallback_options?: Array<{ id?: string; label?: string; consequence?: string }>;
  dirty_summary?: { dirty?: boolean; count?: number; files?: string[]; status?: Record<string, string> };
  changed_files?: string[];
  artifacts?: Array<{ path: string; size?: number }>;
  error?: string;
  created_at?: string;
  updated_at?: string;
  approved_at?: string | null;
  completed_at?: string | null;
};

export type CodingArtifact = {
  path: string;
  size?: number;
  updated_at?: string;
  content?: string;
};

export type CodingConfig = {
  ok?: boolean;
  default_repo_path: string;
  default_writable_scopes: string[];
  default_provider: string;
  default_review_strategy: string;
  default_design_mode: string;
  hapi_url?: string;
  opendesign_artifact_dir?: string;
  opendesign_daemon_url?: string;
  opendesign_web_url?: string;
  opendesign_auth_token?: string;
  opendesign_auth_token_configured?: boolean;
  opendesign_app_path?: string;
  opendesign_auto_start?: boolean;
  claude_credential_mode?: string;
  anthropic_base_url?: string;
  anthropic_model?: string;
  anthropic_api_key?: string;
  anthropic_api_key_configured?: boolean;
  codex_credential_mode?: string;
  codex_base_url?: string;
  codex_model?: string;
  codex_api_key?: string;
  codex_api_key_configured?: boolean;
  config_path?: string;
};

export type CodingProviderConfigTest = {
  ok?: boolean;
  success?: boolean;
  provider_id: string;
  available?: boolean;
  status?: CodingProviderStatus;
  credential_mode?: string;
  isolated_auth?: boolean;
  api_key_configured?: boolean;
  base_url_configured?: boolean;
  model?: string;
  model_configured?: boolean;
  env_keys?: string[];
  checks?: Array<{ label: string; status: 'pass' | 'warn' | 'fail' | string; detail?: string }>;
  api_compatibility?: Record<string, unknown> | null;
  message?: string;
  error?: string;
};

export type CodingProviderInstall = {
  ok?: boolean;
  install_id: string;
  provider_id: string;
  action: string;
  label?: string;
  kind?: string;
  status: 'running' | 'completed' | 'failed' | string;
  command_preview?: string;
  confirmation?: string;
  lines?: string[];
  line_count?: number;
  truncated?: boolean;
  started_at?: string;
  finished_at?: string | null;
  returncode?: number | null;
  error?: string;
};

export type CreateCodingJobRequest = {
  user_request: string;
  repo_path: string;
  task_type: string;
  writable_scopes: string[];
  readonly_scopes?: string[];
  design_mode?: string;
  preferred_provider?: string;
  review_strategy?: string;
};

export type UpdateCodingConfigRequest = Partial<Omit<CodingConfig, 'ok' | 'config_path'>>;

export async function getCodingConfig(): Promise<CodingConfig> {
  return apiGet<CodingConfig>('/ui/coding/config');
}

export async function updateCodingConfig(request: UpdateCodingConfigRequest): Promise<CodingConfig> {
  return apiPatch<CodingConfig>('/ui/coding/config', request);
}

export async function getCodingProviders(): Promise<CodingProviderStatus[]> {
  const payload = await apiGet<{ providers?: CodingProviderStatus[] }>('/ui/coding/providers');
  return payload.providers || [];
}

export async function getReviewProviders(): Promise<CodingProviderStatus[]> {
  const payload = await apiGet<{ providers?: CodingProviderStatus[] }>('/ui/coding/review-providers');
  return payload.providers || [];
}

export async function installCodingProvider(providerId: string, action = 'install'): Promise<CodingProviderInstall> {
  return apiPost<CodingProviderInstall>(`/ui/coding/providers/${encodeURIComponent(providerId)}/install`, { action });
}

export async function testCodingProviderConfig(providerId: string): Promise<CodingProviderConfigTest> {
  return apiPost<CodingProviderConfigTest>(`/ui/coding/providers/${encodeURIComponent(providerId)}/test-config`);
}

export async function getCodingProviderInstall(installId: string): Promise<CodingProviderInstall> {
  return apiGet<CodingProviderInstall>(`/ui/coding/provider-installs/${encodeURIComponent(installId)}`);
}

export async function listCodingJobs(limit = 50): Promise<CodingJob[]> {
  const payload = await apiGet<{ jobs?: CodingJob[] }>(`/ui/coding/jobs?limit=${encodeURIComponent(String(limit))}`);
  return payload.jobs || [];
}

export async function createCodingJob(request: CreateCodingJobRequest): Promise<CodingJob> {
  return apiPost<CodingJob>('/ui/coding/jobs', request);
}

export async function getCodingJob(jobId: string): Promise<CodingJob> {
  return apiGet<CodingJob>(`/ui/coding/jobs/${encodeURIComponent(jobId)}`);
}

export async function approveCodingJob(jobId: string): Promise<CodingJob> {
  return apiPost<CodingJob>(`/ui/coding/jobs/${encodeURIComponent(jobId)}/approve`);
}

export async function cancelCodingJob(jobId: string): Promise<CodingJob> {
  return apiPost<CodingJob>(`/ui/coding/jobs/${encodeURIComponent(jobId)}/cancel`);
}

export async function getCodingArtifacts(jobId: string): Promise<CodingArtifact[]> {
  const payload = await apiGet<{ artifacts?: CodingArtifact[] }>(`/ui/coding/jobs/${encodeURIComponent(jobId)}/artifacts`);
  return payload.artifacts || [];
}

export function seedCodingDraftFromChat(text: string) {
  const value = text.trim();
  if (value) window.localStorage.setItem(DRAFT_STORAGE_KEY, value);
}

export function consumeSeededCodingDraft(): string {
  return window.localStorage.getItem(DRAFT_STORAGE_KEY) || '';
}

export function clearSeededCodingDraft() {
  window.localStorage.removeItem(DRAFT_STORAGE_KEY);
}
