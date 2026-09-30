# -*- coding: utf-8 -*-
r"""只读解析 Windows 内核崩溃转储: 取 BugCheck 参数 + 出错地址落在哪个驱动模块里。
用法: python minidump_parse.py C:\Windows\Minidump\xxxx.dmp
只用标准库, 不改动任何文件。
"""
import struct, sys, io

def u32(b, o): return struct.unpack_from("<I", b, o)[0]
def u64(b, o): return struct.unpack_from("<Q", b, o)[0]

def build_parser():
    return None

def main(path):
    with open(path, "rb") as f:
        b = f.read()
    if b[:4] != b"MDMP":
        print("不是 minidump:", b[:8]); return
    n_streams = u32(b, 8)
    dir_rva = u32(b, 12)
    print("== 文件:", path, "大小 %.1f MB" % (len(b) / 1048576.0))
    print("== 流数量:", n_streams)

    streams = {}
    for i in range(n_streams):
        o = dir_rva + i * 12
        st, sz, rva = u32(b, o), u32(b, o + 4), u32(b, o + 8)
        streams[st] = (sz, rva)

    # 异常流(6): 取蓝屏码/参数/出错地址
    fault_mod = None
    if 6 in streams:
        sz, rva = streams[6]
        # MINIDUMP_EXCEPTION_STREAM: ThreadId u32, align u32, ExceptionRecord...
        er = rva + 8
        code = u32(b, er)
        flags = u32(b, er + 4)
        rec = u64(b, er + 8)
        addr = u64(b, er + 16)
        nparam = u32(b, er + 24)
        params = [u64(b, er + 32 + 8 * k) for k in range(min(nparam, 15))]
        print("== ExceptionCode: 0x%08X  Flags: 0x%08X" % (code, flags))
        print("== ExceptionAddress: 0x%016X" % addr)
        print("== Parameters:", " ".join("0x%016X" % p for p in params))
        if code == 0x139:
            print("== 解读: 0x139 = KERNEL_SECURITY_CHECK_FAILURE(内核安全检查失败)")
            if params and params[0] == 3:
                print("   参数1=3 ⇒ LIST_ENTRY 链表被破坏 —— 典型是**驱动/内核态**内存被写坏(不是用户态程序能造成的)")
    guard = (code, addr)

    # 模块流(7): 名字表
    mods = []
    if 7 in streams:
        sz, rva = streams[7]
        n = u32(b, rva)
        for i in range(n):
            o = rva + 4 + i * 108
            base = u64(b, o)
            size = u32(b, o + 8)
            ts = u32(b, o + 16)
            name_rva = u32(b, o + 20)
            ln = u32(b, name_rva)
            raw = b[name_rva + 4: name_rva + 4 + ln]
            name = raw.decode("utf-16-le", "ignore")
            mods.append((base, size, ts, name))
    print("== 已加载模块数:", len(mods))

    if 6 in streams:
        addr = guard[1]
        for base, size, ts, name in mods:
            if base <= addr < base + size:
                fault_mod = name
                print("== 出错地址落在模块: %s  (base=0x%X size=0x%X stamp=0x%08X)" % (name, base, size, ts))
        if fault_mod is None:
            print("== 出错地址不落在任何已加载模块内(可能是已卸载的驱动/池内存)")

    # 关键字驱动的模块时间戳, 便于怀疑第三方驱动
    import time as _t
    def ts2s(ts):
        try: return _t.strftime("%Y-%m-%d", _t.gmtime(ts))
        except Exception: return "?"
    print("== 非微软风格的内核模块(.sys/.dll, 按名字筛选常见第三方/相机/USB):")
    keys = ("scicam", "sci", "mv", "hik", "dahua", "usb", "uvc", "cyusb", "libusb",
            "opt", "camera", "cam", "yc", "basler", "daheng", "galaxy", "ptp", "wdf", "kbd", "net")
    shown = 0
    for base, size, ts, name in mods:
        low = name.lower()
        if low.endswith(".sys") and any(k in low for k in keys):
            print("   %-40s base=0x%016X size=0x%-8X %s" % (name, base, size, ts2s(ts)))
            shown += 1
    if shown == 0:
        print("   (没有按关键字命中的 .sys)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python minidump_parse.py " + r"<dmp路径>"); raise SystemExit(2)
    main(sys.argv[1])
