# GitHub Actions Workflows for PyQt5 Desktop App Distribution

This directory contains reference workflow files for automating
Docker image builds and Windows .exe packaging via CI.

## Files

| File | Purpose |
|------|---------|
| `docker-acr.yml` | Build & push Docker image to Alibaba Cloud ACR on tag |
| `build-win-exe.yml` | Build Windows .exe via PyInstaller on Windows runner |

## Usage

1. Copy the desired `.yml` files to `.github/workflows/` in your repo
2. For ACR: add `ACR_USERNAME` and `ACR_PASSWORD` to GitHub Secrets
3. Push a `v*` tag to trigger, or use workflow_dispatch for manual builds

## Secrets Required

| Workflow | Secret | Description |
|----------|--------|-------------|
| docker-acr.yml | `ACR_USERNAME` | Alibaba Cloud ACR login username |
| docker-acr.yml | `ACR_PASSWORD` | Alibaba Cloud ACR login password |
| build-win-exe.yml | (none) | Uses `GITHUB_TOKEN` — needs `permissions: { contents: write }` |

## build-win-exe.yml — Key invariants

| Requirement | Detail |
|-------------|--------|
| `runs-on` | `windows-latest` |
| `permissions` | `contents: write, actions: read` (for release upload) |
| pip install | `pyinstaller PyQt5 numpy pillow grpcio protobuf` |
| PyInstaller | `--onefile --windowed` |
| Release tag | Use `steps.release_tag.outputs.tag` (handles both tag push and workflow_dispatch) |
| Zone.Identifier | Repo must NOT have `:Zone.Identifier` files — they break Windows checkout |

## docker-acr.yml — Key invariants

| Requirement | Detail |
|-------------|--------|
| Login action | `docker/login-action@v3` with `registry: ${{env.REGISTRY}}` |
| Secrets | `ACR_USERNAME`, `ACR_PASSWORD` |
| Registry | `registry.cn-hangzhou.aliyuncs.com` |
| Buildx | Required for multi-platform |

## Common CI failures & fixes

| Symptom | Root cause | Fix |
|---------|-----------|-----|
| Checkout fails: `invalid path ':Zone.Identifier'` | Windows ADS files in repo | `git rm --cached` + `*:Zone.Identifier` in `.gitignore` |
| Release upload: "Resource not accessible" | Missing `permissions: contents: write` | Add permissions block to job |
| Release upload: skipped on workflow_dispatch | `if: startsWith(github.ref, 'refs/tags/v')` doesn't match branches | Add `|| github.event_name == 'workflow_dispatch'` |
| workflow_dispatch uses wrong tag | `github.ref_name` is branch name, not tag input | Use dedicated `Determine release tag` step |
| .exe crashes: `ModuleNotFoundError: grpc` | Missing grpcio in pip install | Add `grpcio protobuf` to deps |
| .exe crashes: `ModuleNotFoundError: torch` | torch not bundled | Wrap in try/except with `_TORCH_AVAILABLE` flag |
