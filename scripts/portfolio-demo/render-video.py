"""Edit one verified real recording into captioned portfolio films with FFmpeg.

No synthetic API/LLM footage. Source ranges, holds and speed changes are logged.
Video masters are local ignored artifacts; captions and edit decisions are small.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import subprocess
import textwrap

from fontTools.ttLib import TTFont
from prepare import ROOT, LOCAL, OUT

DEST = ROOT/'output/portfolio-demo'
PARTS = DEST/'parts'


def run(args, log):
    with log.open('w', encoding='utf-8') as file:
        subprocess.run(args, cwd=ROOT, stdout=file, stderr=subprocess.STDOUT, check=True)


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],text=True))


def stamp(seconds, ass=False):
    total=round(seconds*(100 if ass else 1000))
    scale=100 if ass else 1000
    h,total=divmod(total,3600*scale);m,total=divmod(total,60*scale);s,f=divmod(total,scale)
    return f'{h}:{m:02}:{s:02}.{f:02}' if ass else f'{h:02}:{m:02}:{s:02},{f:03}'


def captions(name, timeline, narration):
    cues=[]
    for scene in timeline:
        sentences=re.split(r'(?<=[.!?])\s+',narration[scene['id']])
        chunks=[];current=''
        for sentence in sentences:
            if current and len(current+' '+sentence)>86:
                chunks.append(current);current=''
            current=(current+' '+sentence).strip()
        if current:chunks.append(current)
        wrapped=[]
        for chunk in chunks:
            lines=textwrap.wrap(chunk,width=46,break_long_words=False,break_on_hyphens=False)
            wrapped.extend('\n'.join(lines[i:i+2]) for i in range(0,len(lines),2))
        total=sum(len(c) for c in wrapped);cursor=scene['start']
        for i,chunk in enumerate(wrapped):
            end=scene['end'] if i==len(wrapped)-1 else cursor+(scene['end']-scene['start'])*len(chunk)/total
            cues.append({'start':cursor,'end':end,'text':chunk});cursor=end
    srt='\n\n'.join(f"{i+1}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}" for i,c in enumerate(cues))+'\n'
    (DEST/(name+'.ko.srt')).write_text(srt,encoding='utf-8')
    (OUT/(name+'.ko.srt')).write_text(srt,encoding='utf-8')
    ass='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Spoqa Han Sans Neo Medium,27,&H00F7F4F2,&H00F7F4F2,&H00201B17,&H00201B17,0,0,0,0,100,100,0,0,1,0,0,7,430,70,0,1
Style: Label,Spoqa Han Sans Neo Medium,18,&H00FFB482,&H00FFB482,&H00201B17,&H00201B17,0,0,0,0,100,100,0,0,1,0,0,7,80,0,0,1
Style: Note,Spoqa Han Sans Neo Medium,14,&H00C7B9AF,&H00C7B9AF,&H00201B17,&H00201B17,0,0,0,0,100,100,0,0,1,0,0,7,80,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    for cue in cues:
        text=cue['text'].replace('\n',r'\N')
        ass+=f"Dialogue: 0,{stamp(cue['start'],True)},{stamp(cue['end'],True)},Caption,,0,0,0,,{{\\pos(430,999)}}{text}\n"
    for scene in timeline:
        ass+=f"Dialogue: 0,{stamp(scene['start'],True)},{stamp(scene['end'],True)},Label,,0,0,0,,{{\\pos(80,1004)}}DATA:EZ · {scene['id']}\n"
    ass+=f"Dialogue: 0,0:00:00.00,{stamp(timeline[-1]['end'],True)},Note,,0,0,0,,{{\\pos(80,1040)}}실제 시연 · 합성 자료 · 읽기 정지\n"
    (DEST/(name+'.ass')).write_text(ass,encoding='utf-8')
    return cues


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--reuse-parts',action='store_true');args=parser.parse_args()
    candidates=sorted((LOCAL/'recordings').glob('*/rehearsal.json'),key=lambda p:p.stat().st_mtime)
    source_path=candidates[-1];report=json.loads(source_path.read_text(encoding='utf-8'))
    assert report['passed'] and report['page_error_count']==0
    raw=Path(report['video_path']);info=probe(raw);duration=float(info['format']['duration'])
    raw_hash=hashlib.sha256(raw.read_bytes()).hexdigest()
    marks={x['name']:x['time'] for x in report['marks']}
    offset=max(0,marks['end']-duration)
    marks={k:max(0,v-offset) for k,v in marks.items()}
    scenario=json.loads((OUT/'scenario.json').read_text(encoding='utf-8'))
    DEST.mkdir(exist_ok=True);PARTS.mkdir(exist_ok=True)
    font=TTFont(ROOT/'web/app/fonts/spoqa-500.woff2');font.flavor=None;(DEST/'fonts').mkdir(exist_ok=True);font.save(DEST/'fonts/spoqa.ttf')
    segments=[]
    def clip(name,dur,start,end,crop=None):
        a=marks[start] if isinstance(start,str) else start;b=marks[end] if isinstance(end,str) else end
        segments.append({'name':name,'duration':dur,'source':'recording','start':a,'end':min(b,duration), 'crop':crop})
        return name
    def card(name,dur,asset,crop=None):
        segments.append({'name':name,'duration':dur,'source':asset,'crop':crop});return name
    products=[clip('p01',8,marks['Q1_complete']+.3,marks['Q1_complete']+7.5),
        clip('p02',14,'Q1_library','Q1_question'),clip('p03',18,'Q1_question','Q1_analysis'),
        clip('p04a',7,'Q1_analysis','Q1_table'),clip('p04b',6,'Q1_table','Q1_sql',[1100,618,410,200]),clip('p04c',6,'Q1_sql','Q1_save_start',[1100,618,410,350]),clip('p05',20,'Q1_save_start','Q1_dashboard'),
        clip('p06',20,'Q1_dashboard',marks['Q1_complete']+7),card('p07',11,'end')]
    technical=[card('t01a',8,'problem'),clip('t01b',7,'pair_complete',marks['pair_complete']+7),
        clip('t01c',10,'Q1_file_preview','Q1_scope'),clip('t02a',14,'Q1_library','Q1_question'),card('t02b',26,'search'),
        clip('t03q',16,'Q1_question','Q1_analysis'),clip('t03chart',5,'Q1_analysis','Q1_table'),clip('t03table',6,'Q1_table','Q1_sql',[1100,618,410,200]),clip('t03sql',8,'Q1_sql','Q1_save_start',[1100,618,410,350]),clip('t03save',10,'Q1_save_start','Q1_dashboard'),
        clip('t04',45,'Q2_scope','append_explained'),card('t05a',8,'append'),
        clip('t05b',12,'refresh_Q1','refresh_Q2'),clip('t05c',16,'refresh_Q2','pair_layout'),
        clip('t05d',24,'pair_complete',marks['pair_complete']+7),
        clip('t06',30,'pair_layout','end'),card('t07a',18,'architecture',[1240,698,340,105]),card('t07b',17,'limits'),
        card('t08a',12,'evidence'),card('t08b',8,'end')]
    loop=[clip('l01',4,marks['Q1_send']-2,marks['Q1_send']+2),clip('l02',4,'Q1_analysis',marks['Q1_analysis']+4),
          clip('l03',4,'Q1_complete',marks['Q1_complete']+4)]
    text=(OUT/'NARRATION.md').read_text(encoding='utf-8')
    narration={m[0]:m[1].strip() for m in re.findall(r'### ([PT]\d\d).*?\*\*내레이션:\*\* (.*?)(?=\n\n)',text,re.S)}
    narration['T08']='파일 보관과 실제 분석, 저장, 재계산 흐름을 합성 데이터로 검증했습니다. 실제 PG 연동과 고객 사용성, 대규모 부하 검증은 다음 과제입니다. 구현과 검증 근거는 저장소에 정리했습니다. 공개 사이트에서 직접 체험할 수 있습니다.'
    cue_report={}
    for name,key in [('product','product_timeline'),('technical','technical_timeline')]:
        cue_report[name]=captions(name,scenario[key],narration)
    cue_report['loop']=captions('loop',scenario['loop_timeline'],{c['id']:c['caption'] for c in scenario['loop_timeline']})
    reuse=args.reuse_parts
    def encode(segment):
        name=segment['name'];args=['ffmpeg','-hide_banner','-loglevel','warning','-y','-threads','2']
        dur=segment['duration']
        input_hash=raw_hash if segment['source']=='recording' else hashlib.sha256((DEST/'assets'/(segment['source']+'.png')).read_bytes()).hexdigest()
        cache={'segment':dict(segment),'input_sha256':input_hash,'render_version':2}
        cache_file=PARTS/(name+'.input.json')
        if segment['source']=='recording':
            length=segment['end']-segment['start'];speed=min(1,dur/length)
            args+=['-ss',str(segment['start']),'-t',str(length),'-i',str(raw)]
            filters=[f'setpts={speed}*(PTS-STARTPTS)']
            segment['playback_speed']=1/speed;segment['held_seconds']=max(0,dur-length)
        else:
            args+=['-loop','1','-framerate','30','-i',str(DEST/'assets'/(segment['source']+'.png'))];filters=[]
        if segment.get('crop'):filters+=['crop='+':'.join(map(str,segment['crop']))]
        filters+=['scale=1760:990:flags=lanczos','setsar=1','fps=30','pad=1920:1080:80:0:color=0x171b20',
                  'tpad=stop_mode=clone:stop_duration='+str(dur)]
        args+=['-vf',','.join(filters),'-t',str(dur),'-an','-c:v','libx264','-preset','veryfast','-crf','18',
               '-pix_fmt','yuv420p','-threads','2',str(PARTS/(name+'.mp4'))]
        if reuse and (PARTS/(name+'.mp4')).exists() and cache_file.exists() and json.loads(cache_file.read_text())==cache:
            assert abs(float(probe(PARTS/(name+'.mp4'))['format']['duration'])-dur)<.1
            return
        run(args,PARTS/(name+'.log'));print('Rendered '+name,flush=True)
        cache_file.write_text(json.dumps(cache,sort_keys=True))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(encode,segments))
    for name,parts in [('product',products),('technical',technical),('loop',loop)]:
        listing=PARTS/(name+'.txt');listing.write_text(''.join(f"file '{p}.mp4'\n" for p in parts))
        run(['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','concat','-safe','0','-i',str(listing),
             '-vf',f"ass=output/portfolio-demo/{name}.ass:fontsdir=output/portfolio-demo/fonts",
             '-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-threads','4',
             '-movflags','+faststart',str(DEST/(name+'.mp4'))],PARTS/(name+'-final.log'))
        print('Completed '+name+'.mp4',flush=True)
    run(['ffmpeg','-hide_banner','-loglevel','warning','-y','-i',str(DEST/'loop.mp4'),'-an','-c:v','libvpx-vp9',
         '-crf','32','-b:v','0','-row-mt','1','-threads','4',str(DEST/'loop.webm')],PARTS/'loop-webm.log')
    evidence={'status':'rendered_not_reviewed','capture_fps':'25/1','output_fps':'30/1','size':[1920,1080],
        'audio':'none; Korean captions burned in and supplied as SRT','project_id':report['project_id'],
        'source_commit':report['source_commit'],'raw_duration_seconds':duration,'marker_offset_seconds':offset,
        'raw_sha256':raw_hash,'segments':segments,'cues':cue_report,
        'editing':'Hard cuts, real-speed footage unless playback_speed says otherwise; explicit final-frame reading holds.',
        'privacy':'Login occurred in a separate unrecorded context. Account label hidden by capture-only CSS. Cursor ring added.',
        'files':{}}
    for name in ['product.mp4','technical.mp4','loop.mp4','loop.webm']:
        p=DEST/name;meta=probe(p);s=meta['streams'][0]
        evidence['files'][name]={'duration':float(meta['format']['duration']),'codec':s['codec_name'],'width':s['width'],
             'height':s['height'],'fps':s['avg_frame_rate'],'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    (DEST/'render-manifest.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'phase-3-render.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Video render complete; visual and playback review still required',flush=True)


if __name__=='__main__':main()
