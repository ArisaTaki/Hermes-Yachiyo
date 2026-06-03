# 轮询机制重构设计书

## 1. 背景与问题

### 1.1 当前实现

当前对话界面使用轮询机制来同步状态：

| 轮询目标 | 间隔 | 目的 |
|---------|------|------|
| 消息列表 | 500ms (处理中) / 3000ms (空闲) | 获取最新消息状态 |
| 会话列表 | 500ms (处理中) / 3000ms (空闲) | 获取最新会话状态 |
| Agent 列表 | 10000ms | 获取 Agent 信息更新 |
| 执行器状态 | 30000ms | 获取执行器状态 |

### 1.2 存在问题

1. **网络开销大**
   - 频繁的 HTTP 请求
   - 大量无效请求（状态未变化时）
   - 增加服务器负载

2. **实时性不足**
   - 最大延迟等于轮询间隔
   - 用户体验不够流畅

3. **资源浪费**
   - 客户端持续发送请求
   - 服务器持续处理请求
   - 带宽资源浪费

4. **扩展性差**
   - 用户增加时服务器压力线性增长
   - 难以支持更多实时功能

## 2. 目标与原则

### 2.1 设计目标

1. **减少网络开销**：降低 80% 以上的无效请求
2. **提高实时性**：消息状态变化时立即通知
3. **降低服务器负载**：减少服务器处理压力
4. **保持兼容性**：平滑迁移，不影响现有功能
5. **易于维护**：代码结构清晰，易于扩展

### 2.2 设计原则

1. **事件驱动**：基于事件推送，而非轮询
2. **按需订阅**：只订阅需要的事件
3. **优雅降级**：连接断开时自动回退到轮询
4. **向后兼容**：支持旧版本客户端

## 3. 技术方案

### 3.1 方案对比

| 方案 | 实时性 | 实现复杂度 | 服务器压力 | 浏览器兼容性 |
|------|--------|-----------|-----------|-------------|
| WebSocket | 高 | 高 | 低 | 好 |
| SSE (Server-Sent Events) | 高 | 中 | 低 | 好 |
| 长轮询 | 中 | 中 | 中 | 好 |
| 优化轮询 | 低 | 低 | 高 | 好 |

### 3.2 推荐方案：SSE + 优化轮询

**推荐理由**：
1. SSE 实现简单，浏览器原生支持
2. 服务器单向推送，适合消息通知场景
3. 自动重连机制，可靠性高
4. 与现有架构兼容性好

**回退策略**：
- SSE 连接失败时，自动回退到优化轮询
- 优化轮询间隔：空闲时 10 秒，处理中时 2 秒

## 4. 架构设计

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      客户端 (Frontend)                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ EventSource │  │   轮询管理器  │  │  状态管理器  │         │
│  │   Client    │  │   (回退)     │  │   (Store)   │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          │                                  │
│                          ▼                                  │
│                   ┌─────────────┐                           │
│                   │  消息分发器  │                           │
│                   └──────┬──────┘                           │
│                          │                                  │
│         ┌────────────────┼────────────────┐                 │
│         ▼                ▼                ▼                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ 消息状态更新 │  │ 会话状态更新 │  │ Agent 信息  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ SSE / HTTP
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      服务器 (Backend)                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ SSE 端点    │  │  事件总线    │  │  状态监控器  │         │
│  │ /events     │  │ (EventBus)  │  │             │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          │                                  │
│         ┌────────────────┼────────────────┐                 │
│         ▼                ▼                ▼                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ ChatAPI     │  │ AgentRuntime│  │ TaskRunner  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 事件类型设计

```typescript
// 事件类型定义
type EventType = 
  | 'message.created'      // 新消息创建
  | 'message.updated'      // 消息状态更新
  | 'message.completed'    // 消息处理完成
  | 'message.failed'       // 消息处理失败
  | 'session.created'      // 新会话创建
  | 'session.updated'      // 会话信息更新
  | 'session.switched'     // 切换会话
  | 'agent.updated'        // Agent 信息更新
  | 'agent.run.started'    // Agent 运行开始
  | 'agent.run.completed'  // Agent 运行完成
  | 'agent.run.failed'     // Agent 运行失败
  | 'executor.status'      // 执行器状态变化
  | 'heartbeat';           // 心跳

// 事件数据结构
interface Event {
  type: EventType;
  timestamp: number;
  data: Record<string, unknown>;
  session_id?: string;
}
```

