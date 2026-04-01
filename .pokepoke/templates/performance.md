# Performance Optimization Template

## Title Pattern
`Perf: [component] [brief description of optimization]`

**Examples:**
- `Perf: orchestrator reduce startup latency by 50%`
- `Perf: beads cache query results for 30s`
- `Perf: validation parallelize gate execution`

## Issue Type
`task` (use `performance` label)

## Priority Guidelines
- **P0 (Critical)**: Production unusable due to performance issue
- **P1 (High)**: Significant slowdown affecting user experience (>30s waits)
- **P2 (Medium)**: Noticeable slowdown but acceptable (10-30s waits)
- **P3 (Low)**: Minor optimization, nice to have (<10s improvement)

## Expected Files to Modify

### Primary Implementation
- `src/pokepoke/[component]/[module].py` - Optimize slow code

### Testing
- `tests/[component]/test_[module].py` - Verify behavior unchanged
- `tests/performance/test_[optimization].py` - Add performance benchmarks (optional)

### Configuration
- `.pokepoke/config.yaml` - Add tuning options if applicable
- `src/pokepoke/config.py` - Configuration schema

### Documentation
- `README.md` - Document configuration for performance tuning
- Code comments - Explain optimization rationale

## Performance Optimization Approach

### Step 1: Measure First (Baseline)
**Critical:** Never optimize without measuring first!

```python
import time
import cProfile
import pstats

# Timing measurement
start = time.perf_counter()
result = slow_function()
duration = time.perf_counter() - start
print(f"Execution time: {duration:.3f}s")

# Profiling (detailed breakdown)
profiler = cProfile.Profile()
profiler.enable()
result = slow_function()
profiler.disable()

stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)  # Top 20 slowest functions
```

### Step 2: Identify Bottleneck
Common bottlenecks:
- **I/O bound**: Network calls, file operations, database queries
- **CPU bound**: Heavy computation, parsing, serialization
- **Memory bound**: Large data structures, excessive allocations
- **Algorithmic**: O(n²) when O(n) possible, unnecessary work

### Step 3: Apply Optimization
Choose strategy based on bottleneck type:

#### I/O Optimization
```python
# BEFORE: Serial I/O
results = []
for item in items:
    results.append(fetch_data(item))  # Slow: 10s × 100 = 1000s

# AFTER: Parallel I/O
import concurrent.futures
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    results = list(executor.map(fetch_data, items))  # Fast: ~100s

# AFTER: Caching
@functools.lru_cache(maxsize=1000)
def fetch_data(item):
    return expensive_fetch(item)
```

#### CPU Optimization
```python
# BEFORE: Inefficient algorithm
def find_items(items, target):
    return [i for i in items if i.value == target]  # O(n) per search

# AFTER: Efficient data structure
items_by_value = {i.value: i for i in items}  # O(1) per search
def find_items(target):
    return items_by_value.get(target)

# BEFORE: Repeated computation
for i in range(1000):
    result = expensive_computation(data)  # Computed 1000 times

# AFTER: Compute once
result = expensive_computation(data)
for i in range(1000):
    use_result(result)
```

#### Memory Optimization
```python
# BEFORE: Load entire file into memory
with open('huge_file.txt', 'r') as f:
    lines = f.readlines()  # 10GB in memory
    for line in lines:
        process(line)

# AFTER: Stream processing
with open('huge_file.txt', 'r') as f:
    for line in f:  # One line at a time
        process(line)

# BEFORE: Keep all results
results = [expensive_process(i) for i in range(1000000)]

# AFTER: Generator for lazy evaluation
results = (expensive_process(i) for i in range(1000000))
```

### Step 4: Measure After (Verify Improvement)
```python
# Compare before and after
print(f"Before: {baseline_duration:.3f}s")
print(f"After: {optimized_duration:.3f}s")
print(f"Speedup: {baseline_duration / optimized_duration:.1f}x")
print(f"Time saved: {baseline_duration - optimized_duration:.3f}s")
```

### Step 5: Add Performance Test (Optional)
```python
import pytest

def test_performance_stays_under_threshold():
    """Ensure optimization maintains acceptable performance."""
    start = time.perf_counter()
    
    result = optimized_function(large_input)
    
    duration = time.perf_counter() - start
    
    # Fail if performance regresses
    assert duration < 5.0, f"Too slow: {duration:.3f}s (threshold: 5.0s)"
    assert result == expected_result  # Correctness still matters
```

## Acceptance Criteria

### Performance Improvement
- [ ] Measurable improvement (baseline vs optimized timings documented)
- [ ] Improvement is significant (not micro-optimization)
- [ ] Performance documented in commit message or issue comment

### Behavior Preservation
- [ ] All existing tests pass (behavior unchanged)
- [ ] Output is identical to before optimization
- [ ] Error handling unchanged

### Code Quality
- [ ] Optimization is clear and maintainable
- [ ] No premature optimization (bottleneck was measured)
- [ ] No excessive complexity for marginal gains
- [ ] Comments explain optimization rationale

