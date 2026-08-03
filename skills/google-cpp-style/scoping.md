# Scoping

Full guide: [Namespaces](https://google.github.io/styleguide/cppguide.html#Namespaces) · [Internal Linkage](https://google.github.io/styleguide/cppguide.html#Internal_Linkage) · [Local Variables](https://google.github.io/styleguide/cppguide.html#Local_Variables) · [Static and Global Variables](https://google.github.io/styleguide/cppguide.html#Static_and_Global_Variables) · [thread_local](https://google.github.io/styleguide/cppguide.html#thread_local)

## Rules

- Place all code in namespaces (project/library named). No `using namespace` in headers; avoid in `.cc` except limited local scopes. Do not use inline namespaces indiscriminately.
- Unnamed namespaces or `static` for internal linkage in `.cc` files. Do not use unnamed namespaces in headers.
- Prefer nonmember functions in a namespace over free-floating globals; prefer static members only when they need private access.
- Declare variables in the narrowest scope; initialize at declaration when possible.
- **Namespace-scope / static storage**: only **trivially destructible** types. No nontrivial dynamic initialization at namespace scope when avoidable. Function-local statics OK if careful.
- `thread_local` at class/namespace scope must be `constinit` (true compile-time constant init). Prefer function-local `thread_local` when possible.

## Examples

```cpp
// Good
namespace myproj {
namespace foo_internal {
void Helper();  // .cc-only detail; or unnamed namespace in .cc
}  // namespace foo_internal

void Process() {
  int count = 0;  // narrow scope, initialized
  static int call_count = 0;  // function-local static OK
  ++call_count;
}
}  // namespace myproj
```

```cpp
// Bad
using namespace std;           // especially in a header
static std::string g_path;    // nontrivial dtor + dynamic init at namespace scope
thread_local std::string t;   // needs constinit / not compile-time constant
```
