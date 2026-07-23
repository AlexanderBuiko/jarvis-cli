# Scenario: bad input is rejected in the UI

Goal: the UI refuses an invalid configuration value with a clear error.

1. Open the Jarvis web UI.
2. In **Configuration**, set Key `max_tokens`, Value `-100`, click **Set**.
   - Expect: the Result shows an error saying max_tokens must be a positive integer.

Pass if the Expect holds.