### 4.3 SSE 端点设计

```
GET /api/events

Query Parameters:
  - session_id: string (可选，订阅特定会话的事件)
  - event_types: string (可选，订阅特定事件类型，逗号分隔)

Response:
  Content-Type: text/event-stream
  Cache-Control: no-cache
  Connection: keep-alive

Event Format:
  event: message.created
  data: {"message_id": "xxx", "content": "...", ...}
  
  event: heartbeat
  data: {"timestamp": 1234567890}
```

## 5. 实现计划

### 5.1 阶段一：后端事件系统

**任务清单**：
1. 创建事件总线 (EventBus)
2. 定义事件类型和数据结构
3. 实现 SSE 端点
4. 在关键位置触发事件

**关键文件**：
- `apps/shell/event_bus.py` - 事件总线
- `apps/bridge/routes/events.py` - SSE 端点
- `apps/shell/chat_api.py` - 触发消息事件
- `apps/shell/agent_runtime.py` - 触发 Agent 事件

**预计工时**：3-4 天

### 5.2 阶段二：前端事件客户端

**任务清单**：
1. 创建 EventSource 客户端
2. 实现事件分发器
3. 实现轮询回退机制
4. 集成到现有状态管理

**关键文件**：
- `apps/frontend/src/lib/eventClient.ts` - 事件客户端
- `apps/frontend/src/lib/eventDispatcher.ts` - 事件分发器
- `apps/frontend/src/views/ChatView.tsx` - 集成事件系统

**预计工时**：2-3 天

### 5.3 阶段三：迁移与优化

**任务清单**：
1. 迁移现有轮询逻辑
2. 优化事件触发点
3. 添加连接状态指示
4. 性能测试与优化

**关键文件**：
- `apps/frontend/src/views/ChatView.tsx` - 移除轮询
- `apps/frontend/src/components/ConnectionStatus.tsx` - 连接状态指示

**预计工时**：2-3 天

### 5.4 阶段四：测试与文档

**任务清单**：
1. 单元测试
2. 集成测试
3. 性能测试
4. 更新文档

**预计工时**：2 天

## 6. 详细设计

### 6.1 事件总线 (EventBus)

```python
# apps/shell/event_bus.py
from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, Dict, List, Set
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

logger = logging.getLogger(__name__)

class EventType(str, Enum):
    # 消息事件
    MESSAGE_CREATED = "message.created"
    MESSAGE_UPDATED = "message.updated"
    MESSAGE_COMPLETED = "message.completed"
    MESSAGE_FAILED = "message.failed"
    
    # 会话事件
    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    SESSION_SWITCHED = "session.switched"
    
    # Agent 事件
    AGENT_UPDATED = "agent.updated"
    AGENT_RUN_STARTED = "agent.run.started"
    AGENT_RUN_COMPLETED = "agent.run.completed"
    AGENT_RUN_FAILED = "agent.run.failed"
    
    # 系统事件
    EXECUTOR_STATUS = "executor.status"
    HEARTBEAT = "heartbeat"

@dataclass
class Event:
    type: EventType
    timestamp: float
    data: Dict[str, Any]
    session_id: str | None = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "timestamp": self.timestamp,
            "data": self.data,
            "session_id": self.session_id,
        }
    
    def to_sse(self) -> str:
        """转换为 SSE 格式"""
        import json
        return f"event: {self.type.value}\ndata: {json.dumps(self.to_dict())}\n\n"

class EventBus:
    """事件总线 - 管理事件订阅和分发"""
    
    def __init__(self) -> None:
        self._subscribers: Dict[EventType, List[Callable[[Event], None]]] = {}
        self._session_subscribers: Dict[str, List[Callable[[Event], None]]] = {}
        self._lock = asyncio.Lock()
    
    def subscribe(
        self,
        event_type: EventType,
        callback: Callable[[Event], None],
        session_id: str | None = None,
    ) -> Callable[[], None]:
        """订阅事件
        
        Args:
            event_type: 事件类型
            callback: 回调函数
            session_id: 可选，只订阅特定会话的事件
            
        Returns:
            取消订阅的函数
        """
        if session_id:
            if session_id not in self._session_subscribers:
                self._session_subscribers[session_id] = []
            self._session_subscribers[session_id].append(callback)
            
            def unsubscribe():
                if session_id in self._session_subscribers:
                    self._session_subscribers[session_id].remove(callback)
        else:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)
            
            def unsubscribe():
                if event_type in self._subscribers:
                    self._subscribers[event_type].remove(callback)
        
        return unsubscribe
    
    def publish(self, event: Event) -> None:
        """发布事件
        
        Args:
            event: 事件对象
        """
        # 通知全局订阅者
        for callback in self._subscribers.get(event.type, []):
            try:
                callback(event)
            except Exception as e:
                logger.error("事件回调执行失败: %s", e, exc_info=True)
        
        # 通知会话订阅者
        if event.session_id:
            for callback in self._session_subscribers.get(event.session_id, []):
                try:
                    callback(event)
                except Exception as e:
                    logger.error("会话事件回调执行失败: %s", e, exc_info=True)
    
    def emit(
        self,
        event_type: EventType,
        data: Dict[str, Any],
        session_id: str | None = None,
    ) -> None:
        """发布事件（便捷方法）
        
        Args:
            event_type: 事件类型
            data: 事件数据
            session_id: 可选，会话 ID
        """
        event = Event(
            type=event_type,
            timestamp=datetime.now(timezone.utc).timestamp(),
            data=data,
            session_id=session_id,
        )
        self.publish(event)

# 全局事件总线实例
_event_bus: EventBus | None = None

def get_event_bus() -> EventBus:
    """获取全局事件总线实例"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
```

