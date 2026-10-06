"""Owner Development Policy: the project-neutral development operating policy.

Reusable by each of the Owner's independent projects (listed in README.md); each project instantiates it
independently inside its own development environment through a project adapter.

Dependency rule: this package is stdlib-only and imports nothing from any project or from the
Personal Command Center. Projects depend on it; it never depends on them. See README.md.
"""

OWNER_POLICY_VERSION = "owner-dev-policy.v1"
