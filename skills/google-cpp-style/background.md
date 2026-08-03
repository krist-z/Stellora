# Background, C++ Version, Exceptions

Full guide: [Background](https://google.github.io/styleguide/cppguide.html#Background) · [C++ Version](https://google.github.io/styleguide/cppguide.html#C++_Version) · [Exceptions to the Rules](https://google.github.io/styleguide/cppguide.html#Exceptions_to_the_Rules)

## Rules

- Optimize for the **reader**; prefer consistency over personal taste.
- Target **C++20**; do not use C++23 features.
- Do not use [nonstandard extensions](https://google.github.io/styleguide/cppguide.html#Nonstandard_Extensions) unless wrapped for portability.
- When editing **existing non-conformant** code, match local style rather than drive-by reformatting the whole file.
- On Windows, still follow Google naming/guards; wrap `__declspec` etc. in macros (`DLLIMPORT` / `DLLEXPORT`). Do not use `#pragma once`.

## Examples

```cpp
// Good: C++20, portable
#include <optional>
std::optional<int> MaybeParse(std::string_view s);

// Bad: C++23-only / nonstandard without wrapper
#include <stdfloat>           // if project is still on C++20
__declspec(dllexport) void F();  // use DLLEXPORT macro instead
#pragma once                     // use #ifndef PROJECT_PATH_FILE_H_
```
