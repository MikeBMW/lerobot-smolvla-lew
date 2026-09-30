# Zone.Identifier files on Windows Git runners

## Error

```
error: invalid path 'docs/foo.zip:Zone.Identifier'
##[error]The process 'C:\Program Files\Git\bin\git.exe' failed with exit code 128
```

## Root cause

Windows NTFS creates `:Zone.Identifier` alternate data streams on files
downloaded from the internet or copied from external drives. When these
get committed to git (they show as regular files on Linux), the colon
character is illegal in Windows paths, so Windows git runners fail on
checkout.

## Detection

```bash
git ls-files | grep ':Zone.Identifier'
```

## Fix

```bash
# Remove from git index (keep files locally if needed)
git ls-files -z | tr '\0' '\n' | grep ':Zone.Identifier' | while IFS= read -r f; do
  git rm --cached "$f"
done

# Delete physical files
git ls-files -z | tr '\0' '\n' | grep ':Zone.Identifier' | while IFS= read -r f; do
  rm -f "$f"
done

# Add to .gitignore to prevent re-entry
cat >> .gitignore << 'EOF'
# Windows NTFS ADS — causes checkout failure on Windows runners
*:Zone.Identifier
EOF
```

## Prevention

Add `*:Zone.Identifier` to `.gitignore` in any repo that might be
checked out on Windows (including GitHub Actions `windows-latest`
runners).
