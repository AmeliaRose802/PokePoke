# Bridge Contract Validation

## Overview

The PokePoke desktop frontend and Python pywebview bridge now use **runtime-validated contracts** via Zod schemas on the TypeScript side. This ensures that payload shape drift between Python and TypeScript surfaces immediately at the bridge boundary with actionable error messages, rather than silently breaking the UI at render time.

## Problem Solved

**Before:**
- Frontend relied on TypeScript interfaces that were comments-described as mirroring Python structures
- No runtime validation on incoming payloads
- Payload shape drift caused silent runtime failures deep in rendering code
- AI-authored changes to either side could break the UI without detection until user interaction

**After:**
- All bridge payloads validated at boundary with Zod schemas
- Contract mismatches fail fast with clear error messages including field path and expected type
- Tests cover representative valid and invalid payloads
- AI edits that break contracts surface immediately in development

## Architecture

### Validation at Boundary

```
Python (DesktopAPI)  →  pywebview bridge  →  TypeScript (useBridge)
    dict[str, Any]           JSON IPC            Zod validation
                                                        ↓
                                            Typed React state
```

**Key files:**
- `desktop/src/schemas.ts` - Zod schema definitions for all bridge payloads
- `desktop/src/useBridge.ts` - Validation integrated at all API call sites
- `desktop/src/useSetupBridge.ts` - Validation for setup wizard APIs
- `desktop/src/schemas.test.ts` - 32 tests covering valid/invalid payloads

### Validation Strategies

**Critical paths (fail-fast):**
Use `validatePayload()` for:
- Initial state load
- Configuration responses
- Setup wizard status
- Explicit user-initiated API calls (getPrompt, getConfig, etc.)

```typescript
const state = validatePayload(AppStateSchema, rawState, "loadInitialState");
// Throws with: "[Bridge Contract Error] loadInitialState failed validation: field.path: error message"
```

**Incremental updates (graceful degradation):**
Use `safeValidatePayload()` for:
- Polling updates
- Log entries (fallback to raw if validation fails)
- Non-critical background data

```typescript
const state = safeValidatePayload(AppStateSchema, rawState, "pollState");
if (!state) {
  // Log error and skip update, don't crash UI
  return;
}
```

## Schema Maintenance

### Adding New Fields

**Python side (DesktopAPI):**
```python
def get_state(self) -> dict[str, Any]:
    return {
        "work_item": self._current_work_item,
        "new_field": self._new_field,  # Add new field
        # ...
    }
```

**TypeScript side (schemas.ts):**
```typescript
export const AppStateSchema = z.object({
  work_item: WorkItemSchema.nullable(),
  new_field: z.string().optional(),  // Mark optional if not always present
  // ...
});
```

**TypeScript interface (types.ts):**
```typescript
export interface AppState {
  work_item: WorkItem | null;
  new_field?: string;  // Update interface to match
  // ...
}
```

### Breaking Changes

If you need to change an existing field type:

1. **Add new field first** (alongside old field) in Python and TypeScript
2. **Update consumers** to use new field
3. **Remove old field** once all consumers migrated
4. **Update tests** to cover new schema

### Testing New Schemas

**Test valid payloads:**
```typescript
it("should validate valid payload", () => {
  const valid = { /* ... */ };
  expect(() => validatePayload(MySchema, valid, "test")).not.toThrow();
});
```

**Test invalid payloads:**
```typescript
it("should reject invalid field type", () => {
  const invalid = { field: 123 /* should be string */ };
  expect(() => validatePayload(MySchema, invalid, "test")).toThrow(/field.*expected string/);
});
```

**Test missing required fields:**
```typescript
it("should reject missing required field", () => {
  const incomplete = { /* missing required field */ };
  expect(() => validatePayload(MySchema, incomplete, "test")).toThrow(/Invalid input/);
});
```

## Error Messages

### Example: Invalid Field Type

```
[Bridge Contract Error] getConfig failed validation:
  config.max_parallel_agents: Invalid input: expected number, received string
```

### Example: Missing Required Field

```
[Bridge Contract Error] loadInitialState failed validation:
  work_item.item_id: Invalid input: expected string, received undefined;
  work_item.title: Invalid input: expected string, received undefined
```

### Example: Invalid Enum Value

```
[Bridge Contract Error] pollState failed validation:
  agents[2].status: Invalid option: expected one of "running"|"success"|"failed"
```

## Python-Side Validation (Optional)

While not implemented in this initial version, Python-side validation with Pydantic could provide additional safety:

```python
from pydantic import BaseModel

class WorkItemPayload(BaseModel):
    item_id: str
    title: str
    status: str
    labels: list[str] = []

def push_work_item(self, item_id: str, title: str, status: str = "", labels: list[str] | None = None) -> None:
    payload = WorkItemPayload(
        item_id=item_id,
        title=title,
        status=status,
        labels=labels or []
    )
    self._current_work_item = payload.model_dump()
```

**Tradeoffs:**
- ✅ Catches Python-side errors before they reach the bridge
- ✅ Better developer ergonomics with autocomplete in Python
- ❌ Adds Pydantic dependency and serialization overhead
- ❌ Duplicates validation logic (Pydantic + Zod)

For now, TypeScript-side validation is sufficient as it catches all boundary violations.

## Related Files

- `desktop/src/types.ts` - TypeScript interface definitions (mirrored from schemas)
- `src/pokepoke/desktop/desktop_api.py` - Python API implementation
- `.githooks/check-build.ps1` - Pre-commit hook that runs desktop build (catches TypeScript errors)

## Best Practices

1. **Keep interfaces and schemas in sync** - Update both when changing contracts
2. **Use optional fields liberally** - Makes schemas more resilient to phased rollouts
3. **Test both valid and invalid cases** - Ensures schemas catch actual errors
4. **Use safe validation for non-critical paths** - Prevents UI crashes from transient issues
5. **Include field context in error messages** - Makes debugging easier
6. **Run full build before committing** - Pre-commit hooks catch TypeScript errors
