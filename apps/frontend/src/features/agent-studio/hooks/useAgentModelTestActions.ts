import { testYachiyoStudioAgentModel } from '../../yachiyo-studio/api';

type UseAgentModelTestActionsOptions = {
  draftAgentId: string;
  setStatus: (message: string) => void;
};

export function useAgentModelTestActions({
  draftAgentId,
  setStatus,
}: UseAgentModelTestActionsOptions) {
  async function testAgentModel() {
    if (!draftAgentId) return;
    const result = await testYachiyoStudioAgentModel(draftAgentId);
    setStatus(result.message || (result.ok ? '模型测试通过' : '模型测试失败'));
  }

  return {
    testAgentModel,
  };
}
