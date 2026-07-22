import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

import ts from 'typescript';

function loadTypeScriptModule(relativePath) {
  const moduleUrl = new URL(relativePath, import.meta.url);
  const source = readFileSync(moduleUrl, 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: fileURLToPath(moduleUrl),
  }).outputText;
  const loaded = { exports: {} };
  vm.runInNewContext(output, {
    exports: loaded.exports,
    module: loaded,
    require: createRequire(moduleUrl),
  }, { filename: fileURLToPath(moduleUrl) });
  return loaded.exports;
}

const {
  consumerFailureText,
  consumerMessageFailurePresentation,
  consumerTaskFailurePresentation,
} = loadTypeScriptModule('../src/features/yachiyo-chat/consumerFailure.ts');

test('cancelled messages ignore cleared approval metadata', () => {
  const presentation = consumerMessageFailurePresentation({
    role: 'assistant',
    status: 'cancelled',
    metadata: { pending_approval: {} },
  });

  assert.equal(presentation.kind, 'cancelled');
});

test('cancelled run metadata overrides contradictory failed message status', () => {
  const presentation = consumerMessageFailurePresentation({
    role: 'assistant',
    status: 'failed',
    error: 'Cancelled by user from Chat UI smoke.',
    metadata: { run_status: 'cancelled' },
  });

  assert.equal(presentation.kind, 'cancelled');
});

test('failed messages require an actionable approval id', () => {
  const presentation = consumerMessageFailurePresentation({
    role: 'assistant',
    status: 'failed',
    error: 'provider profile missing',
    metadata: {
      pending_approval: {},
      run_status: 'approval_required',
    },
  });

  assert.equal(presentation.kind, 'unknown');
});

test('failed messages preserve actionable approval requests', () => {
  const presentation = consumerMessageFailurePresentation({
    role: 'assistant',
    status: 'failed',
    metadata: {
      pending_approval: { approval_id: 'approval-public-1' },
      run_status: 'approval_required',
    },
  });

  assert.equal(presentation.kind, 'approval_required');
});

test('task approval status is not actionable without a real approval id', () => {
  const presentation = consumerTaskFailurePresentation({
    status: 'waiting_approval',
    pending_approvals: [{ approval_id: '', status: 'pending' }],
  });

  assert.equal(presentation.kind, 'unknown');
});

test('failed run metadata does not hide a media no-match outcome', () => {
  const presentation = consumerMessageFailurePresentation({
    role: 'assistant',
    status: 'failed',
    error: '没能直接播放超时空辉夜姬相关的音乐，但已打开 Apple Music 搜索',
    metadata: { run_status: 'failed' },
  });

  assert.equal(presentation.kind, 'content_not_found');
});

test('permission nouns in media titles stay content no-match outcomes', () => {
  const cases = [
    '没有找到歌曲 Camera',
    'Could not find the track Camera',
    'Microphone song had no results',
    'The Automation album was not found',
  ];

  for (const error of cases) {
    const presentation = consumerMessageFailurePresentation({
      role: 'assistant',
      status: 'failed',
      error,
    });
    assert.equal(presentation.kind, 'content_not_found', error);
  }
});

test('permission failures remain actionable when permission context is explicit', () => {
  const cases = [
    'Camera permission denied',
    'Accessibility access is missing',
    '需要授予屏幕录制权限',
  ];

  for (const error of cases) {
    const presentation = consumerMessageFailurePresentation({
      role: 'assistant',
      status: 'failed',
      error,
    });
    assert.equal(presentation.kind, 'permission_required', error);
  }
});

test('structured permission failures take precedence over verification failures', () => {
  const presentation = consumerTaskFailurePresentation({
    status: 'failed',
    task_progress: { failed_verification_count: 1 },
    recent_events: [{
      event_type: 'agent.tool.failed',
      payload: {
        result: {
          missing_permissions: ['accessibility'],
          permission_error: true,
        },
      },
    }],
  });

  assert.equal(presentation.kind, 'permission_required');
});

test('verification-failed copy requires an actually executed tool call', () => {
  const presentation = consumerTaskFailurePresentation({
    status: 'failed',
    task_progress: { failed_verification_count: 1 },
    recent_events: [{
      event_type: 'agent.desktop.intent_unavailable',
      payload: {
        tool: 'app.open',
        status: 'blocked',
        reason: 'runtime_execution_not_ready',
        blocked_by: 'installed_not_checked',
        blocked_summary: '后台 Provider 已安装，但当前尚未完成就绪检查；还没有真正执行桌面操作。',
      },
    }],
    tool_calls: [],
  });

  assert.equal(presentation.kind, 'unknown');
  assert.equal(consumerFailureText(presentation).includes('操作可能已经发生'), false);
});

