# C# Source Code Implementation Guidelines

## 🚫 CRITICAL: NEVER HARDCODE KUSTO QUERIES IN C# CODE

**ABSOLUTELY FORBIDDEN:**
- Hardcoding KQL data queries in C# string literals
- Building data queries with string interpolation or concatenation in code
- Inline data queries in any C# file

**REQUIRED APPROACH:**
- ALL data queries MUST be in `.kql` files under `internal_resources/queries/`
- Use `declare query_parameters()` for parameterization
- Load queries via QueryService or query metadata provider
- Pass parameters through the Kusto SDK parameter system

### Exception: Kusto Control-Plane Commands

**ACCEPTABLE INLINE QUERIES:**
Kusto control-plane/metadata commands MAY be inline if they meet ALL criteria:

1. **Purpose**: Used ONLY for error messages, diagnostics, or schema discovery
2. **Frequency**: NOT frequently executed (only in error/edge cases)
3. **Complexity**: Simple metadata commands with no business logic
4. **Documentation**: Must include comment explaining why inline is acceptable

**Acceptable Commands:**
- `.show tables` - List available tables for error suggestions
- `.show table <name> schema` - Get table schema for diagnostics
- `.show database schema` - Database metadata for validation
- `.show cluster` - Cluster information for connection diagnostics

**Documentation Template:**
```csharp
// INLINE QUERY EXCEPTION: Control-plane command for error diagnostics.
// This .show command is used only when [specific error scenario],
// not frequently executed, and provides [diagnostic purpose].
var query = ".show tables | where TableName contains \"pattern\"";
```

**Examples in codebase:**
- `KustoService.FindSimilarTablesAsync()` - Line 109: `.show tables` for table name suggestions
- `KustoService.GetTableSchemaAsync()` - Line 135: `.show table schema` for error messages

**Example of FORBIDDEN code:**
```csharp
// ❌ NEVER DO THIS
var query = $"Incidents | where IncidentId == {incidentId}";
var query = $@"
    Incidents
    | where IncidentId == {incidentId}
    | project *
";
```

**Correct approach:**
```csharp
// ✅ Load from .kql file
var query = await queryService.LoadQueryAsync("incident_by_id");
var parameters = new Dictionary<string, object> { ["incident_id"] = incidentId };
var result = await kustoService.ExecuteQueryAsync(query, cluster, database, parameters);
```

## Query File Organization

**Location:** `internal_resources/queries/{category}/{query_name}.kql`

**Categories:**
- `incidents/` - Incident-related queries
- `node/` - Node and infrastructure queries
- `resolution/` - Resolution and mitigation queries

**Query File Format:**
```kql
// Description of what this query does
declare query_parameters(
    incident_id: long,
    optional_param: string = "default"
);

Incidents
| where IncidentId == incident_id
| project *
```

## C# Coding Standards

### Null Safety
- Enable nullable reference types
- Use `?` for nullable types
- Validate parameters at method entry

### Error Handling
- Use custom exceptions from `IcmMcpServer.Core.Exceptions`
- Catch specific exceptions, not generic `Exception`
- Log errors with structured data

### Async/Await
- Always use `async`/`await` for I/O operations
- Pass `CancellationToken` through the call chain
- Never use `.Result` or `.Wait()`

### Dependency Injection
- Use constructor injection
- Register services in `Program.cs`
- Follow interface-based design

### Logging
- Use `ILogger<T>` from Microsoft.Extensions.Logging
- Include structured data in log messages
- Log at appropriate levels (Debug, Info, Warning, Error)

## Tool Handler Guidelines

### Inherit from BaseToolHandler
```csharp
public class MyToolHandler : BaseToolHandler<MyParams, MyResult>
{
    public MyToolHandler(
        ToolHandlerConfig config,
        IKustoService kustoService,
        ILogger<MyToolHandler> logger)
        : base(config, kustoService, logger)
    {
    }
}
```

### Parameter Validation
- Override `ValidateParameters` to check inputs
- Throw `ValidationError` for invalid parameters
- Provide clear error messages

### Execution
- Override `ExecuteAsync` for tool logic
- Use `LogInfo`, `LogWarning`, `LogError` from base class
- Return structured results

## Testing Requirements

- Write unit tests for all public methods
- Use xUnit with FluentAssertions
- Mock dependencies with Moq
- Test error paths and edge cases
- Maintain >80% code coverage

## File Organization

```
src/
  IcmMcpServer.Core/
    Tools/          - Tool handlers
    Services/       - Business logic
    Exceptions/     - Custom exceptions
    Workflows/      - Workflow tasks
  IcmMcpServer.Infrastructure/
    Services/       - External service implementations
  IcmMcpServer/
    Program.cs      - Entry point and DI setup
```

## Performance Guidelines

- Use async/await consistently
- Avoid blocking calls
- Implement retry logic for transient failures
- Use connection pooling for external services
- Cache expensive computations when appropriate

## Security

- Never log sensitive data (credentials, PII)
- Validate all external inputs
- Use parameterized queries (via .kql files)
- Follow principle of least privilege
- Sanitize error messages before exposing to users
