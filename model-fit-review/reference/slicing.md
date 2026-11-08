# Slicing a large tree into reads a reader can hold

One reader holds about 60K to 85K tokens of files comfortably (240K to 340K chars). Cut by
FAMILY, not by size alone, so each reader sees the siblings that share blocks and can name the
duplicate. Group skills that share a purpose, for example:

1. Planning: requirements, design, spec and test-first skills.
2. Ship and review: pull request, release, review and publish skills.
3. Session and save: the skills that save, close and resume a session.
4. Maintenance: the skills that look after the setup itself.
5. Project skills: the ones written for one project or one service.
6. Deliverables and commands: documents, diagrams, slides, and the slash commands.
7. All agents.


Rebuild the list from `scripts/inventory.py --json` each run: new
skills join the family they belong to, and a family over 350K chars splits in two.
