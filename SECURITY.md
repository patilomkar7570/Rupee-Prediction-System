# Security and safe operation

- The local API is configured to listen on `127.0.0.1`. Do not change it to `0.0.0.0` or expose it to a public network without a separate security review and appropriate authentication.
- Do not commit secrets, private market files, local reports, or manually entered data. `runtime/` is ignored by Git by default.
- Optional headline explanations call a local Ollama service at `127.0.0.1:11434`; the app sends the selected headlines to that local endpoint. Review your local Ollama setup and model before use.
- This research prototype is licensed under the PolyForm Noncommercial License 1.0.0; that license does not grant commercial-use permission. The project is not an execution platform and should not be treated as financial advice.

For a suspected vulnerability, open a private security advisory in the repository if that feature is available, rather than publishing exploit details in an issue.
