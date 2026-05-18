import { apiDelete, apiGet, apiPatch, apiPost } from './bridge';

export type ModelCapability = 'chat' | 'vision' | 'tts';

export type ModelProfile = {
  profile_id: string;
  source_id?: string;
  name: string;
  capability: ModelCapability;
  provider: 'openai_compatible' | string;
  base_url?: string;
  model?: string;
  api_key_configured?: boolean;
  source_name?: string;
  source_provider?: string;
  options?: Record<string, unknown>;
  enabled?: boolean;
  status?: 'untested' | 'available' | 'failed' | string;
  last_tested_at?: string;
  last_error?: string;
  created_at?: string;
  updated_at?: string;
};

export type ModelSource = {
  source_id: string;
  name: string;
  provider: 'openai_compatible' | string;
  base_url?: string;
  api_key_configured?: boolean;
  options?: Record<string, unknown>;
  enabled?: boolean;
  status?: 'untested' | 'available' | 'failed' | string;
  last_tested_at?: string;
  last_error?: string;
  created_at?: string;
  updated_at?: string;
  models?: ModelProfile[];
};

export type ModelProfileDefaults = Partial<Record<ModelCapability, string>>;

export type ModelProfilesPayload = {
  ok?: boolean;
  sources?: ModelSource[];
  profiles?: ModelProfile[];
  defaults?: ModelProfileDefaults;
};

export type ModelProfileRequest = {
  source_id?: string;
  name?: string;
  capability?: ModelCapability;
  provider?: string;
  base_url?: string;
  model?: string;
  api_key?: string;
  options?: Record<string, unknown>;
  enabled?: boolean;
};

export type ModelSourceRequest = {
  name?: string;
  provider?: string;
  base_url?: string;
  api_key?: string;
  options?: Record<string, unknown>;
  enabled?: boolean;
};

export type RemoteModelInfo = {
  id: string;
  canonical_slug?: string;
  context_length?: number;
  default_parameters?: Record<string, unknown>;
  description?: string;
  input_modalities?: string[];
  is_free?: boolean;
  is_moderated?: boolean;
  max_completion_tokens?: number;
  modality?: string;
  name?: string;
  owned_by?: string;
  output_modalities?: string[];
  pricing?: Record<string, string | number | null | undefined>;
  provider_key?: string;
  supported_parameters?: string[];
};

export async function listModelProfiles(): Promise<ModelProfilesPayload> {
  return apiGet('/ui/model-profiles');
}

export async function listModelSources(): Promise<{ ok?: boolean; sources?: ModelSource[] }> {
  return apiGet('/ui/model-sources');
}

export async function createModelSource(request: ModelSourceRequest): Promise<ModelSource> {
  return apiPost('/ui/model-sources', request);
}

export async function updateModelSource(sourceId: string, request: ModelSourceRequest): Promise<ModelSource> {
  return apiPatch(`/ui/model-sources/${encodeURIComponent(sourceId)}`, request);
}

export async function deleteModelSource(sourceId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/ui/model-sources/${encodeURIComponent(sourceId)}`);
}

export async function testModelSource(sourceId: string, model?: string): Promise<{
  ok?: boolean;
  success?: boolean;
  message?: string;
  missing?: string[];
  latency_ms?: number;
  source?: ModelSource;
}> {
  return apiPost(`/ui/model-sources/${encodeURIComponent(sourceId)}/test`, model ? { model } : {});
}

export async function fetchModelSourceModels(sourceId: string): Promise<{
  ok?: boolean;
  models?: RemoteModelInfo[];
  count?: number;
  source?: ModelSource;
}> {
  return apiPost(`/ui/model-sources/${encodeURIComponent(sourceId)}/models/fetch`);
}

export async function createModelProfile(request: ModelProfileRequest): Promise<ModelProfile> {
  return apiPost('/ui/model-profiles', request);
}

export async function updateModelProfile(profileId: string, request: ModelProfileRequest): Promise<ModelProfile> {
  return apiPatch(`/ui/model-profiles/${encodeURIComponent(profileId)}`, request);
}

export async function deleteModelProfile(profileId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/ui/model-profiles/${encodeURIComponent(profileId)}`);
}

export async function testModelProfile(profileId: string): Promise<{
  ok?: boolean;
  success?: boolean;
  message?: string;
  missing?: string[];
  latency_ms?: number;
  profile?: ModelProfile;
}> {
  return apiPost(`/ui/model-profiles/${encodeURIComponent(profileId)}/test`);
}

export async function updateModelProfileDefaults(defaults: ModelProfileDefaults): Promise<{ ok?: boolean; defaults?: ModelProfileDefaults }> {
  return apiPatch('/ui/model-profiles/defaults', defaults);
}
