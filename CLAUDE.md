# Working in this repo

## Tests

- Every enhancement or bug fix should come with unit tests, as long as it makes sense to test it. A pure visual tweak, for example, may not need one.
  - For a bug fix, add a test that fails without the fix.
  - For an enhancement, test the new behaviour, including its edge cases.
  - If you skip tests for a change, say so and explain why.
- Run the game's existing tests before calling the work done, and report the results.
- Some games already have a suite (for example `tidewater/` and `PokerNight/`): `tests.html` holds the tests and `python run_tests.py` runs them headless. Add new tests to that game's `tests.html`, following the style already there.
