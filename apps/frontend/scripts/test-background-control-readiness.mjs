import assert from 'node:assert/strict';
import { createServer } from 'vite';

const server = await createServer({
  root: process.cwd(),
  logLevel: 'error',
  appType: 'custom',
  server: { middlewareMode: true },
});

try {
  const {
    backgroundControlReadiness,
    chatDesktopPermissionNotice,
  } = await server.ssrLoadModule('/src/features/yachiyo-chat/readiness.ts');

  const snapshot = (provider, desktopExecution = {}) => ({
    capabilities: {
      sandbox_provider: provider,
      desktop_execution: desktopExecution,
    },
  });
  const readyProvider = {
    provider_kind: 'background_desktop',
    configured: true,
    available: true,
    adapter_ready: true,
    status: 'available',
    foreground_takeover_required: false,
    blocking_conditions: [],
    health: { checked: true, ok: true, blocking_conditions: [] },
  };
  const installedUncheckedProvider = {
    ...readyProvider,
    available: false,
    adapter_ready: false,
    status: 'installed_not_checked',
    health: { checked: false, ok: false, blocking_conditions: [] },
  };

  const cases = [
    ['fully attested provider', readyProvider, 'ready'],
    ['missing availability', { ...readyProvider, available: undefined }, 'attention'],
    ['adapter unavailable', { ...readyProvider, adapter_ready: false }, 'attention'],
    ['missing foreground attestation', { ...readyProvider, foreground_takeover_required: undefined }, 'attention'],
    ['setup required', { ...readyProvider, configured: false }, 'setup_required'],
    ['installed but unchecked', installedUncheckedProvider, 'installed_unchecked'],
    ['non-background provider', { ...readyProvider, provider_kind: 'local_desktop' }, 'unknown'],
  ];

  for (const [name, provider, expected] of cases) {
    assert.equal(
      backgroundControlReadiness(snapshot(provider)).status,
      expected,
      name,
    );
  }

  assert.equal(
    chatDesktopPermissionNotice(
      snapshot(installedUncheckedProvider, {
        unavailable_tools: ['desktop.click'],
        blocking_conditions: ['desktop_permission_diagnostics_not_checked'],
      }),
    ),
    null,
    'an installed-but-unchecked background provider must not create a chat warning',
  );

  console.log('background-control readiness matrix: 8 assertions passed');
} finally {
  await server.close();
}