### 6.2 SSE 端点

```python
# apps/bridge/routes/events.py
from __future__ import annotations
import asyncio
import json
import logging
from typing import AsyncGenerator
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from apps.shell.event_bus import EventBus, Event, EventType, get_event_bus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Events"])

async def event_generator(
    request: Request,
    event_bus: EventBus,
    session_id: str | None = None,
    event_types: list[EventType] | None = None,
) -> AsyncGenerator[str, None]:
    """SSE 事件生成器"""
    queue: asyncio.Queue[Event] = asyncio.Queue()
    
    def callback(event: Event) -> None:
        """事件回调，将事件放入队列"""
        # 过滤事件类型
        if event_types and event.type not in event_types:
            return
        # 过滤会话
        if session_id and event.session_id != session_id:
            return
        queue.put_nowait(event)
    
    # 订阅所有相关事件
    unsubscribers = []
    types_to_subscribe = event_types or list(EventType)
    for event_type in types_to_subscribe:
        unsubscribers.append(event_bus.subscribe(event_type, callback, session_id))
    
    try:
        # 发送初始连接成功消息
        yield f"event: connected\ndata: {json.dumps({'status': 'ok'})}\n\n"
        
        while True:
            # 检查客户端是否断开
            if await request.is_disconnected():
                break
            
            try:
                # 等待事件，超时后发送心跳
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield event.to_sse()
            except asyncio.TimeoutError:
                # 发送心跳
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': asyncio.get_event_loop().time()})}\n\n"
    finally:
        # 取消订阅
        for unsub in unsubscribers:
            unsub()

@router.get("/api/events")
async def stream_events(
    request: Request,
    session_id: str | None = Query(None, description="订阅特定会话的事件"),
    event_types: str | None = Query(None, description="订阅特定事件类型，逗号分隔"),
):
    """SSE 事件流端点
    
    示例:
        GET /api/events
        GET /api/events?session_id=xxx
        GET /api/events?event_types=message.created,message.updated
    """
    event_bus = get_event_bus()
    
    # 解析事件类型
    parsed_types = None
    if event_types:
        try:
            parsed_types = [EventType(t.strip()) for t in event_types.split(",")]
        except ValueError as e:
            return {"error": f"Invalid event type: {e}"}
    
    return StreamingResponse(
        event_generator(request, event_bus, session_id, parsed_types),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

### 6.3 前端事件客户端

```typescript
// apps/frontend/src/lib/eventClient.ts
export type EventType =
  | 'message.created'
  | 'message.updated'
  | 'message.completed'
  | 'message.failed'
  | 'session.created'
  | 'session.updated'
  | 'session.switched'
  | 'agent.updated'
  | 'agent.run.started'
  | 'agent.run.completed'
  | 'agent.run.failed'
  | 'executor.status'
  | 'heartbeat'
  | 'connected';

