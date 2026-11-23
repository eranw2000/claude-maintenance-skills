- **Decisions are the user's, asked early** (AskUserQuestion, in parallel with any running
  agents): scope, enforcement depth (deterministic hooks vs agent checklists vs both;
  default to BOTH, the guard+net pattern), new artifact vs extending an existing one.
  Hand the user the whole inventory first, worst first by what each miss cost and how often.
- **Artifact-type selection:** auto-trigger on a tool event = hook; isolated one-shot
  judgment report = agent; interactive multi-step workflow = skill; a behavior rule =
  CLAUDE.md (a pointer to a separate file when the detail is large); an observational fact
  = memory. Every new skill, agent or command gets a `model:` choice that follows your
  model-routing rule, recorded in the same change.
