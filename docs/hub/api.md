# Hub API Reference

## REST API

Base URL: `http://your-server:8080`

### Agents

#### List Connected Agents

```http
GET /api/agents
```

Response:
```json
[
  {
    "agent": {
      "agent_id": "uuid",
      "hostname": "workstation",
      "project_name": "my-project",
      "project_path": "/home/user/my-project",
      "agent_name": "workstation",
      "connected_at": "2024-01-15T10:30:00Z",
      "last_seen": "2024-01-15T10:35:00Z"
    },
    "task": {
      "task_name": "add-auth",
      "task_description": "Add user authentication",
      "task_type": "feature",
      "stage": "DEV",
      "attempt": 1,
      "awaiting_approval": false
    },
    "connected": true
  }
]
```

#### Get Agents Needing Attention

```http
GET /api/agents/needs-attention
```

Returns agents with `awaiting_approval: true`.

#### Get Agent by ID

```http
GET /api/agents/{agent_id}
```

### Tasks

#### List Recent Tasks

```http
GET /api/tasks?limit=50&agent_id=optional
```

#### Get Active Tasks

```http
GET /api/tasks/active
```

#### Get Task Details

```http
GET /api/tasks/{agent_id}/{task_name}
```

### Actions

#### Approve Stage

```http
POST /api/actions/{agent_id}/{task_name}/approve
Content-Type: application/json

{
  "feedback": "Looks good!"
}
```

#### Reject Stage

```http
POST /api/actions/{agent_id}/{task_name}/reject
Content-Type: application/json

{
  "reason": "Missing error handling"
}
```

#### Skip Stage

```http
POST /api/actions/{agent_id}/{task_name}/skip
Content-Type: application/json

{
  "reason": "Not needed for this task"
}
```

#### Rollback to Stage

```http
POST /api/actions/{agent_id}/{task_name}/rollback
Content-Type: application/json

{
  "target_stage": "DEV",
  "feedback": "Need to fix the implementation"
}
```

#### Interrupt Task

```http
POST /api/actions/{agent_id}/{task_name}/interrupt
```

## WebSocket API

### Agent Connection

Endpoint: `ws://your-server:8080/ws/agent`

#### Registration

Agent sends on connect:

```json
{
  "type": "register",
  "agent_id": "uuid",
  "timestamp": "2024-01-15T10:30:00Z",
  "payload": {
    "agent_id": "uuid",
    "hostname": "workstation",
    "project_name": "my-project",
    "project_path": "/home/user/my-project",
    "agent_name": "workstation"
  }
}
```

Hub responds:

```json
{
  "type": "registered",
  "agent_id": "uuid"
}
```

#### State Update

Agent sends on stage changes:

```json
{
  "type": "state_update",
  "agent_id": "uuid",
  "timestamp": "2024-01-15T10:30:00Z",
  "payload": {
    "task_name": "add-auth",
    "task_description": "Add user authentication",
    "task_type": "feature",
    "stage": "DEV",
    "attempt": 1,
    "awaiting_approval": false,
    "started_at": "2024-01-15T10:00:00Z"
  }
}
```

#### Event

Agent sends on workflow events:

```json
{
  "type": "event",
  "agent_id": "uuid",
  "timestamp": "2024-01-15T10:30:00Z",
  "payload": {
    "event_type": "stage_complete",
    "timestamp": "2024-01-15T10:30:00Z",
    "data": {
      "stage": "PM",
      "duration": 120
    }
  }
}
```

Event types:
- `stage_start`
- `stage_complete`
- `stage_fail`
- `approval_needed`
- `rollback`
- `task_complete`
- `task_error`

#### Heartbeat

Agent sends periodically:

```json
{
  "type": "heartbeat",
  "agent_id": "uuid",
  "timestamp": "2024-01-15T10:35:00Z",
  "payload": {}
}
```

#### Action (Hub to Agent)

Hub sends when user takes action:

```json
{
  "type": "action",
  "payload": {
    "action_type": "approve",
    "task_name": "add-auth",
    "data": {
      "feedback": "Looks good!"
    }
  }
}
```

Action types:
- `approve`
- `reject`
- `skip`
- `rollback`
- `interrupt`

### Dashboard Connection

Endpoint: `ws://your-server:8080/ws/dashboard`

Hub sends refresh notifications:

```json
{
  "type": "refresh"
}
```

Dashboard can listen for updates and refresh HTMX partials.

## Authentication

If `HUB_API_KEY` is set, include in requests:

```http
Authorization: Bearer your-api-key
```

For WebSocket, include in connection headers:

```javascript
new WebSocket(url, {
  headers: {
    'Authorization': 'Bearer your-api-key'
  }
})
```
