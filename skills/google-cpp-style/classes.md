# Classes

Full guide: [Classes](https://google.github.io/styleguide/cppguide.html#Classes)

## Rules

- Prefer **factory** / two-phase init over heavy work or failure in constructors when construction can fail (no exceptions).
- Use `explicit` on single-argument constructors and conversion operators; avoid implicit conversions.
- Be intentional about copy/move: `=default`, `=delete`, or define correctly. Prefer value semantics; use `std::unique_ptr` members when needed.
- `struct` = passive data; `class` = invariants / methods. Prefer `struct` over `std::pair`/`std::tuple` when fields need names.
- Public inheritance for “is-a”; composition preferred. Multiple implementation inheritance only when careful; interface inheritance via abstract bases is fine.
- Overload operators sparingly and only when meaning is obvious (`==`, `<<` for streams in limited cases, etc.).
- Make data members `private` (or `protected` only when needed). Use `public` / `protected` / `private` sections in that order.
- Declaration order: types → constants → factories → constructors/destructor → methods → data members.

## Examples

```cpp
// Good
class Foo {
 public:
  static absl::StatusOr<Foo> Create(int n);

  Foo(const Foo&) = delete;
  Foo& operator=(const Foo&) = delete;
  Foo(Foo&&) noexcept = default;
  Foo& operator=(Foo&&) noexcept = default;

  explicit Foo(std::string name);
  int size() const { return size_; }

 private:
  Foo(int size, std::string name);

  int size_;
  std::string name_;
};

struct Point {
  double x;
  double y;
};
```

```cpp
// Bad
class Foo {
 public:
  Foo(std::string name);     // missing explicit
  int size_;                 // public data with invariant methods
  Foo();                     // constructor does I/O / can fail silently
};
```
