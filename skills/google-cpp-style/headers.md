# Header Files

Full guide: [Header Files](https://google.github.io/styleguide/cppguide.html#Header_Files)

## Rules

- Every `.cc` should usually have a matching `.h` (exceptions: tests, `main`-only files).
- Headers must be **self-contained** (compile alone), end in `.h`. Rare include fragments use `.inc`.
- Use `#define` guards: `<PROJECT>_<PATH>_<FILE>_H_` from the path under the project root. No `#pragma once`.
- **Include What You Use (IWYU)** — include what you reference; do not rely on transitive includes. `foo.cc` includes `bar.h` even if `foo.h` already does.
- Prefer `#include` over forward declarations.
- Put inline/template definitions in the header (directly or via includes); do not use `-inl.h` split files.
- Include order: related header → C system → C++ library → other libraries → project headers. Within each section, lexicographic. Separate sections with a blank line. Use quotes for project headers, `<>` for others.

## Examples

```cpp
// Good: guard + IWYU + include order
#ifndef MYPROJ_FOO_BAR_H_
#define MYPROJ_FOO_BAR_H_

#include <memory>
#include <string>

#include "myproj/foo/baz.h"

namespace myproj {

class Bar {
 public:
  explicit Bar(std::string name);
  const std::string& name() const { return name_; }

 private:
  std::string name_;
};

}  // namespace myproj

#endif  // MYPROJ_FOO_BAR_H_
```

```cpp
// Bad: no guard, forward-decl instead of include, wrong order
#pragma once
class Baz;              // prefer #include "baz.h"
#include "myproj/foo/baz.h"
#include <string>       // C++ includes should come before project includes
```
