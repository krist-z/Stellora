# Formatting

Full guide: [Formatting](https://google.github.io/styleguide/cppguide.html#Formatting)

Do **not** apply formatting rules by hand. Use clang-format with the Google style dump shipped in this skill.

## Config file

- [clang-format.txt](clang-format.txt) — `clang-format --style=Google --dump-config` output (Google built-in style expanded).

## How to run

From this skill directory, or after copying the file into a project:

```bash
# One-off against the skill config (clang-format 14+)
clang-format -style=file:/absolute/path/to/clang-format.txt -i path/to/file.cc

# Project default: copy to repo root as .clang-format
cp clang-format.txt /path/to/project/.clang-format
clang-format -i path/to/file.cc

# Equivalent without a file
clang-format -style=Google -i path/to/file.cc
```

## Agent rules

1. Before finishing C++ edits under this skill, run clang-format with this config (or `-style=Google` / project `.clang-format` based on Google).
2. Do not restate line-length, brace, or whitespace rules from the guide — the config encodes them (80 columns, 2-space indent, etc.).
3. If the project already has a `.clang-format`, prefer that file; only fall back to this skill’s [clang-format.txt](clang-format.txt) when enforcing Google style explicitly.
