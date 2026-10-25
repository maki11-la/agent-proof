# Agent Proof

Agent Proof checks an AI agent's "task complete" claim against a spec you wrote — files, commands, git, and JSON/YAML — and exits non-zero when the claim is false. It never calls a model.

## Security

A `type: command` check runs the command in the spec as your user, with your environment. There is no sandbox.

- A string `run` is a shell command. On macOS and Linux that is `sh -c`.
- A list `run` is executed directly, without a shell. It still runs as you.

Only run a spec you trust. Treat a spec you did not write the way you would treat a shell script someone sent you. The CLI itself does not call a model and does not open a network connection. A command inside the spec can, when the spec says to. Do not let an agent rewrite `proof.yaml` to turn a failing check green.

## Why it exists

Agents say the work is done when the tree is unchanged, the test command was never run, or a config key still has the old value. Reviewing that by hand does not scale, and asking a second model "did this succeed?" just moves the same failure into another prompt.

Agent Proof is the mechanical half of that review. You list the facts that must be true. The CLI checks those facts the same way every time, on a laptop or in CI, and prints a pass/fail report an agent can read with `--json`. If a check cannot be decided, the run fails.

## How it differs

Agent Proof does not watch sessions, schedule work, or score a trace. It checks the artifacts you name.

| Project | What it actually does |
| --- | --- |
| **Agent Proof** | Runs a declarative spec (`proof.yaml`) against files, commands, git, and JSON/YAML. No account, no daemon, no model. |
| **Traceplain** | Reads on-chain fund flow for crypto yield platforms and publishes a risk reading. It is not a repository checker. Nearby names that do touch agents: **Traceplane** records agent telemetry (traces, cost, latency) and stores it. **tracelint** lints a captured trace for structural defects, with no model in the loop. Agent Proof never reads a trace. It checks the files, commands, and git state named in the spec. |
| **AgentLens** | Local observability for coding-agent sessions (Codex, Claude, Cursor, and others): a UI and CLI over session logs. It helps you inspect what an agent did. It does not pass or fail the task. |
| **AgentCron** | A hosted MCP scheduler. An agent can ask it to notify someone later or call a webhook. It does not look at files, tests, or git state. |