test('common media no-match wording stays a content outcome', () => {
  const cases = [
    '没搜到对应歌曲，已打开音乐应用',
    'Could not play the requested song; opened Apple Music search instead',
    'Apple Music search returned zero results for that song',
    'Playback search found no playable match',
    'Apple Music library has no matching item',
  ];

  for (const error of cases) {
    const presentation = consumerMessageFailurePresentation({
      role: 'assistant',
      status: 'failed',
      error,
      metadata: { run_status: 'failed' },
    });
    assert.equal(presentation.kind, 'content_not_found', error);
  }
});

test('macOS application not-found wording stays an app outcome', () => {
  const presentation = consumerMessageFailurePresentation({
    role: 'assistant',
    status: 'failed',
    error: "Application 'Calculator' could not be found",
  });

  assert.equal(presentation.kind, 'app_not_found');
});

test('UI element not-found wording stays a target outcome', () => {
  const presentation = consumerMessageFailurePresentation({
    role: 'assistant',
    status: 'failed',
    error: 'Could not find the Save button',
  });

  assert.equal(presentation.kind, 'target_not_found');
});

test('consumer artifact presentation never exposes an internal path as its label or tooltip', () => {
  const {
    runtimeArtifactPresentation,
  } = loadTypeScriptModule('../src/features/runtime-shared/artifactPresentation.ts');
  const internalPath = '/private/runs/run-secret/tool-calls/call-secret/result.json';

  const presentation = runtimeArtifactPresentation({
    kind: 'json',
    path: internalPath,
  }, 'consumer');

  assert.equal(presentation.label, '文件结果');
  assert.equal(presentation.tooltip, '');
  assert.equal(presentation.label.includes(internalPath), false);
});

test('consumer artifact read errors hide backend diagnostics', () => {
  const {
    runtimeArtifactReadError,
  } = loadTypeScriptModule('../src/features/runtime-shared/artifactPresentation.ts');
  const rawError = 'HTTP 500: provider profile missing; source_run_id=run-secret';

  const message = runtimeArtifactReadError({ message: rawError }, 'consumer');

  assert.equal(message, '暂时无法打开这个结果，请重试。');
  assert.equal(message.includes('provider'), false);
  assert.equal(message.includes('run-secret'), false);
});

test('diagnostic artifact presentation preserves paths and backend errors', () => {
  const {
    runtimeArtifactPresentation,
    runtimeArtifactReadError,
  } = loadTypeScriptModule('../src/features/runtime-shared/artifactPresentation.ts');
  const internalPath = '/private/runs/run-debug/result.json';
  const rawError = 'HTTP 500: provider debug detail';

  const presentation = runtimeArtifactPresentation({ kind: 'json', path: internalPath }, 'diagnostic');

  assert.equal(presentation.label, internalPath);
  assert.equal(presentation.tooltip, internalPath);
  assert.equal(runtimeArtifactReadError({ message: rawError }, 'diagnostic'), rawError);
});

test('consumer RuntimeArtifactPreview renders a safe visible label without a path tooltip', async () => {
  const [{ createElement }, { renderToStaticMarkup }, { createServer }] = await Promise.all([
    import('react'),
    import('react-dom/server'),
    import('vite'),
  ]);
  const root = fileURLToPath(new URL('../', import.meta.url));
  const server = await createServer({
    appType: 'custom',
    logLevel: 'silent',
    root,
    server: { middlewareMode: true },
  });
  try {
    const { RuntimeArtifactPreview } = await server.ssrLoadModule(
      '/src/features/runtime-shared/components/RuntimeArtifactPreview.tsx',
    );
    const html = renderToStaticMarkup(createElement(RuntimeArtifactPreview, {
      artifact: {
        artifact_id: 'artifact-public-1',
        kind: 'json',
        path: '/private/runs/run-secret/tool-calls/call-secret/result.json',
      },
      presentationMode: 'consumer',
    }));

    assert.match(html, /<strong>文件结果<\/strong>/);
    assert.doesNotMatch(html, /title="[^"]*run-secret/);
  } finally {
    await server.close();
  }
});

