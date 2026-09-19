from pathlib import Path
import json
import numpy as np
import soundfile as sf

SRC=Path("output/serenoa_safe_retry/0070_no_reference_candidate.wav")
TGT=Path("output/serenoa_safe_retry/0090_verified_boundary_candidate.wav")
OUTDIR=Path("output/serenoa_audio_repair_poc")
OUTDIR.mkdir(parents=True, exist_ok=True)

src,sr=sf.read(SRC,dtype="float64")
tgt,sr2=sf.read(TGT,dtype="float64")
assert sr==sr2==24000 and src.ndim==tgt.ndim==1

src_text="เมื่อตระกูลวูล์ฟฟอร์ต ซึ่งมีอำนาจสูงสุดเหนือตระกูลอื่นใดในเกลนบรู๊ค รับรู้ถึงการโจมตี พวกเขาจึงเร่งรุดเข้าช่วยเหล่าเชื้อพระวงศ์ นำทัพโดยเซเรโนอา ผู้สืบทอดตำแหน่งลอร์ดมาจากพ่อของเขา"
tgt_text="สงครามใหม่กำลังระอุขึ้น โดยมีเชื้อไฟเป็นหลักความเชื่ออันแน่วแน่ของดินแดนทั้งหลาย แต่เซเรโนอา กับทัพของเขา มุ่งตรงเข้าสู่ไฟสงคราม โดยที่พวกเขายังไม่ค่อยเข้าใจสถานการณ์เท่าใดนัก..."
word="เซเรโนอา"

def nearest_low_energy(y, expected, radius=.45, win=.025):
    w=max(1,int(win*sr)); lo=max(0,int((expected-radius)*sr)); hi=min(len(y)-w,int((expected+radius)*sr))
    best=None
    for i in range(lo,hi,max(1,w//4)):
        rms=float(np.sqrt(np.mean(y[i:i+w]**2)))
        if best is None or rms<best[0]: best=(rms,i)
    return best[1]/sr,best[0]

def estimate_range(y,text):
    dur=len(y)/sr
    st=text.index(word)/len(text)*dur
    en=(text.index(word)+len(word))/len(text)*dur
    # seek low energy only close to estimated word edges
    a,_=nearest_low_energy(y,st,.32)
    b,_=nearest_low_energy(y,en,.32)
    if b-a < .35 or b-a > 1.5:
        a,b=st,en
    return a,b,(st,en)

sa,sb,sest=estimate_range(src,src_text)
ta,tb,test=estimate_range(tgt,tgt_text)

# Keep donor word natural; local RMS match donor to target region.
donor=src[int(sa*sr):int(sb*sr)].copy()
target_region=tgt[int(ta*sr):int(tb*sr)]
def rms(x): return float(np.sqrt(np.mean(x*x))) if len(x) else 0.0
gain=np.clip(rms(target_region)/max(rms(donor),1e-9),0.75,1.33)
donor*=gain

# If donor length differs, preserve donor pronunciation and allow local duration change.
left=tgt[:int(ta*sr)].copy()
right=tgt[int(tb*sr):].copy()
fade=min(int(.025*sr),len(donor)//4,len(left),len(right))
if fade:
    x=np.linspace(0,1,fade,endpoint=False)
    # equal-power crossfades
    fi=np.sin(x*np.pi/2); fo=np.cos(x*np.pi/2)
    donor[:fade]=left[-fade:]*fo+donor[:fade]*fi
    left=left[:-fade]
    donor[-fade:]=donor[-fade:]*fo+right[:fade]*fi
    right=right[fade:]
out=np.concatenate([left,donor,right])
peak=float(np.max(np.abs(out)))
if peak>10**(-1/20): out*=10**(-1/20)/peak

outp=OUTDIR/"0090_serenoa_audio_repair_poc.wav"
sf.write(outp,out,sr,subtype="PCM_16")

# Listening snippets make manual verification of alignment possible without touching originals.
pad=.8
sf.write(OUTDIR/"source_0070_serenoa_context.wav",src[max(0,int((sa-pad)*sr)):min(len(src),int((sb+pad)*sr))],sr,subtype="PCM_16")
sf.write(OUTDIR/"target_0090_serenoa_context.wav",tgt[max(0,int((ta-pad)*sr)):min(len(tgt),int((tb+pad)*sr))],sr,subtype="PCM_16")

stats={
 "source_word_range_s":[round(sa,4),round(sb,4)],"source_proportional_estimate_s":[round(x,4) for x in sest],
 "target_word_range_s":[round(ta,4),round(tb,4)],"target_proportional_estimate_s":[round(x,4) for x in test],
 "donor_gain":round(float(gain),6),"crossfade_ms":25,
 "source_word_duration_s":round(sb-sa,4),"target_word_duration_s":round(tb-ta,4),
 "output_duration_s":round(len(out)/sr,4),"peak":round(float(np.max(np.abs(out))),6),
 "method":"proportional text-time estimate refined to nearby low-energy boundaries; 25 ms equal-power crossfade; local RMS gain match",
 "warning":"word boundaries are heuristic because no forced aligner/ASR is installed; human listening is mandatory"
}
(OUTDIR/"report.json").write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(stats,ensure_ascii=False,indent=2))
