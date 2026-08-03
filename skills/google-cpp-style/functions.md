# Functions

Full guide: [Functions](https://google.github.io/styleguide/cppguide.html#Functions) · [cpplint](https://github.com/cpplint/cpplint)

## Rules

- Prefer return values / `absl::StatusOr<T>` over output parameters. Inputs before outputs when outputs are required. Prefer `const T&` or values over pointers for inputs.
- Keep functions short and focused.
- Overload only when behavior is equivalent and naming would not be clearer.
- Default arguments: OK in unconstrained cases; avoid defaults that change overload resolution surprising ways; often prefer overloads at different declarations carefully.
- Prefer trailing return types only when needed (e.g. decltype of parameters, readability for complex returns).
- Run **cpplint** when the project uses it; treat its Google-style warnings seriously.

## Examples

```cpp
// Good
absl::StatusOr<User> LoadUser(UserId id);
void Append(const std::string& in, std::string* out);  // output last, pointer

// Bad
void LoadUser(UserId id, User* out);  // prefer StatusOr return when feasible
void F(int* optional_in_out);         // unclear ownership / optional semantics
```

```cpp
// Good: short, clear overloads
std::string Join(std::string_view a, std::string_view b);
std::string Join(absl::Span<const std::string_view> parts);

// Bad: overload differs only by subtle default / unrelated meaning
void Draw(int x, int y, bool fill = false);
void Draw(Color c);  // unrelated — rename instead
```
