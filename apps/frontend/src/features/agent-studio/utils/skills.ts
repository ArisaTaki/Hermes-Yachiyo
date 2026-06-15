import type {
  SkillFolderSpec,
  SkillSourceRoot,
  SkillSpec,
  SkillSyncResult,
} from '../types';
import type {
  SkillFolderSnapshot,
  SkillSnapshot,
  SkillSourceRootSnapshot,
} from '../../yachiyo-studio/types';

export type SkillFolderFilter = 'all' | 'uncategorized' | string;
export type SkillImportResult = {
  source: string;
  status: 'success' | 'failed' | 'skipped' | 'updated' | 'imported';
  message: string;
};
export type SkillSourceFilter = 'installed' | 'native';

export const skillFolderNameMaxLength = 120;

export function publicSkillToSkillSpec(snapshot: SkillSnapshot): SkillSpec {
  return {
    skill_id: snapshot.skill_id,
    name: snapshot.name,
    description: snapshot.description || undefined,
    source_path: snapshot.source_path || undefined,
    local_path: snapshot.local_path || undefined,
    folder_id: snapshot.folder_id || undefined,
    folder_name: snapshot.folder_name || undefined,
    source_type: snapshot.source_type || undefined,
    origin_path: snapshot.origin_path || undefined,
    source_ref: snapshot.source_ref || undefined,
    content_hash: snapshot.content_hash || undefined,
    last_synced_at: snapshot.last_synced_at || undefined,
    sync_status: snapshot.sync_status || undefined,
    content_summary: snapshot.content_summary || undefined,
    skill_markdown: snapshot.skill_markdown || undefined,
    asset_paths: snapshot.asset_paths || [],
    enabled: snapshot.enabled,
    created_at: snapshot.created_at,
    updated_at: snapshot.updated_at,
  };
}

export function publicSkillFolderToSkillFolderSpec(snapshot: SkillFolderSnapshot): SkillFolderSpec {
  return {
    folder_id: snapshot.folder_id,
    name: snapshot.name,
    description: snapshot.description || undefined,
    source_scope: snapshot.source_scope,
    sort_order: snapshot.sort_order,
    skill_count: snapshot.skill_count,
    installed_count: snapshot.installed_count,
    native_count: snapshot.native_count,
    created_at: snapshot.created_at,
    updated_at: snapshot.updated_at,
  };
}

export function publicSkillSourceRootToSkillSourceRoot(snapshot: SkillSourceRootSnapshot): SkillSourceRoot {
  return {
    path: snapshot.path,
    source_type: snapshot.source_type,
    library: snapshot.library || undefined,
    exists: snapshot.exists,
    skill_count: snapshot.skill_count,
  };
}

export function normalizeSkillSources(sources: string[]): string[] {
  const cleanSources = sources
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(cleanSources));
}

export function skillPathLabel(skill: SkillSpec): string {
  return skill.local_path || skill.source_path || 'local skill';
}

export function skillSourceLabel(skill: SkillSpec): string {
  const sourceRef = String(skill.source_ref || '').trim();
  const sourceType = String(skill.source_type || '');
  if (sourceRef && sourceType === 'npx_skills') return sourceRef;
  if (sourceRef && /^https?:\/\//.test(sourceRef)) return sourceRef;
  return skill.origin_path || skill.source_path || sourceRef;
}

export function localSourceAlias(source: string): string {
  const clean = source.trim().replace(/[\\/]+$/, '');
  const name = clean.split(/[\\/]/).pop();
  return name ? `local:${name}` : '';
}

export function skillSourceTypeLabel(value?: string): string {
  if (value === 'native_global') return 'Native Global';
  if (value === 'native_project') return 'Native Project';
  if (value === 'npx_skills') return 'npx skills';
  if (value === 'local_zip') return 'Installed ZIP';
  return 'Installed Skill';
}

export function isNativeSkill(skill: SkillSpec): boolean {
  return skill.source_type === 'native_global' || skill.source_type === 'native_project';
}

export function isInstalledSkill(skill: SkillSpec): boolean {
  return !isNativeSkill(skill);
}

export function skillMatchesSourceFilter(skill: SkillSpec, filter: SkillSourceFilter): boolean {
  return filter === 'native' ? isNativeSkill(skill) : isInstalledSkill(skill);
}

export function skillMatchesFolderFilter(skill: SkillSpec, filter: SkillFolderFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'uncategorized') return !skill.folder_id;
  return skill.folder_id === filter;
}

export function skillMatchesQuery(skill: SkillSpec, query: string): boolean {
  const clean = query.trim().toLowerCase();
  if (!clean) return true;
  return [
    skill.name,
    skill.description,
    skill.content_summary,
    skill.source_ref,
    skill.source_path,
    skill.local_path,
    skill.origin_path,
    skill.folder_name,
  ].some((value) => String(value || '').toLowerCase().includes(clean));
}

export function skillResultStatusLabel(status: string): string {
  if (status === 'success' || status === 'imported') return '成功';
  if (status === 'updated') return '更新';
  if (status === 'skipped') return '跳过';
  return '失败';
}

export function syncResultsToImportResults(results: SkillSyncResult[] = []): SkillImportResult[] {
  return results.map((result) => ({
    source: result.source || result.source_ref || result.name || 'unknown',
    status: result.status === 'updated' ? 'updated' : result.status === 'imported' ? 'imported' : result.status === 'failed' ? 'failed' : 'skipped',
    message: result.message || result.name || result.status,
  }));
}

export function skillFolderNameError(name: string, folders: SkillFolderSpec[], currentFolderId = ''): string {
  const clean = name.trim();
  if (!clean) return '';
  if (clean.length > skillFolderNameMaxLength) return `文件夹名称不能超过 ${skillFolderNameMaxLength} 个字符`;
  const duplicate = folders.some((folder) => (
    folder.folder_id !== currentFolderId
    && folder.name.trim().toLowerCase() === clean.toLowerCase()
  ));
  return duplicate ? '已存在同名 Skill 文件夹' : '';
}
