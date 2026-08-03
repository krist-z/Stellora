# Comments

Full guide: [Comments](https://google.github.io/styleguide/cppguide.html#Comments)

## Rules

- Use `//` comments in most cases; `/* */` OK for temporarily disabling code or specific cases.
- File comments: license / copyright as required by the project; brief description when non-obvious.
- Every non-obvious class, function, and enum gets comments stating purpose, not how.
- Function comments on the **declaration** (header): inputs, outputs, ownership, errors. Do not restate the function name.
- Document tricky data members and non-obvious invariants.
- Prefer clear code over narrating obvious lines. Comment *why*, not *what*.
- TODO format: `TODO(username):` or bug link + actionable note.
- Proper punctuation, spelling, grammar in comments.

## Examples

```cpp
// Good
// Loads the user from durable storage.
// Returns NotFound if `id` does not exist.
absl::StatusOr<User> LoadUser(UserId id);

// TODO(jdoe): merge with Cache::Lookup once the API is stable.

// Bad
// This function loads the user.   // restates the name
absl::StatusOr<User> LoadUser(UserId id) {
  // increment i by 1
  ++i;
}
```
