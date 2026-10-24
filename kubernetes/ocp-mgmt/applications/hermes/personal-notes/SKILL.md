---
name: personal-notes
description: Capture personal notes, journals, project details, tasks, and reminders from Signal Note to Self; retrieve and update the authoritative SilverBullet pages.
---

# Personal notes

Use `personal_notes` for durable notes and tasks. SilverBullet is authoritative;
Hermes memory and todo are not substitutes. Every write needs a saved capture ID.
Signal inputs already have one. Never invent an ID or claim an unsaved action.

Work the user wants to do belongs in `create_task`, even without a due date,
reminder, or project. Use `note` for information to keep. Do not invent a project
name or require a deadline to create a task.

If a capture reference is rejected, no plan or action has been written. Copy the
exact 32-character capture ID from the current input and retry the same operations
unchanged. Never turn a failed task into a note saying "Task created". If the
reference still fails, report the failure and retain the requested intent. Once a
plan exists, use that frozen plan on retry; do not replace it to bypass an error.

1. Read the immutable capture and its source time in America/Toronto. Separate
   independent intents: project facts, tasks, reminders, journal observations.
2. Use `find_pages`, `read_page`, and `list_tasks` to resolve existing projects and
   stable task IDs. Ask when multiple projects/tasks match. Do not create a second
   task merely to change its due date, snooze it, complete it, or cancel a reminder.
3. Ask before acting on materially ambiguous measurements, low-confidence speech,
   or uncertain dates. Preserve uncertainty in a note; never silently repair a
   measurement. A clarification is a new capture and may cite the earlier one.
4. Resolve “tomorrow” against the source timestamp, not the machine's UTC date.
   Ask for a time if none was supplied. A task due date is independent of a
   reminder. Use Toronto's actual UTC offset for that date. During the autumn
   repeated hour, ask which occurrence; reject nonexistent spring times. Confirm
   dates in the past rather than silently shifting them.
5. Before `apply_capture`, read `Inbox/Plans/CAPTURE_ID.md`. If it exists, reuse
   its JSON operations exactly. A partly completed plan cannot be replaced.
   Corrections go through a new follow-up capture. Otherwise construct all the
   requested operations together; the tool freezes them before applying effects.
6. Inspect every result. Report successful pages with links and exact reminder
   times; identify failed/unattempted actions. Retry the same plan after a service
   failure. Never say “reminder sent” when only its schedule was saved.

Example input: “For Garage, the opening is 82 centimetres. Remind me tomorrow at
10 to check the fitting size. Today was productive but I spent too long on DNS.”
After checking Garage, use `project`, `create_task` (project Garage, no invented
due date, explicit tomorrow 10:00 Toronto reminder), and `journal` (capture date).
Keep the original transcript and its source citations. The reminder worker sends
the alert independently of the LLM and ignores completed tasks.

For retrieval, search the relevant prefix and read matching pages before answering.
For completion, use the existing task ID. `reschedule_task` changes only `due`;
`schedule_reminder`/`snooze_reminder` changes `remind_at`; `cancel_reminder` clears it.
Standalone reminders are tasks without a due date. The Tasks page shows delivery
failures; do not promise a phone notification merely because ntfy accepted it.