export interface Event {
  type: EventType;
  timestamp: number;
  data: Record<string, unknown>;
  session_id?: string;
}

export type EventCallback = (event: Event) => void;

export interface EventClientOptions {
  session_id?: string;
  event_types?: EventType[];
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Event) => void;
  fallbackToPolling?: boolean;
  pollingInterval?: number;
}

export class EventClient {
  private eventSource: EventSource | null = null;
  private subscribers: Map<EventType, Set<EventCallback>> = new Map();
  private options: EventClientOptions;
  private connected: boolean = false;
  private reconnectTimer: number | null = null;
  private pollingTimer: number | null = null;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 10;

  constructor(options: EventClientOptions = {}) {
    this.options = {
      fallbackToPolling: true,
      pollingInterval: 30000,
      ...options,
    };
  }

  /**
   * 连接到事件流
   */
  connect(): void {
    if (this.eventSource) {
      this.disconnect();
    }

    const params = new URLSearchParams();
    if (this.options.session_id) {
      params.set('session_id', this.options.session_id);
    }
    if (this.options.event_types?.length) {
      params.set('event_types', this.options.event_types.join(','));
    }

    const url = `/api/events${params.toString() ? '?' + params.toString() : ''}`;
    
    try {
      this.eventSource = new EventSource(url);
      this.setupEventListeners();
    } catch (error) {
      console.error('Failed to create EventSource:', error);
      this.handleConnectionError();
    }
  }

  /**
   * 断开连接
   */
  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.pollingTimer) {
      clearInterval(this.pollingTimer);
      this.pollingTimer = null;
    }

    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }

    this.connected = false;
    this.reconnectAttempts = 0;
  }

  /**
   * 订阅事件
   */
  on(eventType: EventType, callback: EventCallback): () => void {
    if (!this.subscribers.has(eventType)) {
      this.subscribers.set(eventType, new Set());
    }
    this.subscribers.get(eventType)!.add(callback);

    return () => {
      this.subscribers.get(eventType)?.delete(callback);
    };
  }

  /**
   * 取消所有订阅
   */
  offAll(): void {
    this.subscribers.clear();
  }

  /**
   * 获取连接状态
   */
  isConnected(): boolean {
    return this.connected;
  }

  private setupEventListeners(): void {
    if (!this.eventSource) return;

    this.eventSource.onopen = () => {
      console.log('SSE connection established');
      this.connected = true;
      this.reconnectAttempts = 0;
      this.options.onConnect?.();
    };

    this.eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as Event;
        this.dispatch(data);
      } catch (error) {
        console.error('Failed to parse event:', error);
      }
    };

    this.eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      this.connected = false;
      this.options.onDisconnect?.();
      this.handleConnectionError();
    };

    // 监听特定事件类型
    const eventTypes: EventType[] = [
      'message.created',
      'message.updated',
      'message.completed',
      'message.failed',
      'session.created',
      'session.updated',
      'session.switched',
      'agent.updated',
      'agent.run.started',
      'agent.run.completed',
      'agent.run.failed',
      'executor.status',
      'heartbeat',
      'connected',
    ];

    eventTypes.forEach((eventType) => {
      this.eventSource!.addEventListener(eventType, (event) => {
        try {
          const data = JSON.parse((event as MessageEvent).data) as Event;
          this.dispatch(data);
        } catch (error) {
          console.error(`Failed to parse ${eventType} event:`, error);
        }
      });
    });
  }

  private handleConnectionError(): void {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      // 指数退避重连
      const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
      console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);
      
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectAttempts++;
        this.connect();
      }, delay);
    } else if (this.options.fallbackToPolling) {
      console.warn('Max reconnect attempts reached, falling back to polling');
      this.startPolling();
    }
  }

  private startPolling(): void {
    if (this.pollingTimer) return;

    this.pollingTimer = window.setInterval(() => {
      // 轮询逻辑由调用方实现
      this.options.onError?.({
        type: 'heartbeat',
        timestamp: Date.now(),
        data: { reason: 'polling' },
      });
    }, this.options.pollingInterval);
  }

  private dispatch(event: Event): void {
    const callbacks = this.subscribers.get(event.type);
    if (callbacks) {
      callbacks.forEach((callback) => {
        try {
          callback(event);
        } catch (error) {
          console.error(`Event callback error for ${event.type}:`, error);
        }
      });
    }

    // 通配符订阅
    const wildcardCallbacks = this.subscribers.get('*' as EventType);
    if (wildcardCallbacks) {
      wildcardCallbacks.forEach((callback) => {
        try {
          callback(event);
        } catch (error) {
          console.error('Wildcard event callback error:', error);
        }
      });
    }
  }
}

