import { useCallback, useEffect, useState } from 'react';

import { getYachiyoStudioToolCatalog } from '../../yachiyo-studio/api';
import type { ToolCatalogSnapshot } from '../../yachiyo-studio/types';

export function useAgentToolCatalog() {
  const [toolCatalog, setToolCatalog] = useState<ToolCatalogSnapshot | null>(null);
  const [toolCatalogLoading, setToolCatalogLoading] = useState(true);
  const [toolCatalogError, setToolCatalogError] = useState('');

  const reloadToolCatalog = useCallback(async () => {
    setToolCatalogLoading(true);
    setToolCatalogError('');
    try {
      setToolCatalog(await getYachiyoStudioToolCatalog());
    } catch (err) {
      setToolCatalogError(err instanceof Error ? err.message : 'Tool catalog unavailable');
    } finally {
      setToolCatalogLoading(false);
    }
  }, []);

  useEffect(() => {
    void reloadToolCatalog();
  }, [reloadToolCatalog]);

  return {
    reloadToolCatalog,
    toolCatalog,
    toolCatalogError,
    toolCatalogLoading,
  };
}
