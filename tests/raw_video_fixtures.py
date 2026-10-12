"""Unlabelled moving pictures plus ordinary supplied ASR, never semantic answers.

The deterministic audio is ambient sound, not a speech-recognition benchmark.
Ground truth belongs to the evaluator after production inference, not this API.
"""
from __future__ import annotations

import array
import math
from pathlib import Path
import random
import subprocess
import sys
import wave

from PIL import Image, ImageDraw, ImageEnhance

from app.config import FFMPEG, ROOT
from app.json_store import analysis_json as atomic_json


FIXTURE_NAMES = ('reverse_shots_same_room', 'similar_rooms', 'binding_same_background',
                 'kidnapping_vehicle', 'slow_fade', 'short_action_during_asr', 'long_tracking_action')
FRAME_SIZE = (640, 360)
FPS = 12
FIXTURE_VERSION = 1
_DURATIONS = {name: 12 for name in FIXTURE_NAMES}
_DURATIONS.update(kidnapping_vehicle=14, long_tracking_action=14)


def _workspace(path):
    path = Path(path).resolve()
    path.relative_to(ROOT.resolve())
    return path


def _mix(left, right, amount):
    return tuple(round(a+(b-a)*amount) for a, b in zip(left, right))


def _room(variant=0):
    picture = Image.new('RGB', FRAME_SIZE, (211, 207, 181))
    d = ImageDraw.Draw(picture)
    d.rectangle((0, 244, 639, 359), fill=(133, 111, 91))
    for x in range(-160, 800, 120):
        d.line((x, 360, 320+(x-320)*.55, 244), fill=(94, 77, 64), width=2)
    for y in (271, 310, 355):
        d.line((0, y, 640, y), fill=(94, 77, 64), width=2)
    d.rectangle((0, 231, 640, 245), fill=(107, 81, 65))
    wx = 436 if variant == 0 else 43
    d.rounded_rectangle((wx-8, 28, wx+148, 160), radius=12, fill=(110, 92, 78))
    d.rectangle((wx, 36, wx+140, 152), fill=(149, 184, 190))
    d.ellipse((wx+15, 42, wx+90, 72), fill=(202, 217, 206))
    d.line((wx+70, 36, wx+70, 152), fill=(246, 235, 195), width=6)
    d.line((wx, 93, wx+140, 93), fill=(246, 235, 195), width=6)
    sx = 35 if variant == 0 else 444
    d.rectangle((sx, 37, sx+120, 220), fill=(113, 85, 63), outline=(62, 54, 45), width=4)
    for y in (88, 139, 190):
        d.rectangle((sx+6, y-39, sx+114, y), fill=(81, 63, 49))
        for i in range(8):
            bx = sx+11+i*12
            color = ((152, 91, 82), (102, 132, 126), (191, 159, 111))[i % 3]
            d.rectangle((bx, y-33-(i%3)*2, bx+8, y-3), fill=color)
    if variant == 0:
        d.rectangle((244, 32, 362, 114), fill=(105, 76, 53), outline=(67, 49, 34), width=4)
        d.rectangle((251, 39, 355, 107), fill=(202, 182, 132))
        d.polygon(((260, 97), (297, 49), (345, 97)), fill=(139, 90, 83))
        d.ellipse((312, 47, 331, 66), fill=(170, 148, 73))
    else:
        d.ellipse((262, 35, 340, 113), fill=(120, 93, 63), outline=(67, 49, 34), width=4)
        d.ellipse((269, 42, 333, 106), fill=(224, 212, 173))
        d.line((301, 75, 302, 50), fill=(61, 66, 57), width=4)
        d.line((301, 75, 321, 84), fill=(61, 66, 57), width=4)
        d.rectangle((365, 142, 398, 204), fill=(129, 87, 62))
        for i in range(5):
            d.ellipse((338+i*8, 96+i%2*14, 389+i*8, 153+i%2*14), fill=(77, 113, 78))
        # Persistent room architecture distinguishes a new location from a
        # reverse camera angle. The palette remains close to the first room.
        d.polygon(((0,0),(639,0),(639,27),(518,45),(411,60),(322,68),
                   (224,61),(108,44),(0,24)), fill=(155,146,126))
        d.arc((-45,-130,685,141),0,180,fill=(105,94,78),width=9)
        d.rectangle((364,67,408,246),fill=(187,176,148),outline=(121,107,86),width=4)
        d.rectangle((354,62,419,82),fill=(153,140,114),outline=(108,94,73),width=3)
        d.rectangle((351,239,421,257),fill=(153,140,114),outline=(108,94,73),width=3)
        d.rectangle((0,247,639,292),fill=(182,168,138),outline=(105,92,73),width=3)
        for xx in range(-80,721,80):
            d.line((xx,247,xx+20,291),fill=(124,111,89),width=2)
        for yy in (261,277):
            d.line((0,yy,639,yy),fill=(124,111,89),width=2)
        d.rectangle((0,292,639,308),fill=(126,110,88),outline=(88,75,60),width=3)
    return picture