Other tools sit closer and carry more workflow. [agent-audits](https://github.com/aiswarya797/agent-audits) keeps an evidence ledger and review notes. [Verik](https://github.com/veriks/verik) snapshots a turn and runs a built-in diff policy. [donegate](https://github.com/intrepideai/donegate) blocks test-deletion and lint-suppression against a session baseline. [ConstraintLoop](https://github.com/mauhpr/constraintloop) evaluates versioned contracts, including optional model rubrics. [agent-completion-gate](https://github.com/zhjai/agent-completion-gate) is a state machine around a protected manifest. Use those when you want their process. Use Agent Proof when you want one file and a deterministic exit code in any repo or CI job.

## Install

Python 3.10+ is the runtime. The job is files, subprocesses, YAML, and git. The standard library covers that except for a YAML parser, so the package depends only on PyYAML. `pipx` installs the CLI into its own environment, which keeps it off your project's dependencies. A normal virtualenv works the same way when you would rather not install pipx. A Python CLI matches a repository that already runs pytest, and it avoids adding Node for a tool with one dependency.

The distribution name on PyPI is `agent-proof`. Until the first release is published, install from a checkout (this is the quick start below). After publication:

```bash
pipx install agent-proof
# or, inside an existing virtualenv:
python -m pip install agent-proof
```

Both install the `agent-proof` command and the shorter `aproof` alias. `python -m agent_proof` runs the same CLI.

## Quick start

```bash
git clone https://github.com/maki11-la/agent-proof.git
cd agent-proof
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install .
agent-proof run examples/quickstart/proof.yaml
```

`pipx install .` from the same directory is the equivalent one-step install if you use pipx. A non-zero exit means at least one check failed.

`https://github.com/maki11-la/agent-proof` is the public address for this project. Cloning works after that GitHub repository exists. If you already have the files, skip the clone and start at `python -m venv .venv`.

From the repository root, `agent-proof` with no path discovers `proof.yaml`. Specs are also read from `proof.yml`, `.agent-proof.yaml`, and `agent-proof.yaml`, in that order.

`agent-proof init` writes a starter `proof.yaml`. `agent-proof validate proof.yaml` parses a spec and does not run it.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Every check passed |
| 1 | One or more checks failed |
| 2 | The spec or the command line is invalid, so nothing was proved |

## Example spec

This is [`examples/quickstart/proof.yaml`](examples/quickstart/proof.yaml). `root: ../..` is resolved from the spec file, so the command works from any working directory. Paths inside checks are relative to that root.

```yaml
version: 1
name: quickstart
root: ../..
checks:
  - name: readme exists and states the pitch
    type: file
    path: README.md
    exists: true
    min_bytes: 400
    contains: "Agent Proof"
    matches: "pipx install"

  - name: license is MIT
    type: file
    path: LICENSE
    contains: "MIT License"

  - name: scratch file was not left behind
    type: file
    path: scratch.tmp
    exists: false

  - name: package modules are present
    type: file
    glob: src/agent_proof/*.py
    min_matches: 5

  - name: console script is declared
    type: file
    path: pyproject.toml
    contains: 'agent-proof = "agent_proof.cli:main"'

  - name: sponsors file names the maintainer
    type: yaml
    path: .github/FUNDING.yml
    equals:
      github: maki11-la

  - name: python runs
    type: command
    run: [python3, -c, "print('agent-proof-ok')"]
    timeout: 15
    stdout_contains: agent-proof-ok
```

[`examples/tiny-app`](examples/tiny-app) is a self-contained fixture (JSON paths, YAML values, a glob, a missing file, a command). [`examples/git-gate`](examples/git-gate) is a template for "the branch changed `src`"; it is not run in CI because it depends on your branch. [`examples/ci/workflow.yml`](examples/ci/workflow.yml) is a job you can paste into another repository.

## Example output

Text goes to the terminal. `PASS` is green and `FAIL` is red when stdout is a TTY. `NO_COLOR` or `--no-color` turns that off. `--color=always` forces it. Timings below are from a real run of [`examples/tiny-app`](examples/tiny-app); a later run will differ by milliseconds.

```text
Agent Proof 0.1.0
tiny-app  examples/tiny-app/proof.yaml
Self-contained example. Paths are relative to this directory.

  PASS  readme names the app  0ms
        README.md exists (209 bytes); contains "tiny-app"

  PASS  scratch file is absent  0ms
        scratch.tmp does not exist

  PASS  source file says hello  0ms
        1 file matched src/*.txt; each is at least 5 bytes; each contains "hello"

  PASS  manifest name, port, and first feature  0ms
        app.json: 5 values matched

  PASS  beta flag is off  0ms
        config.yaml: 2 values matched

  PASS  greeting command  9ms
        exited 0; stdout contains "hello tiny-app"

────────────────────────────────────────────────────────────────────────
PASS  6 passed, 0 failed, 6 total  in 11ms
```

A failing spec names the check and the evidence. This one expected a README phrase and a successful test command:

```text
Agent Proof 0.1.0
sample failure  proof.yaml

  FAIL  readme mentions install  0ms
        README.md does not contain "pipx install"

  FAIL  tests passed  9ms
        exited 1, expected 0
        stdout:
          1 failed

────────────────────────────────────────────────────────────────────────
FAIL  0 passed, 2 failed, 2 total  in 9ms
```

That process exits 1.

`--json` is for agents and CI. It is the only thing written to stdout, so it can be piped. `ok` is false when any check failed. `stopped_early` is true when fail-fast skipped the rest; `summary.planned` is the full list and `summary.total` is how many ran. `root` is the absolute project root. This document is the tiny-app report with the `checks` array cut down to the command check; the summary still counts all six:

```json
{
  "ok": true,
  "tool": "agent-proof",
  "version": "0.1.0",
  "spec": "examples/tiny-app/proof.yaml",
  "name": "tiny-app",
  "description": "Self-contained example. Paths are relative to this directory.",
  "root": "/path/to/examples/tiny-app",
  "stopped_early": false,
  "summary": {
    "passed": 6,
    "failed": 0,
    "total": 6,
    "planned": 6,
    "duration_ms": 11
  },
  "checks": [
    {
      "name": "greeting command",
      "type": "command",
      "ok": true,
      "duration_ms": 9,
      "message": "exited 0; stdout contains \"hello tiny-app\"",
      "details": {
        "command": "python3 -c \"print('hello tiny-app')\"",
        "exit_code": 0,
        "expected_exit_code": 0,
        "timed_out": false,
        "stdout": "hello tiny-app\n",
        "stderr": ""
      }
    }
  ]
}
```

A spec that cannot be parsed exits 2. With `--json` the shape is `{"ok": false, "error": "...", "checks": []}` and the run did not count as a pass.

## Check reference

`version` must be `1`. `name` and `description` are optional. `fail_fast: true` stops after the first failure. `root` is a relative path from the spec file (it may contain `..`). The CLI flag `--root` overrides it. If you set neither, paths are relative to the current working directory.

Checks run in order. Unknown fields are errors. Duplicate check names are errors. Duplicate YAML or JSON keys inside the spec are errors.

Paths are relative, use forward slashes, and must not contain `..`. A string `run` is a shell command (`sh -c` on POSIX). A list `run` is executed without a shell and is the better default.

### `type: file`

| Field | Meaning |
| --- | --- |
| `path` or `glob` | One path, or a glob of files under the root. Set one of them. |
| `exists` | Default `true`. `false` means the path is absent, or the glob matches nothing. |
| `min_bytes` | Size of each matched file. |
| `contains`, `not_contains` | Literal substring. |
| `matches` | Python regular expression, searched with `re.MULTILINE` (`$` matches at each line end). `.` does not match newlines. |
| `min_matches`, `max_matches` | Glob only. `min_matches` defaults to 1 when the files must exist. |
| `modified_after` | ISO-8601 timestamp, or an unquoted YAML timestamp. A bare date is midnight UTC. "After" is strict. |
| `modified_within` | A duration with a unit: `30s`, `5m`, `2h`, `1d`. |
| `in_diff` | Whether the path is in the diff against `diff_base` (default `HEAD`). |
| `diff_base` | Git ref. Requires `in_diff`. |
| `include_untracked` | Default `true`. Untracked files count as part of the diff. Requires `in_diff`. |

A path is in the diff when the worktree or the index differs from `diff_base`, or when it is untracked. A directory matches when any file under it differs. `exists: false` together with `in_diff: true` is how you prove a file was deleted. Content checks are refused when `exists` is false. Text checks require UTF-8 and refuse files larger than 8 MiB.

### `type: command`

A command check executes whatever `run` contains. A string is a shell command (`sh -c` on macOS and Linux). A list is executed directly, without a shell. Both run as you, with your environment. Read [Security](#security) before you run a spec you did not write.

| Field | Meaning |
| --- | --- |
| `run` | Required. A string (shell) or a list (no shell). |
| `cwd` | Relative directory under the root. Default: the root. |
| `exit_code` | Default `0`. Any integer is allowed, so a check can require a non-zero status. |
| `timeout` | Seconds, or a duration (`30s`, `2m`). Default 60. Maximum 24 hours. The process group is killed on timeout. |
| `env` | Extra environment variables. Values may be strings, numbers, or booleans (`true` / `false`). |
| `stdout_contains`, `stdout_not_contains`, `stdout_matches` | Applied to stdout. `matches` is a Python regex. |
| `stderr_contains`, `stderr_not_contains`, `stderr_matches` | Same, for stderr. |

The child process inherits your environment, so it sees the same `PATH` you do. Output over 2,000,000 characters fails the check. The JSON report keeps up to 16,000 characters of each stream.

### `type: git`

Set `dirty`, `since`, or both. Every condition you set must hold.

| Field | Meaning |
| --- | --- |
| `paths` | Optional file or directory pathspecs, relative to the root. Omit them to mean the whole tree. |
| `dirty` | `true`: those paths have staged, unstaged, or untracked changes. `false`: they are clean. |
| `include_untracked` | Default `true`. Set `false` so untracked files do not count as dirty. |
| `since` | A git ref. The check counts commits reachable from `HEAD` and not from the ref (`git rev-list ref..HEAD`). |
| `min_commits` | Default 1. Requires `since`. |

Git is discovered from the project root upward. A missing `git` binary, a directory that is not a repository, or a ref that does not exist fails the check.

### `type: json` and `type: yaml`

| Field | Meaning |
| --- | --- |
| `path` | Required file. |
| `equals` | Mapping of path to expected value. Set this, `exists`, or both. |
| `exists` | List of paths that must be present. The value may be null. |

Paths are dot keys (`server.port`), bracket indexes (`features[0]`), or a digit segment on a list (`features.1`). A digit is a string key when the current value is an object. The expected value can be a scalar, a list, or an object. Objects must match exactly, keys and values; use a dotted path when you only care about one field.

Numbers are strict: JSON `1` (an integer) does not match `1.0` (a float), and booleans are not integers. YAML 1.1 rules apply to YAML files and to the spec, so unquoted `yes`/`no` are booleans and unquoted timestamps are times. Quote them when you want strings. A YAML file must contain one document.

## CI

Run the proof after the steps that produce the artifacts. Publish `agent-proof` to PyPI and install it, or install from git:

```yaml
name: agent-proof
on: [push, pull_request]
jobs:
  proof:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install agent-proof
      - run: agent-proof run proof.yaml
```

From a checkout of this repository the install line is `python -m pip install .`. The workflow that tests Agent Proof itself is [`.github/workflows/ci.yml`](.github/workflows/ci.yml): pytest on Python 3.10–3.13, then the repository proof and the examples, plus a second job that installs the package into a fresh virtualenv and runs the same specs.

`--json` is the machine-readable form if a later step needs the report. The exit code is enough to fail the job.

## Use with AI agents

Put the spec in the repo before the agent starts, and tell the agent it does not get to declare success. For example:

```text
When you believe the task is complete, do not say that it is done.
Run: agent-proof run proof.yaml --json
Exit 0 is the only completion signal. A failed check is still your bug.
Do not edit proof.yaml, and do not delete or skip a check, unless I asked you to change the spec.
If the command cannot be run, say so. Do not invent a pass.
```

The same command belongs in a stop hook, a task runner, or the last step of a pull-request workflow. The agent sees the JSON. You see the text report. Neither of you has to re-read the diff to answer "did the file land, and did the tests exit 0?"

### Trust the spec

The full warning is in [Security](#security). `type: command` runs whatever the spec says, with your user account and your environment. Agent Proof does not sandbox it, and it does not phone home. Only run a spec you would run as a shell script. Do not let an agent rewrite the spec to make a red check green. The spec is the contract; the diff is the work.

## Roadmap

The 0.1 checks are file, command, git, and JSON/YAML. Later, without turning this into a platform:

- `sha256` pins on files
- a `warn` severity that prints but does not fail the process
- JUnit XML and SARIF alongside `--json`
- shell completion and a published JSON Schema for editor diagnostics
- `http` checks (status and body) for projects that already started a server
- a `proof.yaml` import so a repo can share one fragment across specs

Not planned: model judges, session recording, hosted accounts, or a daemon.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bugs and ideas use the [issue templates](.github/ISSUE_TEMPLATE). The license is MIT.

## Sponsors

Agent Proof is free and open source, maintained by [maki11-la](https://github.com/maki11-la). If it saves you from a confident agent and a broken tree, consider sponsoring the work.

[Sponsor on GitHub](https://github.com/sponsors/maki11-la)

The sponsor button is wired in [`.github/FUNDING.yml`](.github/FUNDING.yml).
