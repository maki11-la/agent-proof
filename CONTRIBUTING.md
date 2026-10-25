# Contributing to Agent Proof

Agent Proof is a small, deterministic checker. Contributions should keep it that way: a spec in, a pass or fail out, no model calls, no network required to run a proof.

## Set up

Python 3.10 or newer and git.

```bash
git clone https://github.com/maki11-la/agent-proof.git
cd agent-proof
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
agent-proof run proof.yaml
```

On Windows, activate the virtualenv with `.venv\Scripts\activate`.

## Tests

`python -m pytest` is the suite. Add or extend a test when you change a check, the spec schema, the report, or the exit codes. Tests use temporary directories and temporary git repositories. They do not need network and they do not call a model.

The examples under `examples/quickstart` and `examples/tiny-app` are executed by the suite and by CI. If you change their specs, keep them passing. `examples/git-gate` is a template; it is parsed, not run against this repository.

## Pull requests

- Describe the behavior change in the pull request, and update the README check reference if the spec schema changed.
- Keep new dependencies rare. File, process, YAML, and git access should stay in the standard library plus PyYAML unless there is a strong reason.
- Fail closed. A typo in a spec, a missing git ref, or a check that cannot be decided is a failure or a spec error, not a pass.
- Do not weaken `proof.yaml` to make a change look done. Fix the change.

## Reporting issues

Use the bug and feature templates. A spec is as powerful as a shell script: do not include secrets in an issue.

Security notes can go in a public issue as well. This tool does not phone home and does not run a service. The sensitive surface is the spec itself, which can execute any command the author writes.

## License

By contributing, you agree that your contributions are licensed under the MIT License in `LICENSE`.

Sponsoring ongoing maintenance is welcome at [github.com/sponsors/maki11-la](https://github.com/sponsors/maki11-la).
