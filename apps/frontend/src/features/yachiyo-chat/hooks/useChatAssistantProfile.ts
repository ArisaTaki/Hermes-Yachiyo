import { useCallback, useEffect, useRef, useState } from 'react';

import { useAssistantProfileSeed } from '../../../lib/assistantProfileSeed';
import { apiGet } from '../../../lib/bridge';
import {
  cachedAssistantProfileSnapshot,
  mergeAssistantProfileSeed,
  profileFromSeed,
  rememberAssistantProfile,
} from '../sessionState';
import type { AssistantProfilePayload } from '../types';

const ASSISTANT_PROFILE_UPDATED_EVENT = 'oha-assistant-profile-updated';

export function useChatAssistantProfile() {
  const assistantProfileSeed = useAssistantProfileSeed();
  const initialAssistantProfile = cachedAssistantProfileSnapshot() || profileFromSeed(assistantProfileSeed);
  const [assistantProfile, setAssistantProfile] = useState<AssistantProfilePayload | null>(() => initialAssistantProfile);
  const [assistantProfileLoading, setAssistantProfileLoading] = useState(() => !initialAssistantProfile);
  const assistantProfileSeedRef = useRef(assistantProfileSeed);

  const refreshAssistantProfile = useCallback(async () => {
    try {
      const profile = await apiGet<AssistantProfilePayload>('/assistant/profile');
      if (profile.ok === false) throw new Error('读取助手资料失败');
      setAssistantProfile(rememberAssistantProfile(profile));
    } catch {
      const fallback = cachedAssistantProfileSnapshot() || profileFromSeed(assistantProfileSeedRef.current);
      setAssistantProfile(fallback);
    } finally {
      setAssistantProfileLoading(false);
    }
  }, []);

  useEffect(() => {
    assistantProfileSeedRef.current = assistantProfileSeed;
    const seededProfile = profileFromSeed(assistantProfileSeed);
    if (!seededProfile) return;
    setAssistantProfile((current) => {
      const merged = mergeAssistantProfileSeed(current, seededProfile);
      return rememberAssistantProfile(merged);
    });
    setAssistantProfileLoading(false);
  }, [assistantProfileSeed]);

  useEffect(() => {
    const refreshProfile = () => void refreshAssistantProfile();
    window.addEventListener(ASSISTANT_PROFILE_UPDATED_EVENT, refreshProfile);
    return () => window.removeEventListener(ASSISTANT_PROFILE_UPDATED_EVENT, refreshProfile);
  }, [refreshAssistantProfile]);

  return {
    assistantProfile,
    assistantProfileLoading,
    refreshAssistantProfile,
  };
}