def _street(offset=0):
    picture = Image.new('RGB', FRAME_SIZE, (182, 203, 207))
    d = ImageDraw.Draw(picture)
    for x in range(-200, 900, 160):
        left = x+offset
        d.rectangle((left, 23, left+146, 247), fill=(170, 163, 150), outline=(104, 103, 102), width=3)
        for wx in (left+18, left+82):
            for wy in (47, 112, 177):
                d.rectangle((wx, wy, wx+44, wy+43), fill=(95, 113, 125), outline=(68, 77, 86), width=3)
    d.rectangle((0, 247, 640, 359), fill=(92, 101, 105))
    d.rectangle((0, 247, 640, 269), fill=(186, 185, 171))
    d.line((0, 300, 640, 300), fill=(205, 198, 162), width=4)
    return picture


def _person(picture, x, y, *, scale=1, shirt=(57, 98, 141), hair=(51, 40, 36),
            hands=None, rope=0, stride=0, mouth=0, facing=1):
    d = ImageDraw.Draw(picture)
    skin = (225, 179, 144)
    outline = (42, 42, 45)
    def p(a, b):
        return (x+a*scale, y+b*scale)
    def box(a, b, c, e):
        return (*p(a, b), *p(c, e))
    def line(points, color, width):
        d.line([p(*point) for point in points], fill=color, width=max(1, round(width*scale)), joint='curve')
    leg = math.sin(stride)*22
    line([(-15, 126), (-18-leg, 165), (-13+leg, 202)], outline, 20)
    line([(15, 126), (18+leg, 165), (13-leg, 202)], outline, 20)
    d.ellipse(box(-29+leg, 193, -4+leg, 207), fill=(39, 38, 39))
    d.ellipse(box(4-leg, 193, 29-leg, 207), fill=(39, 38, 39))
    d.polygon([p(-31, 40), p(31, 40), p(36, 127), p(-35, 127)], fill=shirt, outline=outline)
    line([(0, 46), (0, 125)], _mix(shirt, (255, 255, 255), .24), 2)
    for yy in (57, 83, 109):
        d.ellipse(box(6, yy, 9, yy+3), fill=(192, 185, 164))
    if hands is None:
        hands = ((-44-leg*.6, 111), (44+leg*.6, 111))
    for side, hand in zip((-1, 1), hands):
        elbow = ((29*side+hand[0])*.52, 70+(hand[1]-70)*.55)
        line([(29*side, 53), elbow], shirt, 19)
        line([elbow, hand], skin, 13)
        d.ellipse(box(hand[0]-8, hand[1]-8, hand[0]+8, hand[1]+8), fill=skin, outline=outline, width=max(1,round(scale)))
    d.rectangle(box(-10, 23, 10, 43), fill=skin, outline=outline)
    d.ellipse(box(-27, -26, 27, 32), fill=skin, outline=outline, width=max(1,round(2*scale)))
    d.pieslice(box(-30, -32, 28, 22), 178, 359, fill=hair)
    d.polygon([p(-28, -3), p(-19, -24), p(14, -24), p(24, -7), p(6, -14), p(-3, -4), p(-11, -12)], fill=hair)
    for eye in (-11, 11):
        d.ellipse(box(eye-3+facing, 0, eye+3+facing, 7), fill=(247, 239, 219))
        d.ellipse(box(eye-1+facing, 2, eye+2+facing, 7), fill=(43, 50, 57))
        line([(eye-5, -4), (eye+4, -5)], hair, 2)
    line([(facing*3, 9), (facing*5, 14), (0, 16)], (168, 124, 98), 1)
    d.ellipse(box(-7, 21, 8, 23+mouth*5), fill=(113, 65, 62))
    if rope:
        # Separate rope coils around two visible wrists and a connecting knot.
        # Hands remain skin-coloured so this cannot look like a carried parcel.
        for hx in (-15,15):
            for yy in (99,102,105):
                d.ellipse(box(hx-10,yy-4,hx+10,yy+4),outline=(64,48,30),width=max(1,round(3*scale)))
                d.ellipse(box(hx-9,yy-3,hx+9,yy+3),outline=(222,172,87),width=max(1,round(2*scale)))
        line([(-17,103),(-5,105),(5,101),(17,103)],(222,172,87),3)
        d.ellipse(box(-6,100,5,109),outline=(222,172,87),width=max(1,round(2*scale)))
        if rope > .8:
            line([(1,105),(12,129),(2,144)],(64,48,30),4)
            line([(1,105),(12,129),(2,144)],(222,172,87),2)


