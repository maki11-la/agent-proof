# Examples

| Path | What it shows |
| --- | --- |
| [`quickstart/proof.yaml`](quickstart/proof.yaml) | The spec from the README. Checks this repository. Run it from anywhere: `agent-proof run examples/quickstart/proof.yaml`. |
| [`tiny-app/`](tiny-app/) | A tiny fixture project: files, a glob, JSON paths, YAML values, a missing file, and a command. |
| [`git-gate/`](git-gate/) | A template for "the agent changed `src` and committed". Not executed in CI. |
| [`ci/workflow.yml`](ci/workflow.yml) | A GitHub Actions job to paste into another repository. |

The repository root `proof.yaml` is the gate for Agent Proof itself. `agent-proof` with no spec path finds it when you run the command from the repository root.
