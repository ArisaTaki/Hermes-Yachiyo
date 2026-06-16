import { useMemo } from 'react';

import type { ModelProfile } from '../../../lib/modelProfiles';

export function useAgentStudioModelProfiles(modelProfiles: ModelProfile[]) {
  const chatModelProfiles = useMemo(
    () => modelProfiles.filter((profile) => (
      profile.capability === 'chat'
      && profile.status === 'available'
      && profile.enabled !== false
    )),
    [modelProfiles],
  );
  const visionModelProfiles = useMemo(
    () => modelProfiles.filter((profile) => (
      profile.capability === 'vision'
      && profile.status === 'available'
      && profile.enabled !== false
    )),
    [modelProfiles],
  );
  return {
    chatModelProfiles,
    visionModelProfiles,
  };
}