def _vehicle(picture, *, open_door=False):
    d = ImageDraw.Draw(picture)
    d.rounded_rectangle((260, 103, 616, 310), radius=24, fill=(60, 72, 81), outline=(29, 34, 40), width=5)
    d.polygon(((328, 105), (551, 105), (598, 175), (305, 175)), fill=(81, 114, 126), outline=(29, 34, 40))
    for cx in (335, 551):
        d.ellipse((cx-36, 268, cx+36, 340), fill=(27, 30, 33), outline=(20, 22, 24), width=4)
        d.ellipse((cx-17, 287, cx+17, 321), fill=(127, 135, 140))
    d.line((400, 109, 400, 300), fill=(29, 34, 40), width=4)
    if open_door:
        d.polygon(((400, 173), (503, 173), (503, 291), (400, 291)), fill=(20, 27, 34))
        d.polygon(((501, 172), (603, 158), (603, 289), (501, 292)), fill=(73, 83, 91), outline=(29, 34, 40))
        d.polygon(((511, 181), (593, 171), (593, 208), (511, 215)), fill=(111, 141, 152))
    d.rectangle((575, 237, 615, 262), fill=(189, 99, 76))


def _interior():
    picture = Image.new('RGB', FRAME_SIZE, (47, 58, 65))
    d = ImageDraw.Draw(picture)
    d.rounded_rectangle((23, 37, 260, 164), radius=18, fill=(143, 169, 173), outline=(20, 28, 34), width=12)
    d.rounded_rectangle((381, 37, 618, 164), radius=18, fill=(143, 169, 173), outline=(20, 28, 34), width=12)
    for x in (40, 385):
        d.line((x, 114, x+210, 100), fill=(120, 138, 138), width=26)
    d.rounded_rectangle((89, 164, 552, 345), radius=30, fill=(74, 77, 82), outline=(30, 36, 44), width=6)
    d.line((310, 169, 310, 337), fill=(48, 52, 58), width=3)
    return picture


