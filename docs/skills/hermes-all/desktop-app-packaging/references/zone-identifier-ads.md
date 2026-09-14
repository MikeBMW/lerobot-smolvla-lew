# Zone.Identifier — Windows NTFS ADS in Git

## What it is

Windows appends `:Zone.Identifier` alternate data streams (ADS) to files downloaded from the internet. When committed to git (e.g. via `git add` from a WSL mount of an NTFS drive), they show up as files like:

```
docs/他山Ⅰ期验收交付件.zip:Zone.Identifier
```

## Why it breaks

- Windows git checkout rejects paths containing `:` (invalid NTFS character)
- GitHub Actions `windows-latest` runners fail at the Checkout step with:

  ```
  error: invalid path 'docs/他山Ⅰ期验收交付件.zip:Zone.Identifier'
  ```

## Detection

```bash
# List all Zone.Identifier files tracked in git
git ls-files | grep ':Zone.Identifier'

# Check if they exist on the worktree (Linux/WSL)
find . -name '*Zone.Identifier*' -o -name '*:Zone*' 2>/dev/null
```

## Fix

```bash
# Remove from git index (keeps physical file if any)
git rm --cached "./path/to/file:Zone.Identifier"

# Delete physical files
rm -f "./path/to/file:Zone.Identifier"

# Prevent recurrence in .gitignore:
# (existing 'Zone.Identifier' pattern won't match ':Zone.Identifier' filenames)
echo '*:Zone.Identifier' >> .gitignore

# Commit
git add .gitignore && git commit -m "fix: remove Zone.Identifier ADS files"
git tag -f vX.Y.Z && git push origin main --tags --force
```

## Prevention

Add to `.gitignore`:
```
# Windows NTFS ADS — causes checkout failure on Windows runners
*:Zone.Identifier
```
