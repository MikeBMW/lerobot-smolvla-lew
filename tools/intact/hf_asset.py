# -*- coding: utf-8 -*-
"""HF 资产元数据/校验小工具 (供 intact 自主流水线调用)

用法:
  python3 hf_asset.py meta  <dataset-repo> <filename>          # → "size sha256"
  python3 hf_asset.py verify <file> <sha256>                   # → OK / MISMATCH
  python3 hf_asset.py url   <dataset-repo> <filename>          # → 镜像下载 URL
"""
import hashlib
import json
import os
import sys
import urllib.request

ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")


class _Redirect308(urllib.request.HTTPRedirectHandler):
    """★ hf-mirror 回 308 Permanent Redirect, 而 Python 3.10 的 urllib 完全没有 308 支持:
    既没有 http_error_308 handler (落到 http_error_default 直接抛), redirect_request 的
    白名单也只有 301/302/303/307 → 必须**两处都补**。表现为"取不到元数据"或"下载卡 0 字节"。
    (Python 3.11+ 原生支持 308)"""

    def http_error_308(self, req, fp, code, msg, headers):      # noqa: N802
        return self.http_error_302(req, fp, code, msg, headers)

    def redirect_request(self, req, fp, code, msg, headers, newurl):   # noqa: N802
        if code == 308:
            code = 307          # 308 与 307 语义相同(重定向且不改变请求方法)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


opener = urllib.request.build_opener(_Redirect308)


def _tree(repo: str):
    url = f"{ENDPOINT}/api/datasets/{repo}/tree/main?expand=true"
    with opener.open(url, timeout=60) as r:
        return json.loads(r.read().decode())


def meta(repo: str, filename: str) -> int:
    for it in _tree(repo):
        if it.get("path") == filename:
            lfs = it.get("lfs") or {}
            # ★ HF 的 /tree 接口通常不给 lfs.sha256, 但 lfs.oid 就是文件内容的 sha256
            sha = lfs.get("sha256") or lfs.get("oid") or ""
            if not sha:
                print(f"NO_HASH {repo}/{filename}", file=sys.stderr)
                return 4
            print(f"{it.get('size')} {sha}")
            return 0
    print(f"NOT_FOUND {repo}/{filename}", file=sys.stderr)
    return 2


def verify(path: str, sha: str) -> int:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    got = h.hexdigest()
    print("OK" if got == sha else f"MISMATCH {got}")
    return 0 if got == sha else 3


def url(repo: str, filename: str) -> int:
    print(f"{ENDPOINT}/datasets/{repo}/resolve/main/{filename}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "meta":
        sys.exit(meta(sys.argv[2], sys.argv[3]))
    if cmd == "verify":
        sys.exit(verify(sys.argv[2], sys.argv[3]))
    if cmd == "url":
        sys.exit(url(sys.argv[2], sys.argv[3]))
    print(__doc__)
    sys.exit(1)
