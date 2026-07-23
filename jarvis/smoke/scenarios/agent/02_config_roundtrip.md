# Scenario: configuration round-trip

Goal: a value set in the UI is kept for the session. Use the Configuration form.

1. Open the Jarvis web UI.
2. In **Configuration**, set Key `temperature`, Value `0.5`, click **Set**.
   - Expect: the Result reads `Updated: temperature = 0.5`.
3. Click **Show config**.
   - Expect: the Result lists `temperature = 0.5`.

Pass if every Expect holds.
