# Git gate

`proof.yaml` in this directory is a template, not a check of the Agent Proof repository. Copy it to the root of a project an agent is editing and change `paths` and `since` to match that project.

It asks three questions:

- Does the working tree have changes under `src`, including untracked files?
- Is there at least one commit on `HEAD` that `main` does not have, touching `src`?
- Does `dist/report.json` exist, and is that file part of the diff against `HEAD`?

Run it from the repository root:

```bash
agent-proof run proof.yaml
```

`dirty: false` is the inverse: the working tree for those paths must be clean. Set `include_untracked: false` when ignored-or-untracked files should not count. The same `in_diff` field exists on `type: file` for one path or a glob.
