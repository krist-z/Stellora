---
name: google-cpp-style
description: >-
  Applies the Google C++ Style Guide when writing, refactoring, reviewing, or
  formatting C++ code. Use for .h/.cc/.cpp/.hpp/.inc files, C++ APIs, headers,
  scoping, classes, functions, ownership, naming, comments, formatting, and
  style reviews against Google C++ conventions.
---

# Google C++ Style Guide

Canonical guide: [Google C++ Style Guide](https://google.github.io/styleguide/cppguide.html).

This skill keeps **compressed rules + examples** per section. For full rationale, follow the official URL in each file. Target **C++20** (not C++23).

## Workflow

1. Identify which sections apply; **read those reference files** before editing or reviewing.
2. Prefer the smallest conforming change. Match local non-conformant style only in legacy regions ([background.md](background.md)).
3. **Formatting**: do not hand-format. Load [clang-format.txt](clang-format.txt) (see [formatting.md](formatting.md)).
4. Run project `cpplint` when available.

## Table of Contents

| Guide section | File | Official |
|---|---|---|
| Background, C++ Version, Exceptions | [background.md](background.md) | [link](https://google.github.io/styleguide/cppguide.html#Background) |
| Header Files | [headers.md](headers.md) | [link](https://google.github.io/styleguide/cppguide.html#Header_Files) |
| Scoping | [scoping.md](scoping.md) | [link](https://google.github.io/styleguide/cppguide.html#Namespaces) |
| Classes | [classes.md](classes.md) | [link](https://google.github.io/styleguide/cppguide.html#Classes) |
| Functions, cpplint | [functions.md](functions.md) | [link](https://google.github.io/styleguide/cppguide.html#Functions) |
| Other C++ Features | [features.md](features.md) | [link](https://google.github.io/styleguide/cppguide.html#Other_C++_Features) |
| Inclusive Language, Naming | [naming.md](naming.md) | [link](https://google.github.io/styleguide/cppguide.html#Naming) |
| Comments | [comments.md](comments.md) | [link](https://google.github.io/styleguide/cppguide.html#Comments) |
| Formatting | [formatting.md](formatting.md) | [link](https://google.github.io/styleguide/cppguide.html#Formatting) |

## Review priorities

1. Correctness, lifetime/ownership, UB, security
2. Banned/restricted features (exceptions, modules, nontrivial statics, RTTI abuse, …)
3. API clarity (`explicit`, `const`, parameters, copy/move intent)
4. Headers / IWYU / namespaces
5. Naming, comments, formatting (via clang-format)

Cite the specific guide subsection when reporting violations. Distinguish must-fix from suggestions.
