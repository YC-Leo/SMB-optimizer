## Summary

Describe what this pull request changes and why.

## Checklist

- [ ] Unit tests pass locally (`python -m pytest -q -m "not slow"`)
- [ ] Case 1 and Case 2 still match the references (`python -m pytest -q -m slow`), or the new reference values are explained below
- [ ] Code is formatted (`black --check .`) and the content check passes (`python tools/check_repo.py`)
- [ ] `smbsim/` still matches SMB-simulator, or the change was made there first
- [ ] Component names stay generic and example scenarios are named Case 1, Case 2, …
- [ ] Documentation and `CHANGELOG.md` are updated if user-facing behavior changed

## Effect on results

If the optimum of any example changes, give the old and new values here.
