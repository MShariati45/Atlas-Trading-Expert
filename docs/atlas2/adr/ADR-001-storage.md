# ADR-001 — P0 Storage

Owner: Ali Shariati
Status: Accepted

Use one SQLite database (`atlas.sqlite3`) plus a content-addressed raw-blob directory.
All evidence tables are immutable; aggregate completion is represented by seal/terminal rows, not mutable status columns.
No ORM, server database, message bus, or second evidence database in P0.

Revisit only if measured P0/P1 load proves SQLite inadequate.
