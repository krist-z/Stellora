# Other C++ Features

Full guide: [Other C++ Features](https://google.github.io/styleguide/cppguide.html#Other_C++_Features)

Each topic: rule → official link → good / bad examples.

---

### Ownership and Smart Pointers

Prefer single ownership; transfer with `std::unique_ptr`. Avoid `shared_ptr` unless immutable and justified. Never `auto_ptr`.

[Ownership and Smart Pointers](https://google.github.io/styleguide/cppguide.html#Ownership_and_Smart_Pointers)

```cpp
// Good
std::unique_ptr<Foo> CreateFoo();
void Consume(std::unique_ptr<Foo> foo);
void Observe(const Foo& foo);  // borrow, no ownership

// Bad
std::shared_ptr<Foo> f = CreateShared();  // no strong reason / mutable shared state
Foo* CreateFooRaw();                      // ownership unclear at call site
std::auto_ptr<Foo> p;                     // removed / banned
```

---

### Rvalue References

Only for move ctor/assign, `&&`-qualified consume methods, perfect forwarding, or measured overload pairs. Prefer pass-by-value when that is simpler.

[Rvalue References](https://google.github.io/styleguide/cppguide.html#Rvalue_References)

```cpp
// Good
Foo(Foo&& other) noexcept = default;
Foo& operator=(Foo&& other) noexcept = default;
template <typename T>
void Forward(T&& x) { sink(std::forward<T>(x)); }

// Bad
void SetName(std::string&& name);  // prefer by-value or const& unless proven need
void Process(Bar&&);               // unclear post-condition; not a consume API
```

---

### Friends

Allowed when defined nearby and they preserve encapsulation better than public members.

[Friends](https://google.github.io/styleguide/cppguide.html#Friends)

```cpp
// Good
class Foo {
  friend class FooBuilder;  // same file / tight coupling for construction
 private:
  explicit Foo(State s);
  State state_;
};

// Bad
class Foo {
  friend class AlmostEverything;  // widens access with no clear boundary
  friend void RandomHelper();     // defined far away, hard to audit
};
```

---

### Exceptions

Do **not** use C++ exceptions. Prefer `absl::Status` / `StatusOr` / error codes.

[Exceptions](https://google.github.io/styleguide/cppguide.html#Exceptions)

```cpp
// Good
absl::StatusOr<int> Parse(std::string_view s);
absl::Status Write(const Path& path);

// Bad
int Parse(std::string_view s);  // throws on failure
throw std::runtime_error("fail");
try { ... } catch (...) { ... }
```

---

### `noexcept`

Use on moves and APIs that truly never throw and where it helps (e.g. containers).

[noexcept](https://google.github.io/styleguide/cppguide.html#noexcept)

```cpp
// Good
Foo(Foo&& other) noexcept;
void Swap(Foo& a, Foo& b) noexcept;

// Bad
absl::Status Load() noexcept;  // Status failures are normal — misleading
void MightFail() noexcept;     // actually allocates / can fail
```

---

### Run-Time Type Information (RTTI)

Avoid `dynamic_cast` / `typeid`. Prefer virtual methods, variants, or visitor patterns.

[RTTI](https://google.github.io/styleguide/cppguide.html#Run-Time_Type_Information__RTTI_)

```cpp
// Good
struct Shape { virtual void Draw() const = 0; };
void Render(const Shape& s) { s.Draw(); }

// Bad
void Render(const Shape& s) {
  if (auto* c = dynamic_cast<const Circle*>(&s)) { /* ... */ }
}
std::string Name(const Base& b) { return typeid(b).name(); }
```

---

### Casting

Use `static_cast`, `const_cast`, `reinterpret_cast` (rare), or braced conversions. No C-style casts.

[Casting](https://google.github.io/styleguide/cppguide.html#Casting)

```cpp
// Good
int n = static_cast<int>(size);
double d = 1.0;
auto* p = static_cast<Derived*>(base_ptr);  // when hierarchy is known

// Bad
int n = (int)size;
Derived* p = (Derived*)base_ptr;
```

---

### Streams

Fine for I/O. Do not build ad-hoc string formatting solely via `<<` when clearer APIs exist (e.g. `absl::StrCat`).

[Streams](https://google.github.io/styleguide/cppguide.html#Streams)

```cpp
// Good
std::cout << "ready\n";
std::ifstream in(path);
absl::StatusOr<std::string> body = ReadFile(path);

// Bad
std::string msg = (std::ostringstream() << "x=" << x << " y=" << y).str();
// prefer absl::StrCat / Format when composing strings
```

---

### Preincrement and Predecrement

Prefer `++i` / `--i` over post-increment when the value is unused.

[Preincrement and Predecrement](https://google.github.io/styleguide/cppguide.html#Preincrement_and_Predecrement)

```cpp
// Good
for (int i = 0; i < n; ++i) { /* ... */ }
++it;

// Bad
for (int i = 0; i < n; i++) { /* ... */ }  // post-increment unused
```

---

### Use of `const`

Mark methods and data `const` when they do not mutate observable state. Prefer `const T*` / `const T&` for read-only inputs.

[Use of const](https://google.github.io/styleguide/cppguide.html#Use_of_const)

```cpp
// Good
int size() const { return size_; }
void Print(const std::string& s);

// Bad
int size() { return size_; }          // should be const
void Print(std::string& s);           // mutates unintentionally / not needed
```

---

### `constexpr`, `constinit`, and `consteval`

Use when values/functions are truly compile-time; `constinit` for statics that must not dynamic-init.

[Use of constexpr](https://google.github.io/styleguide/cppguide.html#Use_of_constexpr)

```cpp
// Good
constexpr int kMax = 100;
constinit thread_local int tls_id = 0;
consteval int Square(int x) { return x * x; }

// Bad
constexpr std::string Make();  // if it cannot be constexpr in practice
static std::string g;          // prefer constinit / avoid dynamic init
```

---

### Integer Types

Use `int` for ordinary counts. Use `<cstdint>` (`int32_t`, `uint64_t`, …) when size/serialization/ABI matters. Avoid unconstrained unsigned unless bitmasks / modular wrap are intended.

[Integer Types](https://google.github.io/styleguide/cppguide.html#Integer_Types)

```cpp
// Good
int num_items = 0;
int64_t file_offset = 0;
uint32_t flags = 0;  // bitmask

// Bad
long x = 0;           // size varies by platform
unsigned n = Count(); // invites underflow bugs for sizes
```

---

### Floating-Point Types

Be explicit about precision; do not compare floats with `==` for computed values without care.

[Floating-Point Types](https://google.github.io/styleguide/cppguide.html#Floating-Point_Types)

```cpp
// Good
double distance = 0.0;
float sample = 0.0f;
if (std::abs(a - b) < eps) { /* ... */ }

// Bad
float money = 0.1f + 0.2f;  // financial / exact decimal needs
if (a == b) { /* computed floats */ }
```

---

### Architecture Portability

Do not assume pointer/int sizes, endianness, or unaligned access. Use fixed-width types and portable APIs.

[64-bit Portability](https://google.github.io/styleguide/cppguide.html#64-bit_Portability)

```cpp
// Good
static_assert(sizeof(void*) >= 4);
int64_t id = ParseId(s);
memcpy(&value, bytes, sizeof(value));  // or absl endian helpers

// Bad
int handle = (int)ptr;           // truncates on LP64
int word = *(int*)raw_bytes;     // alignment / endian assumptions
```

---

### Preprocessor Macros

Prefer constants, `inline`, templates, enums. Macros are rare, `ALL_CAPS`, project-prefixed, and carefully parenthesized.

[Preprocessor Macros](https://google.github.io/styleguide/cppguide.html#Preprocessor_Macros)

```cpp
// Good
inline constexpr int kMaxRetries = 3;
#define MYPROJ_DISALLOW_COPY(Type) \
  Type(const Type&) = delete;      \
  Type& operator=(const Type&) = delete

// Bad
#define max(a, b) ((a) > (b) ? (a) : (b))  // use std::max
#define square(x) x * x                    // unsafe expansion
```

---

### 0 and `nullptr` / `NULL`

Use `nullptr` for pointers. Use `'\0'` for chars. Do not use `NULL` or `0` as a pointer.

[0 and nullptr/NULL](https://google.github.io/styleguide/cppguide.html#0_and_nullptr_NULL)

```cpp
// Good
Foo* p = nullptr;
char end = '\0';

// Bad
Foo* p = NULL;
Foo* q = 0;
```

---

### `sizeof`

Prefer `sizeof(var)` / `sizeof(*ptr)` over `sizeof(Type)` when the expression’s type should track the object.

[sizeof](https://google.github.io/styleguide/cppguide.html#sizeof)

```cpp
// Good
int values[kN];
memset(values, 0, sizeof(values));
std::vector<int> v(n);
bytes = v.size() * sizeof(v[0]);

// Bad
memset(values, 0, sizeof(int) * kN);  // drifts if element type changes
```

---

### Type Deduction (`auto`)

Use `auto` when the type is obvious or painfully verbose. Do not hide important type information.

[Type deduction](https://google.github.io/styleguide/cppguide.html#Type_deduction)

```cpp
// Good
auto it = map.find(key);
auto status = Load();  // Status / StatusOr clearly named
const auto& entry = table.front();

// Bad
auto x = GetPayload();   // unclear: int? string? unique_ptr?
auto flags = 0x1;        // prefer explicit integer type
```

---

### Class Template Argument Deduction (CTAD)

Allowed when the deduced type is clear at the call site.

[CTAD](https://google.github.io/styleguide/cppguide.html#CTAD)

```cpp
// Good
std::pair p{1, 2.0};              // clear
std::lock_guard lock(mu);

// Bad
std::vector v{1, 2.0};            // ambiguous / surprising element type
auto t = std::tuple{a, b, c};     // when named struct would be clearer
```

---

### Designated Initializers

Allowed for aggregates; follow nested / ordering rules in the guide (designators in declaration order).

[Designated initializers](https://google.github.io/styleguide/cppguide.html#Designated_initializers)

```cpp
// Good
struct Options { int retries; bool verbose; };
Options o{.retries = 3, .verbose = false};

// Bad
Options o{.verbose = false, .retries = 3};  // out of declaration order
```

---

### Lambda Expressions

Prefer explicit captures. Avoid default captures (`[=]`, `[&]`) that silently capture `this` or dangling refs.

[Lambda expressions](https://google.github.io/styleguide/cppguide.html#Lambda_expressions)

```cpp
// Good
std::for_each(v.begin(), v.end(), [limit](int x) { return x < limit; });
auto cb = [this]() { return size_; };  // explicit this

// Bad
auto cb = [=]() { return size_; };     // default capture; easy to dangle
auto bad = [&]() { return tmp; };      // tmp may dangle when invoked later
```

---

### Template Metaprogramming

Use sparingly; prefer concepts, `auto`, and simpler templates. Keep error messages / readability in mind.

[Template metaprogramming](https://google.github.io/styleguide/cppguide.html#Template_metaprogramming)

```cpp
// Good
template <typename T>
concept Addable = requires(T a, T b) { a + b; };

// Bad
template <typename T>
struct DeepTrait { /* 5 layers of SFINAE for a simple check */ };
```

---

### Concepts and Constraints

Allowed. Keep constraints named and readable; prefer standard concepts when they fit.

[Concepts and Constraints](https://google.github.io/styleguide/cppguide.html#Concepts_and_Constraints)

```cpp
// Good
template <std::integral T>
T SaturateAdd(T a, T b);

template <typename T>
  requires std::contiguous_iterator<T>
void Touch(T first, T last);

// Bad
template <typename T>
  requires requires(T t) { /* huge anonymous requires */ }
void F(T);
```

---

### C++20 Modules

**Do not use** yet.

[Modules](https://google.github.io/styleguide/cppguide.html#Modules)

```cpp
// Good
#include "myproj/foo.h"

// Bad
export module myproj.foo;
import myproj.foo;
```

---

### Coroutines

Restricted. Do not introduce coroutines unless the project already has an approved pattern and you follow the guide.

[Coroutines](https://google.github.io/styleguide/cppguide.html#Coroutines)

```cpp
// Good
absl::StatusOr<Result> LoadAsyncBlocking();  // ordinary API until approved

// Bad
LazyTask<int> CoLoad() {  // new coroutine framework without project support
  co_return co_await Fetch();
}
```

---

### Disallowed / Restricted Standard Library Features

Do not use banned facilities (e.g. exceptions-based APIs that force throw, deprecated traits, etc.). Prefer Abseil equivalents when the guide points there.

[Disallowed standard library features](https://google.github.io/styleguide/cppguide.html#Disallowed_standard_library_features) (see guide list)

```cpp
// Good
absl::Mutex mu;
absl::Status st = DoWork();

// Bad
std::uncaught_exceptions();  // exception-oriented
// any std facility the current guide lists as banned for your toolchain
```

---

### Third-party Libraries

Prefer approved libraries (often Abseil). Do not pull Boost / random deps without project policy.

[Boost / third-party](https://google.github.io/styleguide/cppguide.html#Boost)

```cpp
// Good
#include "absl/strings/str_cat.h"
std::string s = absl::StrCat(a, b);

// Bad
#include <boost/lexical_cast.hpp>
auto s = boost::lexical_cast<std::string>(x);
```

---

### Nonstandard Extensions

No compiler-specific extensions unless wrapped behind portability macros.

[Nonstandard Extensions](https://google.github.io/styleguide/cppguide.html#Nonstandard_Extensions)

```cpp
// Good
#if defined(MYPROJ_OS_WINDOWS)
#define MYPROJ_EXPORT __declspec(dllexport)
#else
#define MYPROJ_EXPORT
#endif
MYPROJ_EXPORT void F();

// Bad
void F() __attribute__((always_inline));  // bare, unwrapped
__declspec(dllexport) void G();
```

---

### Aliases

Prefer `using` over `typedef`. Alias when it clarifies; do not obscure the underlying type without benefit.

[Aliases](https://google.github.io/styleguide/cppguide.html#Aliases)

```cpp
// Good
using IdMap = absl::flat_hash_map<UserId, User>;
using Clock = std::chrono::steady_clock;

// Bad
typedef absl::flat_hash_map<UserId, User> IdMap;
using X = int;  // buys nothing
```

---

### Switch Statements

Cover all enum cases or provide `default`. Annotate intentional fallthrough. Do not fall through silently.

[Switch Statements](https://google.github.io/styleguide/cppguide.html#Switch_Statements)

```cpp
// Good
switch (color) {
  case Color::kRed:
  case Color::kOrange:  // intentional fallthrough
    PaintWarm();
    break;
  case Color::kBlue:
    PaintCool();
    break;
}

// Bad
switch (color) {
  case Color::kRed:
    PaintWarm();
    // missing break — falls into kBlue
  case Color::kBlue:
    PaintCool();
    break;
}
```
