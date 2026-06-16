import { useRunLaunchActions } from './useRunLaunchActions';

type UseAgentStudioRunLaunchControlsOptions = Parameters<typeof useRunLaunchActions>[0];

export function useAgentStudioRunLaunchControls(options: UseAgentStudioRunLaunchControlsOptions) {
  return useRunLaunchActions(options);
}
