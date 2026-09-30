import h5py, numpy as np, os
SRC="/home/ubuntu/stable-wm-cache/datasets/l5_gen_v3.h5"
f=h5py.File(SRC,"r"); N=int(f["observation"].shape[0])
cut=int(N*2/3)
keys=[k for k in f if f[k].ndim>=2 and f[k].shape[0]==N]
for name,lo,hi in (("l5_train",0,cut),("l5_holdout",cut,N)):
    out=f"/home/ubuntu/stable-wm-cache/datasets/{name}.h5"
    g=h5py.File(out,"w"); n=hi-lo
    for k in keys:
        d=f[k]; s=(n,)+d.shape[1:]
        kw=dict(compression="lzf") if d.nbytes>1e7 else {}
        g.create_dataset(k,shape=s,dtype=d.dtype,chunks=(min(256,n),)+d.shape[1:],**kw)
        for a in range(lo,hi,4096):
            b=min(hi,a+4096); g[k][a-lo:b-lo]=d[a:b]
    g.close()
    print(name,n,"帧",round(os.path.getsize(out)/1048576),"MB",flush=True)
f.close()
