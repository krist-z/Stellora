# Inclusive Language and Naming

Full guide: [Inclusive Language](https://google.github.io/styleguide/cppguide.html#Inclusive_Language) · [Naming](https://google.github.io/styleguide/cppguide.html#Naming)

## Rules

- Use inclusive, gender-neutral language in names and comments (avoid master/slave, blacklist/whitelist, etc.).
- **Files**: `snake_case`, match what they define when practical (`foo_bar.h` / `foo_bar.cc`).
- **Types / concepts**: `PascalCase` (`UrlTable`, `Hashing`).
- **Variables / data members**: `snake_case`; class members often end with `_` (`table_name_`).
- **Constants**: `k` + PascalCase (`kDaysInAWeek`) for true constants; `enum` enumerators like constants or `PascalCase` per local convention in the guide.
- **Functions**: `PascalCase` for regular functions and methods (`AddTableEntry()`, `DeleteUrl()`).
- **Namespaces**: `snake_case`, short, top-level project name; avoid `using` that flattens into other namespaces.
- **Template params**: `PascalCase` or short `T`, `U`; concepts like types.
- **Macros**: `ALL_CAPS_WITH_UNDERSCORES`, rare and project-prefixed.
- Prefer descriptive names; abbreviations only if widely known (`Rpc`, `i` for loop index).

## Examples

```cpp
// Good
constexpr int kMaxRetries = 3;
class UrlTable { /* ... */ };
void DeleteUrl(UrlTable* table, std::string_view url);
int num_entries_;  // member

// Bad
int MaxRetries = 3;           // should be kMaxRetries
void delete_url();            // functions are PascalCase
int m_numEntries;             // not Google (no m_ Hungarian)
std::string blacklist;        // prefer denylist / blocklist
```