// 全局事件客户端实例
let globalEventClient: EventClient | null = null;

export function getEventClient(options?: EventClientOptions): EventClient {
  if (!globalEventClient) {
    globalEventClient = new EventClient(options);
  }
  return globalEventClient;
}

export function destroyEventClient(): void {
  if (globalEventClient) {
    globalEventClient.disconnect();
    globalEventClient.offAll();
    globalEventClient = null;
  }
}
```

### 6.4 ChatView 集成

```typescript
// apps/frontend/src/views/ChatView.tsx (部分代码)
import { getEventClient, type Event, type EventClient } from '../lib/eventClient';

// 在组件内部
const eventClientRef = useRef<EventClient | null>(null);

useEffect(() => {
  const client = getEventClient({
    session_id: sessions?.current_session_id,
    onConnect: () => {
      console.log('Event stream connected');
      // 连接成功后可以停止轮询
    },
    onDisconnect: () => {
      console.log('Event stream disconnected');
      // 断开连接后可以启动轮询
    },
  });

  // 订阅消息事件
  const unsubMessage = client.on('message.completed', (event: Event) => {
    // 更新消息状态
    void refreshMessages();
  });

  const unsubSession = client.on('session.updated', (event: Event) => {
    // 更新会话列表
    void loadSessions();
  });

  const unsubAgent = client.on('agent.updated', (event: Event) => {
    // 更新 Agent 列表
    void refreshRunnables();
  });

  eventClientRef.current = client;

  return () => {
    unsubMessage();
    unsubSession();
    unsubAgent();
  };
}, [sessions?.current_session_id]);
```

## 7. 迁移策略

### 7.1 渐进式迁移

1. **阶段 1**：实现后端事件系统，保持现有轮询
2. **阶段 2**：实现前端事件客户端，与轮询并存
3. **阶段 3**：逐步替换轮询逻辑
4. **阶段 4**：完全移除轮询

### 7.2 兼容性处理

```typescript
// 检测 SSE 支持
function supportsSSE(): boolean {
  return typeof EventSource !== 'undefined';
}

// 根据支持情况选择方案
const client = supportsSSE()
  ? new EventClient({ fallbackToPolling: true })
  : new PollingClient();
```

### 7.3 回退机制

```typescript
// 自动回退到轮询
const client = new EventClient({
  fallbackToPolling: true,
  pollingInterval: 10000,
  onError: (error) => {
    if (error.data?.reason === 'polling') {
      // 执行轮询逻辑
      void refreshMessages();
      void loadSessions();
    }
  },
});
```

## 8. 测试计划

### 8.1 单元测试

- 事件总线订阅/发布
- 事件过滤
- SSE 序列化
- 客户端连接/断开

### 8.2 集成测试

- 端到端事件流
- 多客户端并发
- 断线重连
- 回退机制

### 8.3 性能测试

- 事件延迟
- 服务器负载
- 内存占用
- 网络带宽

## 9. 风险与应对

### 9.1 潜在风险

1. **连接稳定性**
   - 风险：网络不稳定导致连接频繁断开
   - 应对：指数退避重连 + 自动回退

2. **服务器资源**
   - 风险：大量 SSE 连接占用服务器资源
   - 应对：连接池管理 + 心跳检测

3. **浏览器兼容性**
   - 风险：旧浏览器不支持 SSE
   - 应对：自动检测 + 回退到轮询

### 9.2 监控指标

- SSE 连接数
- 事件延迟
- 重连次数
- 回退到轮询的比例

## 10. 总结

本设计书提出了将轮询机制重构为 SSE 事件推送的方案。通过事件驱动架构，可以：

1. **减少 80% 以上的网络请求**
2. **提高实时性到毫秒级**
3. **降低服务器负载**
4. **提升用户体验**

建议分 4 个阶段实施，预计总工时 10-12 天。

---

**文档版本**：v1.0  
**创建日期**：2026-06-03  
**作者**：AI Assistant  
**状态**：待评审
