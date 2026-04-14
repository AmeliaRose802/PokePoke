# PokePoke C# Implementation

This directory contains the C# rewrite of the PokePoke autonomous workflow orchestrator.

## Project Structure

The C# solution mirrors the Python package layout with the following projects:

### Core Libraries

- **PokePoke.Core** - Core abstractions, interfaces, and base types
- **PokePoke.Models** - Data models and DTOs shared across projects
- **PokePoke.Utils** - Utility functions and helper classes

### Domain Modules

- **PokePoke.Orchestration** - Main workflow orchestration logic
- **PokePoke.Agents** - AI agent integration and management
- **PokePoke.Beads** - Beads issue tracker integration (bd/br CLI wrappers)
- **PokePoke.Git** - Git operations and worktree management
- **PokePoke.Desktop** - Desktop UI components
- **PokePoke.Stats** - Statistics and telemetry

### Applications

- **PokePoke.CLI** - Command-line interface (main entry point)

## Building

### Prerequisites

- .NET 9.0 SDK or later
- Windows, macOS, or Linux

### Build Commands

```bash
# Restore dependencies
dotnet restore PokePoke.sln

# Build all projects
dotnet build PokePoke.sln --configuration Release

# Run tests (when added)
dotnet test tests-csharp/**/*.csproj

# Publish CLI application
dotnet publish src-csharp/PokePoke.CLI/PokePoke.CLI.csproj -c Release -o ./publish
```

## Dependencies

### Key NuGet Packages

- **System.CommandLine** - Modern command-line parsing
- **YamlDotNet** - YAML configuration and beads support
- **Microsoft.Data.Sqlite** - SQLite database access for beads
- **Microsoft.Extensions.Logging** - Structured logging
- **Microsoft.Extensions.DependencyInjection** - Dependency injection
- **System.Text.Json** - JSON serialization

## Project Dependencies

```
PokePoke.CLI
├── PokePoke.Core
└── PokePoke.Orchestration
    ├── PokePoke.Core
    ├── PokePoke.Agents
    │   ├── PokePoke.Core
    │   └── PokePoke.Models
    ├── PokePoke.Beads
    │   ├── PokePoke.Core
    │   ├── PokePoke.Models
    │   └── PokePoke.Utils
    ├── PokePoke.Git
    │   ├── PokePoke.Core
    │   ├── PokePoke.Models
    │   └── PokePoke.Utils
    └── PokePoke.Models

PokePoke.Desktop
├── PokePoke.Core
└── PokePoke.Models

PokePoke.Stats
├── PokePoke.Core
├── PokePoke.Models
└── PokePoke.Utils

PokePoke.Utils
└── PokePoke.Core
```

## CI/CD

Azure Pipelines configuration is in `azure-pipelines.yml` at the repository root. The pipeline:

1. Installs .NET 9.0 SDK
2. Restores NuGet packages
3. Builds the solution
4. Runs tests with code coverage
5. Publishes the CLI application as an artifact

## Development

### Adding New Projects

```bash
# Create new class library
dotnet new classlib -n PokePoke.NewModule -o src-csharp/PokePoke.NewModule -f net9.0

# Add to solution
dotnet sln PokePoke.sln add src-csharp/PokePoke.NewModule/PokePoke.NewModule.csproj

# Add project references
dotnet add src-csharp/PokePoke.NewModule/PokePoke.NewModule.csproj reference src-csharp/PokePoke.Core/PokePoke.Core.csproj
```

### Adding NuGet Packages

```bash
dotnet add src-csharp/PokePoke.ProjectName/PokePoke.ProjectName.csproj package PackageName
```

## Future Work

- Port Python orchestration logic to C#
- Implement beads CLI wrapper with bd/br backend support
- Add git worktree management
- Implement AI agent integration
- Add comprehensive unit and integration tests
- Desktop UI implementation
- Performance optimizations

## Relationship to Python Implementation

The C# implementation is a complete rewrite while maintaining the same architecture and functionality as the Python version in `src/pokepoke/`. Both implementations will coexist during the transition period.