test('consumer RuntimeReadableArtifactPreview keeps its trigger path-free', async () => {
  const [{ createElement }, { renderToStaticMarkup }, { createServer }] = await Promise.all([
    import('react'),
    import('react-dom/server'),
    import('vite'),
  ]);
  const root = fileURLToPath(new URL('../', import.meta.url));
  const server = await createServer({
    appType: 'custom',
    logLevel: 'silent',
    root,
    server: { middlewareMode: true },
  });
  try {
    const { RuntimeReadableArtifactPreview } = await server.ssrLoadModule(
      '/src/features/runtime-shared/components/RuntimeReadableArtifactPreview.tsx',
    );
    const html = renderToStaticMarkup(createElement(RuntimeReadableArtifactPreview, {
      artifact: {
        artifact_id: 'artifact-public-2',
        kind: 'json',
        path: '/private/runs/run-secret/tool-calls/call-secret/result.json',
      },
      presentationMode: 'consumer',
      readArtifact: async () => ({ content: '{}' }),
    }));

    assert.match(html, /<strong>文件结果<\/strong>/);
    assert.doesNotMatch(html, /title="[^"]*run-secret/);
  } finally {
    await server.close();
  }
});

test('chat AgentTaskCard renders partial artifacts through the consumer presentation mode', async () => {
  const [{ createElement }, { renderToStaticMarkup }, { createServer }] = await Promise.all([
    import('react'),
    import('react-dom/server'),
    import('vite'),
  ]);
  const root = fileURLToPath(new URL('../', import.meta.url));
  const server = await createServer({
    appType: 'custom',
    logLevel: 'silent',
    root,
    server: { middlewareMode: true },
  });
  try {
    const { AgentTaskCard } = await server.ssrLoadModule(
      '/src/features/yachiyo-chat/components/AgentTaskCard.tsx',
    );
    const html = renderToStaticMarkup(createElement(AgentTaskCard, {
      surface: 'chat',
      task: {
        task_id: 'task-public-1',
        status: 'failed',
        artifacts: [{
          artifact_id: 'artifact-public-3',
          kind: 'json',
          path: '/private/runs/run-secret/tool-calls/call-secret/result.json',
        }],
      },
    }));

    assert.match(html, /<strong>文件结果<\/strong>/);
    assert.doesNotMatch(html, /title="[^"]*run-secret/);
  } finally {
    await server.close();
  }
});

test('task AgentTaskCard preserves diagnostic artifact paths', async () => {
  const [{ createElement }, { renderToStaticMarkup }, { createServer }] = await Promise.all([
    import('react'),
    import('react-dom/server'),
    import('vite'),
  ]);
  const root = fileURLToPath(new URL('../', import.meta.url));
  const server = await createServer({
    appType: 'custom',
    logLevel: 'silent',
    root,
    server: { middlewareMode: true },
  });
  try {
    const { AgentTaskCard } = await server.ssrLoadModule(
      '/src/features/yachiyo-chat/components/AgentTaskCard.tsx',
    );
    const internalPath = '/private/runs/run-debug/result.json';
    const html = renderToStaticMarkup(createElement(AgentTaskCard, {
      surface: 'task',
      task: {
        task_id: 'task-debug-1',
        status: 'failed',
        artifacts: [{ artifact_id: 'artifact-debug-1', kind: 'json', path: internalPath }],
      },
    }));

    assert.match(html, new RegExp(`<strong>${internalPath.replaceAll('/', '\\/')}<\\/strong>`));
    assert.match(html, /title="[^"]*run-debug/);
  } finally {
    await server.close();
  }
});

test('unknown technical failures never echo provider or source diagnostics in consumer copy', () => {
  const rawError = 'HTTP 500: provider profile missing; source_run_id=run-secret; tool_call_id=call-secret';
  const presentation = consumerMessageFailurePresentation({
    role: 'assistant',
    status: 'failed',
    error: rawError,
    metadata: { run_status: 'failed' },
  });
  const visibleText = consumerFailureText(presentation);

  assert.equal(presentation.kind, 'unknown');
  assert.equal(visibleText.includes('provider'), false);
  assert.equal(visibleText.includes('source_run_id'), false);
  assert.equal(visibleText.includes('run-secret'), false);
  assert.equal(visibleText.includes('call-secret'), false);
});

