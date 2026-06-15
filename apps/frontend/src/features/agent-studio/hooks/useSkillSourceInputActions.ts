import type { DragEvent } from 'react';

import { chooseSkillSources } from '../../../lib/bridge';

type SkillSourceInputRefreshOptions = {
  statusMessage?: string;
};

type UseSkillSourceInputActionsOptions = {
  importSkillSourceList: (rawSources: string[]) => Promise<SkillSourceInputRefreshOptions | void>;
  runAction: (action: () => Promise<SkillSourceInputRefreshOptions | void>, label: string) => void;
  setError: (message: string) => void;
};

export function useSkillSourceInputActions({
  importSkillSourceList,
  runAction,
  setError,
}: UseSkillSourceInputActionsOptions) {
  async function pickSkillSources() {
    setError('');
    try {
      const selected = await chooseSkillSources();
      if (selected.length) await runAction(() => importSkillSourceList(selected), '导入 Skills');
    } catch (err) {
      setError(err instanceof Error ? err.message : '选择 Skill 文件失败');
    }
  }

  function dropSkillSources(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    const filePaths = Array.from(event.dataTransfer.files)
      .map((file) => (file as File & { path?: string }).path || file.name)
      .filter(Boolean);
    if (filePaths.length) {
      void runAction(() => importSkillSourceList(filePaths), '导入 Skills');
    }
  }

  return {
    dropSkillSources,
    pickSkillSources,
  };
}
