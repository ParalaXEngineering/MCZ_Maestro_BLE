import capstone, struct, re, sys, os
# Firmware image lives in ../firmware relative to this script (see panel/README.md).
_IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "firmware", "used_flash_0x0.bin")
d = open(_IMG, "rb").read()
# segments: (vaddr, len, fileoff)
SEGS = [(0x3f400020,0x1992a4,0x10020),   # DROM rodata/strings
        (0x400d0020,0x11202c,0x1b0020),  # IROM code
        (0x40080000,0x1fad8,0x2c3f4c)]   # IRAM code
def v2f(v):
    for lv,ln,fo in SEGS:
        if lv<=v<lv+ln: return fo+(v-lv)
    return None
def f2v(fo):
    for lv,ln,fo0 in SEGS:
        if fo0<=fo<fo0+ln: return lv+(fo-fo0)
    return None
def rdstr(v):
    fo=v2f(v)
    if fo is None: return None
    try:
        e=d.index(b'\x00',fo)
        s=d[fo:e]
        if 1<=len(s)<=60 and all(32<=c<127 for c in s): return s.decode()
    except: pass
    return None
def word(v):
    fo=v2f(v); return struct.unpack('<I',d[fo:fo+4])[0] if fo is not None else None
CODE = [(0x400d0020,0x11202c,0x1b0020),(0x40080000,0x1fad8,0x2c3f4c)]
def find_l32r_xrefs(target):
    hits=[]
    for lv,ln,fo in CODE:
        A=lv
        while A<lv+ln-2:
            b0=d[fo+(A-lv)]
            if (b0&0x0f)==0x01:
                imm=d[fo+(A-lv)+1]|(d[fo+(A-lv)+2]<<8)
                lit=((A+3)&~3)+(imm-0x10000)*4
                lw=word(lit)
                if lw==target: hits.append(A)
            A+=1
    return hits
md=capstone.Cs(capstone.CS_ARCH_XTENSA, capstone.CS_MODE_LITTLE_ENDIAN)
def ann_l32r(ins):
    if 'l32r' not in ins.mnemonic: return ''
    m=re.search(r'0x[0-9a-f]+',ins.op_str)
    if not m: return ''
    lit=int(m.group(0),16); val=word(lit)
    if val is None: return ''
    s=rdstr(val)
    if s is not None: return '  ; ->%r'%s
    return '  ; =0x%08x'%val
def disasm(start,end,align_hint=None):
    fo=v2f(start); code=d[fo:v2f(end)]
    out=[]
    for ins in md.disasm(code,start):
        out.append('0x%08x  %-10s %s%s'%(ins.address,ins.mnemonic,ins.op_str,ann_l32r(ins)))
    return out
def find_aligned(target_addr, back, fwd):
    # try alignments so that target_addr lands on an instruction boundary
    fo=v2f(target_addr)
    for delta in range(0,16):
        base=target_addr-back-delta
        code=d[v2f(base):v2f(target_addr+fwd)]
        addrs={i.address for i in md.disasm(code,base)}
        if target_addr in addrs:
            return base
    return target_addr-back

cmd=sys.argv[1]
if cmd=='xref':
    tv=int(sys.argv[2],16)
    print('xrefs to 0x%08x:'%tv, [hex(x) for x in find_l32r_xrefs(tv)])
elif cmd=='dis':
    start=int(sys.argv[2],16); end=int(sys.argv[3],16)
    print('\n'.join(disasm(start,end)))
elif cmd=='disaround':
    ta=int(sys.argv[2],16); back=int(sys.argv[3],16) if len(sys.argv)>3 else 0x40; fwd=int(sys.argv[4],16) if len(sys.argv)>4 else 0x40
    base=find_aligned(ta,back,fwd)
    print('(aligned base 0x%08x)'%base)
    print('\n'.join(disasm(base,ta+fwd)))
