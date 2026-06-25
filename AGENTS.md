# Repository instructions

## Training-data privacy

- Never read, inspect, preview, summarize, search, sample, or print training-data contents.
- Tools may access training data only when required to copy, hash, count, validate structurally, or run training.
- Tool output must not expose records, prompts, responses, examples, dataset rows, or text fragments to the agent.
- Prefer metadata-only checks such as existence, paths, file counts, byte sizes, checksums, exit codes, and aggregate statistics that cannot reconstruct content.
- Treat training logs as potentially containing dataset text. Do not print or inspect them unless output is filtered to known-safe operational lines.
- Run configurations, schemas, filenames, status files, and aggregate training metrics are not training data and may be inspected when needed.