test('launcher consumer projection hides runtime chrome and only promotes actionable states', async () => {
  const [{ createElement }, { renderToStaticMarkup }, { createServer }] = await Promise.all([
    import('react'),
    import('react-dom/server'),
    import('vite'),
  ]);
  const root = fileURLToPath(new URL('../', import.meta.url));
  const server = await createServer({
    appType: 'custom',
    logLevel: 'silent',
    root,
    server: { middlewareMode: true },
  });
  try {
    const { LauncherAgentTaskLight } = await server.ssrLoadModule(
      '/src/features/yachiyo-chat/components/LauncherAgentTaskLight.tsx',
    );
    const runningTask = {
      task_id: 'task-launcher-running',
      conversation_id: 'session-launcher-running',
      title: '打开音乐并播放歌曲',
      status: 'running',
      needs_user_action: false,
      tool_calls: [{ tool_name: 'media.apple_music_play', status: 'running', risk_level: 'high' }],
      task_progress: {
        needs_replan: true,
        failed_verification_count: 1,
        blocked_todos: 2,
      },
      runtime_debug: {
        blocked_tool_call_count: 2,
        needs_replan: true,
      },
      runtime_execution_envelope: {
        requests: [{ request_id: 'request-secret', tool_name: 'media.apple_music_play', risk_level: 'high' }],
      },
      replan_recoveries: [{
        request_id: 'replan-secret',
        status: 'pending',
        recovery_actions: [{
          action_id: 'recovery-secret',
          tool: 'browser.search',
          prompt: 'Retry Apple Music with resolved title',
        }],
      }],
    };

    const bubbleRunning = renderToStaticMarkup(createElement(LauncherAgentTaskLight, {
      mode: 'bubble',
      task: runningTask,
    }));
    assert.equal(bubbleRunning, '');

    const live2dRunning = renderToStaticMarkup(createElement(LauncherAgentTaskLight, {
      mode: 'live2d',
      task: runningTask,
    }));
    assert.match(live2dRunning, /live2d-launcher-agent-task-compact/);
    assert.match(live2dRunning, /处理中/);
    assert.equal((live2dRunning.match(/<i><\/i>/g) || []).length, 3);
    assert.doesNotMatch(live2dRunning, /Runtime Debug|Agent Studio|exec|todo|replan|verify|risk|apple_music|browser\.search/i);

    const completed = renderToStaticMarkup(createElement(LauncherAgentTaskLight, {
      mode: 'live2d',
      task: {
        ...runningTask,
        status: 'completed',
        needs_user_action: true,
        pending_approvals: [{
          approval_id: 'stale-completed-approval',
          status: 'pending',
          title: 'stale approval',
        }],
      },
    }));
    assert.equal(completed, '');

    const approval = renderToStaticMarkup(createElement(LauncherAgentTaskLight, {
      mode: 'bubble',
      onApproveApproval: () => undefined,
      onRejectApproval: () => undefined,
      task: {
        ...runningTask,
        status: 'waiting_approval',
        needs_user_action: true,
        pending_approvals: [{
          approval_id: 'approval-public',
          run_id: 'run-public',
          status: 'pending',
          title: 'workspace.write_patch high risk approval',
          tool_name: 'workspace.write_patch',
          risk_level: 'high',
        }],
        recent_events: [],
        tool_calls: [],
      },
    }));
    assert.match(approval, /需要你的确认/);
    assert.match(approval, /确认继续/);
    assert.match(approval, /拒绝/);
    assert.doesNotMatch(approval, /Runtime Debug|Agent Studio|workspace\.write_patch|high risk|exec|todo|replan|verify/i);

    const failed = renderToStaticMarkup(createElement(LauncherAgentTaskLight, {
      mode: 'bubble',
      task: {
        task_id: 'task-launcher-failed',
        title: '播放歌曲',
        status: 'failed',
        needs_user_action: true,
        pending_approvals: [{
          approval_id: 'stale-failed-approval',
          status: 'pending',
          title: 'stale approval',
        }],
        summary: 'provider profile missing; tool_call_id=secret',
      },
    }));
    assert.match(failed, /这次没有完成/);
    assert.match(failed, /请打开对话查看原因/);
    assert.doesNotMatch(failed, /需要你的确认|Agent Studio|provider profile|tool_call_id|secret|stale approval/);
  } finally {
    await server.close();
  }
});
