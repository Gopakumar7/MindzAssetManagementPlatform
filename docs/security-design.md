# MindZen ALCM Security Design

## Scope and assumptions

This phase secures the existing company and asset registry as a modular monolith. PostgreSQL remains the source of truth; FastAPI authorizes every protected request, and Angular guards are only a usability layer. The browser continues to use the same-origin `/api/v1/` path through Nginx. The existing `postgres_data` volume and applied Alembic migrations are retained.

No external identity provider or email-delivery service is configured. This design therefore uses local accounts, controlled CLI provisioning, and one-time invitation tokens shown to authorized company administrators for secure out-of-band sharing. SSO, email delivery, password reset delivery, and account recovery require a later integration decision and must not be simulated with public registration endpoints.

## Identity and membership

- A `User` is one globally unique, normalized login email with an Argon2id password hash, active state, timestamps, and optional last-login metadata.
- A `CompanyMembership` links a user to a company and one company-scoped role. Membership revocation is soft state; it does not delete identity or historical audit records.
- A separate system-role assignment links platform administrators to system-scoped roles. Company roles cannot grant system permissions.
- Role definitions and stable permission identifiers are persistent data. Idempotent migrations seed system and company role definitions and their initial permission mappings.
- Company membership and role assignment are resolved from the database on every request. No company authorization or permission claim is trusted from the browser or cached in a long-lived token.

## Authentication and session lifecycle

- Login accepts email and password and returns an authentication status; the Angular client then obtains the current-user representation from `/api/v1/auth/me`. Errors do not reveal whether an email is registered or an account is inactive.
- Passwords use Argon2id via the maintained `argon2-cffi` library. Plaintext passwords are never stored, returned, or logged.
- Successful login issues a cryptographically random opaque session token in an `HttpOnly`, `SameSite=Lax` cookie. Only a SHA-256 token digest is persisted. Sessions have a fixed expiry and can be revoked at logout or account/session administration.
- Cookie `Secure` is disabled only for the explicitly configured local HTTP development environment; non-development configuration requires secure cookies. Deployments must use HTTPS.
- Unsafe cookie-authenticated requests require a per-session CSRF token in `X-CSRF-Token`, compared in constant time. The CSRF token is readable by the same-origin Angular client but is not an authentication credential. Login validates the request origin against configured origins.
- Login throttling is enforced in persistent storage using a time window and cooldown keyed by normalized login and source address. The Compose backend is not host-published and Nginx overwrites the source-address header; deployments must preserve that trust boundary and must not expose the backend directly to untrusted callers.
- Sessions re-check user active status, membership, role, and permissions on every request; expiry, logout, deactivation, and membership revocation therefore take effect promptly.

## Provisioning and account lifecycle

- There is no public self-registration or default account.
- `python -m app.cli.bootstrap_admin` is an interactive, one-time operation that prompts for the first administrator's email and password without echoing the password. It refuses to create a new system administrator once one exists and is safe to rerun.
- A system administrator provisions companies and manages accounts and memberships through authenticated administrative APIs. Company administrators can manage memberships only within their authorized company and cannot alter their own membership or grant permissions they do not hold.
- Invitations are single-use and return the raw token once to the authorized administrator; delivery/sharing occurs out of band. Password reset and account recovery are unavailable until an outbound identity/recovery channel is selected.

## Roles and permissions

Authorization uses permission identifiers, not role-name checks in business routes. Initial role mappings are stored in the database and may be administered by system administrators.

| Scope | Role | Initial authority |
| --- | --- | --- |
| System | System Administrator | Company provisioning, system account/membership administration, role/permission configuration, cross-company access, audit read |
| Company | Company Administrator | Company membership administration and configured company business permissions |
| Company | Asset Manager | Organisation master, category, numbering, and asset read/write permissions |
| Company | IT Support | Explicit operational asset read/update and usage permissions only |
| Company | Auditor | Read-only company records and audit history |
| Company | Read-only User | Company asset/organisation read permissions only |

Initial permission identifiers include `company.read`, `company.create`, `company.update`, `company.members.manage`, `system.companies.manage`, `system.users.manage`, `system.rbac.manage`, `organization.read`, `organization.manage`, `asset.read`, `asset.create`, `asset.update`, `asset.usage.manage`, `asset.history.read`, and `audit.read`. Additional identifiers are added explicitly with endpoints. Unknown permissions deny access.

Every company-scoped operation resolves the authenticated actor, active company, current membership or explicit system-level permission, and required permission before accessing company data. Nested records are selected by both company ID and record ID; request-body company IDs cannot override the path or authenticated scope. Unauthorized resource lookups return `404` where needed to avoid disclosing cross-company record existence; unauthenticated requests return `401` and authenticated permission failures return `403`.

## Endpoint protection

- Public operational endpoints: `GET /api/v1/health`, `GET /api/v1/health/ready`, and the minimal service root. They expose no credentials or business records.
- Authentication endpoints: login is public but rate-limited and origin-checked; current-user/session and logout require a valid session (logout also requires CSRF).
- All `/api/v1/companies/**` organization, category, numbering, asset, usage, and asset-history endpoints require authentication, active company scope, and the corresponding permission.
- Company provisioning, user/membership administration, and role/permission configuration require system- or company-scoped permissions as appropriate.
- Audit reads require `audit.read` and are filtered to the caller's authorized company scope.
- Interactive API docs/OpenAPI are available only in development. They are disabled outside development unless a deployment explicitly enables a protected documentation surface.

## Audit events

Security and business changes are recorded in an append-only `audit_events` table in the same transaction as the change. Events include UTC timestamp, actor (nullable for failed login or controlled bootstrap), company scope when applicable, action, entity type and ID, outcome, request/correlation ID, and safe before/after summaries. Passwords, password hashes, session tokens, CSRF tokens, and other authentication secrets are excluded.

A reusable SQLAlchemy unit-of-work hook observes tracked business/security mutations and adds audit rows before commit; login failures and other non-ORM security events are written explicitly. Any audit persistence failure aborts the related mutation. Database triggers reject updates, deletes, and truncation of audit rows; no ordinary API exposes audit mutation.

## Testing strategy

- Implemented API tests exercise health access, unauthenticated access, CSRF rejection, company-scoped role checks, immediate membership/session revocation, invitation acceptance/reissue, audit ORM immutability, and audit/business transaction atomicity.
- PostgreSQL integration tests exercise those cases and concurrent asset numbering using a dedicated `TEST_DATABASE_URL`; never point destructive test setup at the application database.
- The migration chain and direct PostgreSQL audit update/delete/truncate trigger behavior are verified on a separate disposable PostgreSQL instance.
- Angular tests cover current-user state and CSRF request headers; route/login/invitation browser behavior also has a production-build check. Backend authorization remains authoritative.
- Live Compose/login verification against the persistent application database must be recorded only after the new backend image is deployed and the additive migration is applied.

## Known limitations

The application has no email delivery, SSO, password reset, MFA, or external identity-provider integration. Persistent login throttling is a basic application control, not a substitute for edge rate limiting or monitoring. Production requires HTTPS, secure cookie configuration, protected secret delivery, backups, and operational review of account and audit retention policies.