def _render(name, t):
    talking = .6+.4*math.sin(t*8)
    if name == 'reverse_shots_same_room':
        picture = _room()
        camera = int(t/2)%2
        if camera == 0:
            _person(picture, 300, 67, scale=1.27, mouth=talking)
            _person(picture, 620, 105, scale=1.8, shirt=(137, 93, 80), hair=(139, 110, 65), facing=-1)
        else:
            _person(picture, 330, 67, scale=1.27, shirt=(137, 93, 80), hair=(139, 110, 65), mouth=talking, facing=-1)
            _person(picture, -20, 105, scale=1.8)
        return picture
    if name == 'similar_rooms':
        picture = _room(0 if t < 6 else 1)
        _person(picture, 295, 79, scale=1.15, mouth=talking)
        return picture
    if name in ('binding_same_background', 'short_action_during_asr'):
        picture = _room()
        if name == 'binding_same_background':
            amount = min(1, max(0, (t-4)/2))
            hands = ((-45+37*amount, 109), (45-37*amount, 109))
            if t >= 4:
                _person(picture, 440-45*amount, 73, scale=1.14, shirt=(46, 49, 54), hands=((-87, 121),(-70, 111)))
            _person(picture, 269, 68, scale=1.25, hands=hands, rope=max(0,min(1,(t-5.5)/1.5)), mouth=talking*.3)
        else:
            amount = min(1, max(0, (t-4.8)/1.5))
            _person(picture, 291, 69, scale=1.25, hands=((-44, 111), (44+25*amount, 111-35*amount)), mouth=talking)
            d = ImageDraw.Draw(picture)
            if 4.8 <= t < 6.3:
                hx = 548-(t-4.8)/1.5*163
                d.line((640, 190, hx+30, 189), fill=(46, 49, 54), width=25)
                d.ellipse((hx+16, 175, hx+46, 204), fill=(225,179,144))
                d.rectangle((hx-45, 147, hx+19, 213), fill=(146, 57, 54), outline=(67,40,39), width=4)
            elif t >= 6.3:
                d.rectangle((365, 143, 416, 211), fill=(146,57,54), outline=(67,40,39), width=4)
                d.line((360,207,405,207),fill=(225,179,144),width=13)
        return picture
    if name == 'kidnapping_vehicle':
        if t >= 11:
            picture = _interior()
            _person(picture, 327, 86, scale=1.26, hands=((-8,109),(8,109)), rope=1)
            return picture
        picture = _street()
        if t < 5:
            _person(picture, 233, 91, shirt=(57,98,141), mouth=talking)
            _person(picture, 421, 91, shirt=(137,93,80), hair=(139,110,65), mouth=1-talking, facing=-1)
        elif t < 8:
            amount = min(1,(t-5)/1.5)
            _person(picture, 365, 80, scale=1.2, shirt=(46,49,54), hands=((-83,111),(-65,115)))
            _person(picture, 252, 81, scale=1.2, hands=((-45+37*amount,109),(45-37*amount,109)), rope=amount)
        else:
            _vehicle(picture, open_door=True)
            x = 191+(t-8)*70
            _person(picture, x+80, 103, scale=.92, shirt=(46,49,54), hands=((-60,74),(-65,91)))
            _person(picture, x, 103, scale=.92, hands=((-8,109),(8,109)), rope=1, stride=t*7)
        return picture
    if name == 'slow_fade':
        if t < 6:
            picture = _room()
            _person(picture, 293, 80, scale=1.1)
            return ImageEnhance.Brightness(picture).enhance(1 if t < 4 else max(0,1-(t-4)/2))
        picture = _street()
        _person(picture, 332, 87, scale=1.06, shirt=(137,93,80), hair=(139,110,65))
        return ImageEnhance.Brightness(picture).enhance(min(1,(t-6)/2)*.8)
    if name == 'long_tracking_action':
        picture = Image.new('RGB', FRAME_SIZE, (185,183,157))
        d = ImageDraw.Draw(picture)
        d.rectangle((0,254,640,360),fill=(111,116,109))
        offset = (t*68)%170
        for x in range(-340,1000,170):
            xx = x-offset
            d.rectangle((xx,20,xx+18,271),fill=(127,130,113))
            d.rectangle((xx+40,48,xx+114,181),fill=(94,123,130),outline=(72,86,88),width=4)
            d.line((xx,315,xx+100,270),fill=(80,90,83),width=3)
        jump = max(0,1-abs(t-7)/1.0)*51
        _person(picture, 310, 86-jump, scale=1.05, stride=t*8, hands=((-56,70+math.sin(t*8)*35),(56,70-math.sin(t*8)*35)))
        _person(picture, 95, 101, scale=.98, shirt=(46,49,54), stride=t*8+.8)
        if 5.3 < t < 8.8:
            cx = 628-(t-5.3)*145
            d.polygon(((cx,291),(cx+61,278),(cx+75,310),(cx+22,330)),fill=(123,86,56),outline=(67,56,47))
            d.line((cx+15,291,cx+41,340),fill=(67,56,47),width=6)
        return picture
    raise ValueError('Unknown raw video fixture')


