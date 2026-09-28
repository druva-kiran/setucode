---
name: test-generation
description: Guide for creating robust, isolated unit and integration tests.
activation_conditions:
  - test
  - pytest
  - unit test
  - test suite
---
# Test Generation Skill

## Instructions
1. Write tests using pytest idioms (e.g. fixtures, clear assert statements).
2. Cover positive path, negative path (error handling), and boundary edge cases.
3. Keep test names descriptive (`test_<behavior>_<expected_result>`).
4. Avoid over-mocking; test actual interface contracts where feasible.
5. Ensure tests are independent and deterministic.

## Examples
- `test_returns_expected_result_on_valid_input`
- `test_raises_value_error_on_invalid_argument`
