# Scoping

Full guide: [Namespaces](https://google.github.io/styleguide/cppguide.html#Namespaces) · [Internal Linkage](https://google.github.io/styleguide/cppguide.html#Internal_Linkage) · [Nonmember / Static / Global](https://google.github.io/styleguide/cppguide.html#Nonmember,_Static_Member,_and_Global_Functions) · [Local Variables](https://google.github.io/styleguide/cppguide.html#Local_Variables) · [Static and Global Variables](https://google.github.io/styleguide/cppguide.html#Static_and_Global_Variables) · [thread_local](https://google.github.io/styleguide/cppguide.html#thread_local)

Each topic: rule → official link → good / bad examples.

---

### Namespaces

Place nearly all code in named namespaces (project / library). Do not use `using namespace` in headers; avoid it in `.cc` except in limited local scopes. Close namespaces with a trailing comment. Do not use inline namespaces indiscriminately.

[Namespaces](https://google.github.io/styleguide/cppguide.html#Namespaces)

```cpp
// Good
namespace myproj {
namespace foo {

void Process();

}  // namespace foo
}  // namespace myproj

// .cc only, limited scope:
void F() {
  using ::absl::StrCat;  // specific using-declaration OK
}
```

```cpp
// Bad
using namespace std;              // especially in a header
namespace myproj {
void Process();
}                                // missing // namespace myproj
inline namespace v2 { /* ... */ } // without a strong ABI / versioning need
```

---

### Internal Linkage

In `.cc` files, prefer an unnamed namespace (or `static`) for file-local helpers. Do **not** put unnamed namespaces in headers.

[Internal Linkage](https://google.github.io/styleguide/cppguide.html#Internal_Linkage)

```cpp
// Good — foo.cc
namespace {
constexpr int kBufSize = 256;
void Helper() { /* ... */ }
}  // namespace

namespace myproj {
void PublicApi() { Helper(); }
}  // namespace myproj
```

```cpp
// Bad — foo.h
namespace {           // ODR / duplicate symbols across TUs
void Helper();
}  // namespace

static void HelperInHeader();  // same problem in a header
```

---

### Nonmember, Static Member, and Global Functions

Prefer nonmember functions in a namespace over free globals. Use static members only when they need private access. Prefer placing related free functions with the type they operate on (same header / namespace).

[Nonmember, Static Member, and Global Functions](https://google.github.io/styleguide/cppguide.html#Nonmember,_Static_Member,_and_Global_Functions)

```cpp
// Good
namespace myproj {

class Foo {
 public:
  static Foo FromConfig(const Config& c);  // needs private ctor / state
 private:
  explicit Foo(State s);
};

int ByteSize(const Foo& foo);  // nonmember; uses only public API

}  // namespace myproj
```

```cpp
// Bad
void ProcessFoo(Foo* foo);  // in the global namespace

class Foo {
 public:
  static int ByteSize(const Foo& foo);  // no private access needed — prefer nonmember
};
```

---

### Local Variables

Declare in the narrowest scope. Initialize at the point of declaration when possible. Avoid long-lived uninitialized locals.

[Local Variables](https://google.github.io/styleguide/cppguide.html#Local_Variables)

```cpp
// Good
void Process(const std::vector<int>& items) {
  for (int item : items) {
    int squared = item * item;
    Use(squared);
  }
  absl::StatusOr<Result> result = Compute();
  if (!result.ok()) return;
  Commit(*result);
}
```

```cpp
// Bad
void Process(const std::vector<int>& items) {
  int squared;           // uninitialized; scope too wide
  Result result;
  for (int item : items) {
    squared = item * item;
    Use(squared);
  }
  result = Compute().value();  // late init, easy to misuse
}
```

---

### Static and Global Variables

Namespace-scope / static-storage objects must be **trivially destructible**. Avoid dynamic initialization at namespace scope when possible. Function-local statics are OK when careful (const / no nontrivial teardown issues).

[Static and Global Variables](https://google.github.io/styleguide/cppguide.html#Static_and_Global_Variables)

```cpp
// Good
namespace myproj {
constexpr int kMaxRetries = 3;           // trivial
constinit int g_counter = 0;             // trivial, no dynamic init
absl::NoDestructor<std::string> g_name; // approved pattern for nontrivial types
}  // namespace myproj

void F() {
  static const int kN = ExpensiveButSafeInit();  // function-local OK
}
```

```cpp
// Bad
namespace myproj {
std::string g_path = GetPath();   // dynamic init + nontrivial destructor
static std::mutex g_mu;           // nontrivial destructor at exit
}  // namespace myproj
```

---

### `thread_local` Variables

Prefer function-local `thread_local` when possible. At class or namespace scope, initialize with a true compile-time constant and enforce with `constinit` (or `constexpr` when applicable).

[thread_local](https://google.github.io/styleguide/cppguide.html#thread_local)

```cpp
// Good
void Handle() {
  thread_local int hits = 0;  // function-local
  ++hits;
}

namespace myproj {
constinit thread_local int tls_id = 0;  // compile-time constant init
}  // namespace myproj
```

```cpp
// Bad
namespace myproj {
thread_local std::string tls_name;           // dynamic / nontrivial
thread_local int tls_id = NextId();          // not a constant initializer
}  // namespace myproj
```