def _transcript(name):
    if name == 'reverse_shots_same_room':
        replies = [(1,3.5,'Ты уже закончил работу'),(4,6.6,'Почти, осталось немного'),(7,10.6,'Хорошо, я подожду здесь')]
    elif name == 'short_action_during_asr':
        replies = [(1,11.2,'Я думаю сегодня мы успеем всё обсудить и потом спокойно закончим эту работу')]
    elif name == 'similar_rooms':
        replies = [(1,4.8,'Я зайду немного позже'),(7,10.8,'Хорошо, я тебя услышал')]
    elif name == 'kidnapping_vehicle':
        replies = [(1,4.4,'Я не уверен что успею'),(11.5,13.7,'Что теперь будет')]
    elif name == 'binding_same_background':
        replies = [(1,3.2,'Мы почти закончили'),(8.5,11.4,'Подождите немного')]
    elif name == 'slow_fade':
        replies = [(1,3.2,'До завтра'),(9,11,'Уже поздно')]
    else:
        replies = [(1,2.8,'Подожди меня'),(11,13.2,'Ещё немного')]
    segments, words = [], []
    for start,end,text in replies:
        segments.append({'start':start,'end':end,'text':text})
        items = text.split()
        step = (end-start)/len(items)
        words.extend({'start':round(start+i*step,4),'end':round(start+(i+.83)*step,4),'text':word}
                     for i,word in enumerate(items))
    return {'segments':segments,'words':words}


def _ambient(path, duration, name):
    rate = 16000
    rng = random.Random(491)
    samples = array.array('h')
    for i in range(round(duration*rate)):
        t = i/rate
        value = .003*math.sin(2*math.pi*83*t)+.002*rng.uniform(-1,1)
        if name == 'long_tracking_action':
            pulse = math.exp(-((t%.37)/.025)**2)
            value += .05*pulse*math.sin(2*math.pi*110*t)
        if name == 'kidnapping_vehicle' and 8 <= t < 14:
            value += .014*math.sin(2*math.pi*58*t)+.006*rng.uniform(-1,1)
        samples.append(round(max(-1,min(1,value))*32767))
    if sys.byteorder != 'little':
        samples.byteswap()
    with wave.open(str(path),'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(rate)
        output.writeframes(samples.tobytes())


def build_fixture(name, directory):
    """Return exactly (video Path, words/segments); model inputs contain no oracle."""
    if name not in FIXTURE_NAMES:
        raise ValueError('Unknown raw video fixture')
    directory = _workspace(directory)
    directory.mkdir(parents=True,exist_ok=True)
    source = directory/'source.mp4'
    duration = _DURATIONS[name]
    frames = directory/'frames'
    frames.mkdir(exist_ok=True)
    for index in range(duration*FPS):
        _render(name,index/FPS).save(frames/f'{index:05d}.png')
    audio = directory/'ambient.wav'
    _ambient(audio,duration,name)
    command = [str(FFMPEG),'-y','-v','error','-framerate',str(FPS),'-i',str(frames/'%05d.png'),
               '-i',str(audio),'-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',
               '-c:a','aac','-b:a','64k','-map_metadata','-1','-movflags','+faststart',str(source)]
    completed = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',
        timeout=120,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    if completed.returncode:
        raise RuntimeError('Fixture encoding failed: '+completed.stderr[-1500:])
    transcript = _transcript(name)
    atomic_json(directory/'transcript.json',transcript)
    # Physical input facts only. No scenario name, semantic labels or expected cuts.
    atomic_json(directory/'input.json',{'source':str(source),'transcript':str(directory/'transcript.json')})
    review = directory/'review'
    review.mkdir(exist_ok=True)
    columns = 4
    sample_times = [duration*i/12 for i in range(12)]
    canvas = Image.new('RGB',(320*columns,204*3),(31,34,38))
    draw = ImageDraw.Draw(canvas)
    for index,t in enumerate(sample_times):
        frame = _render(name,t).resize((320,180))
        x,y = index%columns*320,index//columns*204
        canvas.paste(frame,(x,y+24))
        draw.text((x+6,y+6),f'{t:.2f}s',fill='white')
    canvas.save(review/'contact_sheet.jpg',quality=91)
    return source,transcript
