# Scenario: task lifecycle (create → verify → delete → verify)

Goal: a user can create a task through the UI, see it in the list, remove it, and
confirm it is gone. Drive the real form buttons — do not use the command box.

1. Open the Jarvis web UI.
2. In **Tasks**, type `agent-demo` into the Name field and click **Create task**.
   - Expect: the Result shows the task was created, with an id.
3. Click **List tasks**.
   - Expect: `agent-demo` appears in the list. Note its id.
4. Type that id into the Id field and click **Delete task**.
   - Expect: the Result confirms the task was deleted.
5. Click **List tasks** again.
   - Expect: `agent-demo` is no longer listed.

Pass if every Expect holds.
