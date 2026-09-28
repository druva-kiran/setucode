---
name: code-refactor
description: Guide for safely refactoring code for clarity, modularity, and maintainability.
activation_conditions:
  - refactor
  - clean code
  - simplify
  - extract function
---
# Code Refactoring Skill

## Instructions
1. Inspect the target code completely before making any changes.
2. Preserve existing public APIs and behavioral invariants.
3. Keep functions small, single-purpose, and clearly named.
4. Always apply unified diff patches cleanly with `edit_file`.
5. Verify tests after refactoring to ensure zero regressions.

## Examples
- Break down monolithic functions into smaller, composable helpers.
- Replace duplicate logic with shared utility functions.
- Simplify complex nested conditionals using early returns.