### Testing
- [ ] Tests verify behavior unchanged
- [ ] Performance tests added if optimization is critical
- [ ] All pre-commit hooks pass
- [ ] 80%+ coverage on modified files

### Configuration (if applicable)
- [ ] Performance tuning options configurable
- [ ] Defaults work well for most users
- [ ] Documentation explains tradeoffs

## Complexity Guidelines

### Low Complexity (1-3 hours)
- Simple caching with `@lru_cache`
- Replace O(n²) with O(n) algorithm
- Reduce unnecessary work (early exit, skip redundant operations)
- Example: Cache validation gate results for 30s

### Medium Complexity (4-8 hours)
- Parallelize I/O-bound operations with ThreadPoolExecutor
- Optimize data structures (list → set, dict lookup)
- Stream processing instead of loading all into memory
- Example: Parallelize validation gate execution

### High Complexity (1-3 days)
- Implement async/await for concurrent operations
- Add database query optimization (indexes, query rewriting)
- Profile-guided optimization of hot paths
- Example: Refactor orchestrator to async/await

### Epic Complexity (4+ days)
- Architectural changes for performance
- Multi-component optimization
- Distributed processing
- Break into parent issue + child tasks
- Example: Distributed agent execution across machines

**For Epic-sized optimizations:**
```bash
# Create parent performance issue
bd create "Epic: Reduce orchestrator latency by 80%" -t epic -p 1 --json
bd label add <epic-id> performance orchestrator --json

# Create child tasks
bd create "Perf: cache beads queries" -t task -p 1 --parent <epic-id> --json
bd create "Perf: parallelize validation gates" -t task -p 1 --parent <epic-id> --json
bd create "Perf: optimize worktree creation" -t task -p 1 --parent <epic-id> --json
```

## Labels to Add
```bash
bd label add <issue-id> <component> performance --json
```

**Common component labels:**
- `orchestrator` - Orchestration loop and workflow
- `validation` - Quality gates and validation
- `beads` - Beads integration
- `agents` - AI agent integration

**Performance-specific labels:**
- `performance` - Performance optimization
- `caching` - Caching implementation
- `parallelization` - Parallel/concurrent execution
- `memory` - Memory optimization
- `cpu` - CPU optimization

## Example Issue Creation

### Caching Optimization
```bash
bd create "Perf: beads cache query results for 30s" \
  -t task \
  -p 2 \
  -d "Beads ready query is called multiple times per orchestrator loop, executing expensive query each time. Cache results for 30s to reduce latency. Baseline: ~5s per query. Target: <100ms from cache." \
  --design "Add @lru_cache(maxsize=128) with TTL to get_ready_work_items. Add config option for cache duration. Invalidate cache on update operations." \
  --acceptance "Query latency reduced from 5s to <100ms on cache hit. Behavior unchanged. Cache invalidated on updates. Configuration option added." \
  --json

bd label add <issue-id> beads performance caching --json
```

### Parallelization Optimization
```bash
bd create "Perf: validation parallelize gate execution" \
  -t task \
  -p 1 \
  -d "Validation gates run serially, taking ~60s total. Most gates are I/O bound and can run in parallel. Baseline: 60s serial. Target: <15s parallel with 4 workers." \
  --design "Use ThreadPoolExecutor to run gates concurrently. Add config for max_workers. Keep serial execution for gates that depend on others." \
  --acceptance "Validation time reduced from 60s to <15s. All gates still run and pass. Configuration for parallelism level. Tests verify behavior unchanged." \
  --json

bd label add <issue-id> validation performance parallelization --json
```

## Anti-Patterns to Avoid
- ❌ Optimizing without measuring (premature optimization)
- ❌ Micro-optimizations with negligible impact
- ❌ Breaking behavior for performance gains
- ❌ Making code unreadable for minor speedup
- ❌ Optimizing non-bottleneck code
- ❌ Not documenting performance improvement
- ❌ Not adding performance regression tests
- ❌ Over-engineering (complex solution for simple problem)

## Performance Best Practices

### Measure, Measure, Measure
- **Profile before**: Find the actual bottleneck
- **Measure after**: Verify improvement
- **Document results**: Baseline → Optimized timings
- **Add regression tests**: Prevent future slowdowns

### Choose Right Tool
- **I/O bound**: Threading, async/await, caching
- **CPU bound**: Better algorithms, profiling, Cython/C extensions
- **Memory bound**: Generators, streaming, better data structures

### Balance Tradeoffs
- **Readability vs Performance**: Prefer clear code unless bottleneck
- **Memory vs Speed**: Caching trades memory for speed
- **Complexity vs Gain**: Don't over-engineer for 5% improvement

### Low-Hanging Fruit First
1. Cache expensive operations
2. Avoid unnecessary work (early exit, lazy evaluation)
3. Use efficient data structures (set for membership, dict for lookup)
4. Parallelize I/O operations
5. Only then: algorithmic optimization, profiling

### When to Stop
Stop optimizing when:
- Performance is acceptable (meets user requirements)
- Cost of optimization exceeds benefit
- Code becomes unmaintainable
- No more obvious bottlenecks
