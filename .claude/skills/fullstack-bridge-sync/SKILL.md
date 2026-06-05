---
name: fullstack-bridge-sync
description: "Use this skill when the task involves synchronizing API contracts between a Python backend and a TypeScript frontend. Trigger for: generating or validating OpenAPI/JSON Schema specs from Python (FastAPI, Flask, Django), generating TypeScript types or Zod schemas from those specs, detecting request/response shape drift, adding type-safe API client stubs, or any workflow where a backend route change must propagate cleanly to the frontend without manual transcription."
---

# Fullstack Bridge Sync

## Library Selection

| Task | Tool / Library |
|---|---|
| Python schema generation (FastAPI) | `fastapi`, `pydantic` (built-in OpenAPI) |
| Python schema generation (Flask/Django) | `apispec`, `marshmallow`, `drf-spectacular` |
| TypeScript codegen from OpenAPI | `openapi-typescript` (CLI), `orval` |
| Zod schema generation | `openapi-zod-client` |
| Runtime validation (TS) | `zod` |
| Drift detection | `openapi-diff` CLI or custom Python script |
| Typed HTTP client | `axios` + generated types, or `ky` |

Install only what the task requires.

## Source-of-Truth Rule

The Python backend is always the schema source of truth. TypeScript types are always **derived**, never handwritten. Violating this causes silent drift.

```
Python models (Pydantic) → OpenAPI spec → TypeScript types → API client
```

Never write a TypeScript interface that mirrors a backend model by hand — regenerate from spec instead.

## Backend: Exporting the OpenAPI Spec

### FastAPI (auto-generated)
```python
# FastAPI exposes /openapi.json automatically.
# Dump it to a file for codegen:
import json, httpx

def export_spec(base_url: str, out_path: str = "openapi.json") -> None:
    spec = httpx.get(f"{base_url}/openapi.json").json()
    with open(out_path, "w") as f:
        json.dump(spec, f, indent=2)
```

### Pydantic model → inline JSON Schema
```python
from pydantic import BaseModel
import json

class Transaction(BaseModel):
    id: str
    amount: float
    currency: str
    settled_at: str  # ISO-8601

print(json.dumps(Transaction.model_json_schema(), indent=2))
```

Always version the exported spec file and commit it to source control alongside the route change.

### Flask / apispec
```python
from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin

spec = APISpec(
    title="MyAPI",
    version="1.0.0",
    openapi_version="3.0.3",
    plugins=[MarshmallowPlugin()],
)
# Register schemas and paths, then:
with open("openapi.json", "w") as f:
    import json
    json.dump(spec.to_dict(), f, indent=2)
```

## Frontend: Generating TypeScript Types

### openapi-typescript (recommended — zero-runtime overhead)
```bash
npx openapi-typescript openapi.json -o src/api/schema.d.ts
```

Produces pure `interface` / `type` declarations. Import in client code:
```typescript
import type { paths, components } from "./schema";

type Transaction = components["schemas"]["Transaction"];
type CreateTxRequest = paths["/transactions"]["post"]["requestBody"]["content"]["application/json"];
type CreateTxResponse = paths["/transactions"]["post"]["responses"]["200"]["content"]["application/json"];
```

### orval (generates full client + Zod schemas)
```bash
npx orval --config orval.config.ts
```

```typescript
// orval.config.ts
import { defineConfig } from "orval";
export default defineConfig({
  myApi: {
    input:  "./openapi.json",
    output: {
      target:     "./src/api/client.ts",
      schemas:    "./src/api/model",
      client:     "axios",
      mode:       "tags-split",
    },
  },
});
```

### Zod schemas from spec
```bash
npx openapi-zod-client openapi.json -o src/api/schemas.ts
```

Use Zod schemas at runtime API boundary to validate response shapes before they reach application logic:
```typescript
import { TransactionSchema } from "./schemas";

const raw = await fetch("/api/transactions/123").then(r => r.json());
const tx = TransactionSchema.parse(raw); // throws ZodError on shape mismatch
```

## Drift Detection

Run after every backend route change, in CI, and before frontend PRs merge.

### CLI check (openapi-diff)
```bash
npx openapi-diff openapi.prev.json openapi.json
# Exit code 1 = breaking changes present
```

### Python drift reporter
```python
import json, sys
from deepdiff import DeepDiff

def diff_specs(prev_path: str, curr_path: str) -> list[str]:
    with open(prev_path) as f: prev = json.load(f)
    with open(curr_path) as f: curr = json.load(f)
    diff = DeepDiff(prev, curr, ignore_order=True)
    if not diff:
        return []
    issues = []
    for change_type, details in diff.items():
        issues.append(f"{change_type}: {details}")
    return issues

breaking = diff_specs("openapi.prev.json", "openapi.json")
if breaking:
    print("\n".join(breaking))
    sys.exit(1)
```

Breaking changes that require frontend regeneration:
- Field renamed or removed from a response schema
- Request body field made required that was previously optional
- Path or method removed
- Response status code changed

## Contract Enforcement Patterns

### Pydantic strict mode (prevents accidental extra fields)
```python
from pydantic import BaseModel, ConfigDict

class TransactionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")  # rejects unknown fields
    id: str
    amount: float
    currency: str
```

### TypeScript response validation at the API layer
```typescript
import { z } from "zod";

async function fetchTransaction(id: string): Promise<Transaction> {
    const raw = await apiClient.get(`/transactions/${id}`);
    return TransactionSchema.parse(raw.data);  // runtime guard
}
```

Never bypass Zod parse in production client code — silent shape drift causes downstream runtime errors that are hard to trace.

## CI Integration

```yaml
# .github/workflows/contract-check.yml
- name: Export backend spec
  run: python scripts/export_spec.py

- name: Diff against committed spec
  run: npx openapi-diff openapi.committed.json openapi.json

- name: Regenerate TypeScript types
  run: npx openapi-typescript openapi.json -o src/api/schema.d.ts

- name: TypeScript typecheck
  run: npx tsc --noEmit
```

Fail the build on any breaking change detected by `openapi-diff`.

## Verification Checklist

- [ ] `openapi.json` committed to source control and updated on every backend route change
- [ ] TypeScript types generated from spec — none handwritten to mirror backend models
- [ ] Zod (or equivalent) parse called at every API response boundary
- [ ] `openapi-diff` runs in CI and blocks merge on breaking changes
- [ ] `tsc --noEmit` passes after type regeneration
- [ ] Pydantic models use `extra="forbid"` on all public response schemas
- [ ] All required fields have explicit types — no `Any` or `object` in public schema
- [ ] Date/time fields use ISO-8601 strings, not epoch integers, in the spec

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| TypeScript types handwritten to match backend | Delete them; regenerate from spec |
| Spec committed only in frontend repo | Commit spec adjacent to backend routes — it's a backend artifact |
| Optional field silently made required | CI drift check catches this; Zod parse surfaces it at runtime |
| `any` type leaking from generated client | Set `strict: true` in `tsconfig.json`; regenerate with orval strict mode |
| FastAPI returns `422` but TS client ignores it | Model all error response types in the spec; handle in client |
| Enum values added on backend without TS regen | Enum drift causes silent fallthrough — always regen after enum changes |
| Nullable vs optional mismatch | Pydantic `Optional[X]` → `nullable: true` in spec; verify TS output |
