# Skill Authoring Standard

Use this standard for every skill under `.agent/skills`.

## Rules

- Match each kebab-case directory to frontmatter `name`.
- Include only `name` and an English `description` containing capability and concrete `Use when ...` triggers.
- Put UI metadata in `agents/openai.yaml`.
- Keep `SKILL.md` imperative, single-purpose, concise, and below 500 lines.
- Route detail to one-level `references/`; add a table of contents above 100 lines.
- Use tested `scripts/` for repeated fragile operations.
- Do not add per-skill README, changelog, installation guide, duplicate quick reference, cache, or bytecode files.
- Never duplicate canonical research. Route to `research/prd.md`, `research/style.md`, and `research/tech.md`.

## Cliora workflow

1. Start project work with `cliora-project-context`.
2. Inspect the repository before assuming packages, scripts, services, or directories.
3. Preserve product non-goals and trust boundaries.
4. Pair production skills with relevant review and testing skills.
5. Validate every skill with `quick_validate.py`, scan TODOs and broken links, run representative scripts, and forward-test high-risk skills.

## UI metadata

Use quoted strings for `interface.display_name`, `short_description` (25-64 characters), and a one-sentence `default_prompt` that explicitly mentions `$skill-name`. Add no optional fields unless required.
