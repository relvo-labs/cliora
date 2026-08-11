<!-- GENERATED FILE — do not edit.
     Source: app/services/rbac.py (ROLE_ACTIONS) + ADR 0016.
     Regenerate: uv run --project backend python ../scripts/p4/render_permission_matrix.py --write
-->

# Permission matrix

Two layers authorize every session-scoped mutation, and **both** are required
(ADR 0016). The action layer below answers "may this role ever do this kind of
thing?"; the resource-scope rules that follow answer "may this user do it to
*this* resource?". A role check alone was the P1-P3 behaviour, and it let any
Developer terminate any colleague's session.

## Action layer (PRD §8.1)

| 功能 / Capability | Action key | Admin | Developer | Viewer |
|---|---|:--:|:--:|:--:|
| 查看 Node / View nodes | `node.view` | ✓ | ✓ | ✓ |
| 建立安裝 Token / Create enrollment token | `enrollment.manage` | ✓ | — | — |
| 移除 Node / Manage & remove nodes | `node.manage` | ✓ | — | — |
| 建立 Session / Create session | `session.create` | ✓ | ✓ | — |
| 查看 Session / View session (read-only attach) | `session.view` | ✓ | ✓ | ✓ |
| 操作 Terminal / Operate terminal (writer) | `terminal.operate` | ✓ | ✓ | — |
| 接管 Terminal / Take over the writer role | `terminal.takeover` | ✓ | ✓ | — |
| 終止 Session / Terminate session | `session.terminate` | ✓ | ✓ | — |
| 瀏覽檔案 / Browse & preview files | `file.browse` | ✓ | ✓ | ✓ |
| 查看 Audit Log / View audit log | `audit.view` | ✓ | — | — |
| 查看專案 / View projects | `project.view` | ✓ | ✓ | ✓ |
| 管理專案 / Manage projects & workspace bindings | `project.manage` | ✓ | — | — |
| 查看 Agent / View agent runners | `agent.view` | ✓ | ✓ | ✓ |
| 管理 Agent / Manage agent runners | `agent.manage` | ✓ | — | — |
| 派工給 Agent / Dispatch a card to an agent | `run.dispatch` | ✓ | ✓ | — |
| 取消 Run / Cancel a run | `run.cancel` | ✓ | ✓ | — |

Roles are strictly nested: Viewer ⊂ Developer ⊂ Admin. Viewer holds no mutation
action, so a forged Viewer mutation fails before any resource is loaded.

## Resource-scope layer (`app/services/authz.py`)

| Operation | Rule |
|---|---|
| session.view / read-only attach | any holder of `session.view` (Viewer included) |
| terminal writer (input, resize) | `terminal.operate` **and** (owner **or** holder of `terminal.takeover`) |
| terminal takeover | same as writer eligibility; displaces the current writer, so it is announced and audited |
| session.terminate / delete | `session.terminate` **and** (owner **or** holder of `node.manage`, i.e. Admin) |
| session.create | `user_id` is assigned by the server; never accepted from the client |
| file browse / search / preview | `file.browse` **and** view access to the owning session |
| node management | `node.manage`; nodes have no owner |

Every refusal from either layer raises the same `FORBIDDEN` / 403 with the same
message, so a caller cannot use the response to learn whether a resource exists
or who owns it. Where absence is legitimate, view access is settled first and
only then may a 404 be returned.

## Where these are enforced

| Surface | Mechanism |
|---|---|
| HTTP | `require_action()` (action) then `app/services/authz.py` (resource) |
| Browser terminal WebSocket | ws-ticket bound to (user, session), then the same predicates **on every inbound control message** — not once at attach |
| Daemon WebSocket | Ed25519 node credential; a daemon cannot invoke a user action |
| UI | capability flags computed by the server (`/api/auth/me`, `SessionSummary.capabilities`); hiding a control is never the authorization |

Coverage is asserted by `backend/tests/test_authz.py` and
`backend/tests/db/test_permission_matrix.py`: adding a route without deciding its
authorization fails the route-coverage test.
