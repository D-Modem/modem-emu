"""Minimal TMS32010 emulator for the Telebit T2500 DSP programs (best effort).

Not yet checked against a known output.
"""
import struct
def s16(x):
    """Return the 16-bit value as a signed integer."""
    x&=0xFFFF; return x-0x10000 if x&0x8000 else x
def s32(x):
    """Return the 32-bit value as a signed integer."""
    x&=0xFFFFFFFF; return x-0x100000000 if x&0x80000000 else x
class C10:
    """One TMS32010 core with the shared-RAM ports and the sample DMA of the T2500."""
    def __init__(s,pm,shared=None):
        """Make a core with the program words, and an optional shared RAM of the T2500 board."""
        s.pm=list(pm)+[0]*(4096-len(pm)); s.dm=[0]*256; s.acc=0; s.p=0; s.t=0
        s.ar=[0,0]; s.arp=0; s.dp=0; s.stack=[]; s.pc=0; s.ovm=0; s.intm=1; s.ov=0
        s.sh=shared if shared is not None else [0]*0x4000
        s.addr=0; s.pa7=0; s.dma={4:0,5:0,0:0,1:0}; s.hooks={}; s.ticks=0; s.cyc=0
        s.tick_cb=None; s.dmawrite=[]
    # ---- ports
    def port_in(s,p):
        """Read an I/O port: the shared-RAM address and data ports, the DMA ports and port 7."""
        dmam=s.pa7&0x8000
        if p==7:
            v=s.pa7|0x08  # block flag always ready
            if s.tick_cb: s.tick_cb(s)
            return v
        if dmam and p in (4,5,0,1): return s.dma[p]
        if p==5: return s.addr
        if p==2: return s.sh[s.addr&0x3FFF]
        if p==0: v=s.sh[s.addr&0x3FFF]; s.addr=(s.addr+1)&0xFFFF; return v
        if p==1: v=s.sh[s.addr&0x3FFF]; s.addr=(s.addr-1)&0xFFFF; return v
        return 0
    def port_out(s,p,v):
        """Write an I/O port: the shared-RAM address and data ports, the DMA ports and port 7."""
        dmam=s.pa7&0x8000
        if p==7: s.pa7=v; return
        if dmam and p in (4,5,0,1):
            s.dma[p]=v; s.dmawrite.append((p,v)); return
        if p==5: s.addr=v; return
        if p==2: s.sh[s.addr&0x3FFF]=v; return
        if p==0: s.addr=(s.addr+1)&0xFFFF; s.sh[s.addr&0x3FFF]=v; return
        if p==1: s.sh[s.addr&0x3FFF]=v; s.addr=(s.addr-1)&0xFFFF; return
    # ---- addressing
    def ea(s,w):
        """Return the effective data address for the instruction word, and apply the AR changes."""
        if w&0x80:
            a=s.ar[s.arp]&0xFF
            if w&0x20: s.ar[s.arp]=(s.ar[s.arp]+1)&0xFFFF
            if w&0x10: s.ar[s.arp]=(s.ar[s.arp]-1)&0xFFFF
            if not w&0x08: s.arp=w&1
            return a
        return (s.dp<<7)|(w&0x7F)
    def rd(s,a):
        """Read one data word."""
        return s.dm[a&0xFF]
    def wr(s,a,v):
        """Write one data word."""
        s.dm[a&0xFF]=v&0xFFFF
    def setacc(s,v):
        """Set the accumulator to a signed 32-bit value."""
        s.acc=s32(v)
    def step(s):
        """Execute one instruction."""
        pc=s.pc; w=s.pm[pc]; h=w>>8; s.pc=(pc+1)&0xFFF; s.cyc+=1
        if h>=0xF4:
            tgt=s.pm[(pc+1)&0xFFF]&0xFFF; s.pc=(pc+2)&0xFFF
            c={0xF4:None,0xF5:s.ov,0xF6:0,0xF8:True,0xF9:True,0xFA:s.acc<0,0xFB:s.acc<=0,0xFC:s.acc>0,0xFD:s.acc>=0,0xFE:s.acc!=0,0xFF:s.acc==0}[h]
            if h==0xF4:
                c=(s.ar[s.arp]&0x1FF)!=0; s.ar[s.arp]=(s.ar[s.arp]-1)&0xFFFF
            if h==0xF5: s.ov=0
            if h==0xF8: s.stack.append(s.pc); s.stack=s.stack[-4:]
            if c: s.pc=tgt
            return
        if w in (0x7F80,0x7F81,0x7F82,0x7F88,0x7F89,0x7F8A,0x7F8B,0x7F8C,0x7F8D,0x7F8E,0x7F8F,0x7F90,0x7F9C,0x7F9D):
            if w==0x7F81: s.intm=1
            elif w==0x7F82: s.intm=0
            elif w==0x7F88: s.setacc(abs(s.acc))
            elif w==0x7F89: s.acc=0
            elif w==0x7F8A: s.ovm=0
            elif w==0x7F8B: s.ovm=1
            elif w==0x7F8C: s.stack.append(s.pc); s.stack=s.stack[-4:]; s.pc=s.acc&0xFFF
            elif w==0x7F8D: s.pc=s.stack.pop() if s.stack else 0
            elif w==0x7F8E: s.acc=s.p
            elif w==0x7F8F: s.setacc(s.acc+s.p)
            elif w==0x7F90: s.setacc(s.acc-s.p)
            elif w==0x7F9C: s.stack.append(s.acc&0xFFF); s.stack=s.stack[-4:]
            elif w==0x7F9D: s.acc=s.stack.pop() if s.stack else 0
            return
        if h<0x30:
            op=h>>4; sh=h&15; a=s.ea(w); v=s16(s.rd(a))<<sh
            if op==0: s.setacc(s.acc+v)
            elif op==1: s.setacc(s.acc-v)
            else: s.setacc(v)
            return
        if h in (0x30,0x31): a=s.ea(w); s.wr(a,s.ar[h&1]); return
        if h in (0x38,0x39): a=s.ea(w); s.ar[h&1]=s.rd(a); return
        if 0x40<=h<0x48: a=s.ea(w); s.wr(a,s.port_in(h&7)); return
        if 0x48<=h<0x50: a=s.ea(w); s.port_out(h&7,s.rd(a)); return
        if h==0x50: a=s.ea(w); s.wr(a,s.acc); return
        if 0x58<=h<0x60: a=s.ea(w); s.wr(a,(s.acc<<(h&7))>>16); return
        if h==0x6E: s.dp=w&1; return
        if h in (0x70,0x71): s.ar[h&1]=w&0xFF; return
        if h==0x7E: s.acc=w&0xFF; return
        if 0x80<=h<0xA0:
            k=w&0x1FFF; k=k-0x2000 if k&0x1000 else k; s.p=s32(s16(s.t)*k); return
        a=s.ea(w); m=s.rd(a)
        if h==0x60: s.setacc(s.acc+(s16(m)<<16))
        elif h==0x61: s.setacc(s.acc+m)
        elif h==0x62: s.setacc(s.acc-(s16(m)<<16))
        elif h==0x63: s.setacc(s.acc-m)
        elif h==0x64:
            d=s.acc-(m<<15)
            s.acc=s32((d<<1)+1) if d>=0 else s32(s.acc<<1)
        elif h==0x65: s.acc=s32(m<<16)
        elif h==0x66: s.acc=m
        elif h==0x67: s.wr(a,s.pm[s.acc&0xFFF])
        elif h==0x68: pass
        elif h==0x69: s.wr(a+1,m)
        elif h==0x6A: s.t=m
        elif h==0x6B: s.t=m; s.wr(a+1,m); s.setacc(s.acc+s.p)
        elif h==0x6C: s.t=m; s.setacc(s.acc+s.p)
        elif h==0x6D: s.p=s32(s16(s.t)*s16(m))
        elif h==0x6F: s.dp=m&1
        elif h==0x78: s.acc=(s.acc&~0xFFFF)|((s.acc^m)&0xFFFF); s.acc=s32(s.acc)
        elif h==0x79: s.acc=(s.acc&m)&0xFFFF
        elif h==0x7A: s.acc=s32((s.acc&~0xFFFF)|((s.acc|m)&0xFFFF))
        elif h==0x7B: s.ov=m>>15&1; s.ovm=m>>14&1; s.intm=m>>13&1; s.arp=m>>8&1; s.dp=m&1
        elif h==0x7C: s.wr(a,(s.ov<<15)|(s.ovm<<14)|(s.intm<<13)|0x1EFE|(s.arp<<8)|s.dp)
        elif h==0x7D: s.pm[s.acc&0xFFF]=m
        else: raise Exception('bad op %04X at %03X'%(w,pc))
def load(path):
    """Read a binary file as big-endian 16-bit program words."""
    d=open(path,'rb').read(); return list(struct.unpack('>%dH'%(len(d)//2),d))
