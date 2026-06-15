import {
  importSkill,
  installSkillCommand,
  syncNativeSkills,
  type SkillSourceRoot,
  type SkillSpec,
} from '../../../lib/agents';
import {
  localSourceAlias,
  normalizeSkillSources,
  syncResultsToImportResults,
  type SkillImportResult,
} from '../utils/skills';

type SkillImportRefreshOptions = {
  statusMessage?: string;
};

type UseSkillImportActionsOptions = {
  setSkillImportResults: (results: SkillImportResult[]) => void;
  setSkillSources: (sources: SkillSourceRoot[]) => void;
  skillInstallCommand: string;
  skillTargetFolderId: string;
  skills: SkillSpec[];
};

export function useSkillImportActions({
  setSkillImportResults,
  setSkillSources,
  skillInstallCommand,
  skillTargetFolderId,
  skills,
}: UseSkillImportActionsOptions) {
  async function importSkillSourceList(rawSources: string[]): Promise<SkillImportRefreshOptions | void> {
    const sources = normalizeSkillSources(rawSources);
    if (!sources.length) throw new Error('请先选择或拖入 Skill 目录/ZIP');
    const existingPaths = new Set(skills.flatMap((skill) => [skill.local_path, skill.source_path]).filter(Boolean).map(String));
    const results: SkillImportResult[] = [];
    for (const source of sources) {
      if (existingPaths.has(source) || existingPaths.has(localSourceAlias(source))) {
        results.push({ source, status: 'skipped', message: '已存在，跳过' });
        continue;
      }
      try {
        const imported = await importSkill(source, skillTargetFolderId);
        results.push({ source, status: 'success', message: `已导入 ${imported.name}` });
      } catch (err) {
        results.push({ source, status: 'failed', message: err instanceof Error ? err.message : '导入失败' });
      }
    }
    setSkillImportResults(results);
  }

  async function syncNativeSkillLibrary(): Promise<SkillImportRefreshOptions | void> {
    const result = await syncNativeSkills();
    setSkillImportResults(syncResultsToImportResults(result.results || []));
    if (result.roots) setSkillSources(result.roots);
  }

  async function installSkillFromCommand(): Promise<SkillImportRefreshOptions | void> {
    const command = skillInstallCommand.trim();
    if (!command) throw new Error('请输入 Skill 来源或安装命令');
    const result = await installSkillCommand(command, skillTargetFolderId);
    if (result.sync?.results) {
      setSkillImportResults(syncResultsToImportResults(result.sync.results));
    }
    if (!result.ok) {
      throw new Error(result.stderr || result.stdout || `安装命令退出：${result.returncode ?? 'unknown'}`);
    }
  }

  return {
    importSkillSourceList,
    installSkillFromCommand,
    syncNativeSkillLibrary,
  };
}
