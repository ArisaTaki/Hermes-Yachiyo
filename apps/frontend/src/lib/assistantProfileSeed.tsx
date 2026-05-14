import { createContext, useContext } from 'react';

export type AssistantProfileSeed = {
  agent_name?: string;
  agent_nickname?: string;
  agent_avatar_url?: string;
  user_avatar_url?: string;
};

export const AssistantProfileSeedContext = createContext<AssistantProfileSeed | null>(null);

export function useAssistantProfileSeed() {
  return useContext(AssistantProfileSeedContext);
}
