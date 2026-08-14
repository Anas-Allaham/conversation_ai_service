# Content provenance policy

1. Every production item must declare `source: original_project_item`.
2. No prompt, recording, image, scoring key, or sample answer from a proprietary examination may enter the repository.
3. AI may assist offline drafting and review; production runtime generation is forbidden.
4. Each item receives a stable ID, semantic version, author field, reviewer field, review date, status, and notes.
5. Only `active` items with approved review metadata may be selected.
6. Retired items remain versioned for historical interpretation but are never selected for new sessions.
7. The project name and result must not imply certification or endorsement by the Council of Europe or any examination provider.
8. The owner explicitly chose not to pursue a licensing inquiry for this MVP because no third-party questions are used.

The original bank was drafted specifically for this project and frozen as version 0.1.0. Version 0.1.1 preserves all scored questions and adds fixed clarification prompts for learner support. Version 0.2.0 revises the A2 appointment item to state the service and role-play conditions explicitly, renames the extra form a boundary item, and preserves stable versioned IDs for interpretation and rollback. Before formal human pilot reporting, one named project team member should record final owner approval in the item metadata; the current AI-assisted review label must not be presented as independent expert validation.
