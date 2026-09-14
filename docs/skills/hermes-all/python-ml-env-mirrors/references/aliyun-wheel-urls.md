# Aliyun mirror wheel URLs + nvidia batch download

## Wheel URL patterns (aliyun pytorch-wheels, cu124)

Base: `https://mirrors.aliyun.com/pytorch-wheels/cu124/`

Filename pattern (URL-encoded `+` as `%2B`, `&#43;` in HTML listing):
- torch: `torch-2.6.0+cu124-cp312-cp312-linux_x86_64.whl` → URL `torch-2.6.0%2Bcu124-cp312-cp312-linux_x86_64.whl`
- torchvision: `torchvision-0.21.0+cu124-cp312-cp312-linux_x86_64.whl`
- nvidia libs: `nvidia_<name>_cu12-<ver>-py3-none-manylinux2014_x86_64.whl` (note: underscore in `nvidia_cublas_cu12`, plain `manylinux2014`, no cp tag)

Listing versions:
```bash
timeout 20 curl -sL "https://mirrors.aliyun.com/pytorch-wheels/cu124/" | grep -oE 'torch-2\.[0-9.]+&#43;cu124-cp312-cp312-linux_x86_64\.whl' | sort -uV | tail
```

## Batch download script for all nvidia wheels

```bash
#!/bin/bash
# Usage: download every nvidia_*_cu12 x86_64 wheel from aliyun cu124 listing
set -e
cd /tmp/wheels2
BASE="https://mirrors.aliyun.com/pytorch-wheels/cu124"
PKGS="nvidia_cuda_runtime_cu12 nvidia_cuda_nvrtc_cu12 nvidia_cudnn_cu12 nvidia_cufft_cu12 \
nvidia_curand_cu12 nvidia_cusolver_cu12 nvidia_cusparse_cu12 nvidia_cusparselt_cu12 \
nvidia_nccl_cu12 nvidia_nvjitlink_cu12 nvidia_nvtx_cu12 nvidia_cuda_cupti_cu12"
for pkg in $PKGS; do
  url=$(timeout 30 curl -sL "$BASE/" | grep -oE "$pkg-[0-9.]+[^\"]*x86_64\.whl" | sort -uV | tail -1)
  [ -z "$url" ] && { echo "SKIP $pkg"; continue; }
  [ -f "$url" ] || { echo ">>> $pkg"; timeout 300 curl -sL --retry 3 -o "$url" "$BASE/$url" || echo "FAIL $pkg"; }
done
echo ALL_DOWNLOADED
```

Then install all at once (add `nvidia_cublas_cu12` — the first one needed, ~347MB):
```bash
ls nvidia_*.whl | grep -v "12.9.2" | xargs ~/.venvs/act/bin/pip install --quiet --no-deps
```

## Sizes observed (2026-08, cu124)

| wheel | size |
|-------|------|
| torch 2.6.0+cu124 cp312 | ~2.4GB expected; aliyun served 768MB (verify with zipfile!) |
| nvidia_cudnn_cu12 9.1.0.70 | 664MB |
| nvidia_cublas_cu12 12.4.5.8 | 347MB |
| nvidia_cufft_cu12 | 211MB |
| nvidia_cusparse_cu12 | 207MB |
| nvidia_nccl_cu12 | 188MB |
| torchvision 0.21.0+cu124 | 7MB |

## Zip-verify before pip install

```bash
python3 -c "import zipfile; z=zipfile.ZipFile('x.whl'); print('ZIP_OK', z.testzip(), len(z.namelist()))"
```
Truncated downloads show `File is not a zip file` or `ZIP损坏` — re-download with `curl --retry 3`. A 2.3MB "cublas" file that should be 347MB is a 404 page in disguise — check the listing URL actually exists for that version.

## Import-error order (missing nvidia libs)

torch import fails in sequence as each missing lib is hit:
1. `ValueError: libcublas.so.*[0-9] not found` → install nvidia_cublas_cu12
2. `ValueError: libcudnn.so.*[0-9] not found` → install nvidia_cudnn_cu12
3. Then cufft/curand/cusolver/cusparse/nccl/nvjitlink/cusparselt as used — just install the whole set upfront.
