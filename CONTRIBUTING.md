# Contributing

Bug reports and pull requests are welcome. For a bug, include your Python version,
the command or MCP tool you called, what you expected and what happened. Use a
small, non-sensitive input; don't upload your conversation history. Follow
[the security policy](SECURITY.md) for private reports.

[Development](docs/development.md) explains the source layout and gives the test
commands. [The example index](examples/README.md) distinguishes current recordings
from compatibility fixtures and generated output.

Keep changes focused. When changing a parser or MCP tool, add a regression test
for the affected records and update [the tool reference](docs/mcp.md) if its
behaviour changes. Preserve source references and pagination handles. Regenerate
derived examples with their owning tools rather than editing the outputs.

Before opening a pull request, run the checks in the development guide. Changes
to installation or package data should also pass the distribution check there.
Contributions are licensed under the project's [Apache-2.0 licence](LICENSE).
