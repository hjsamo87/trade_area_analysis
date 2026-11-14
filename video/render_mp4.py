"""슬라이드(site/assets/slides.json) + 내레이션(site/assets/narration.mp3) -> video/proposal.mp4 (1920x1080, H.264/AAC)
실행: py -I -X utf8 video/render_mp4.py
slides.json: [{start_sec, title, bullets[], big_number?}]  (start_sec 순서대로, 마지막 슬라이드는 오디오 끝까지)
"""
import json, os, re, shutil, subprocess, tempfile
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLIDES = os.path.join(ROOT, "site", "assets", "slides.json")
AUDIO = os.path.join(ROOT, "site", "assets", "narration.mp3")
OUT = os.path.join(ROOT, "video", "proposal.mp4")
SITE_COPY = os.path.join(ROOT, "site", "assets", "proposal.mp4")
FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 1920, 1080
FONT_R, FONT_B = "C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"
INK, SUB, ACCENT, BG, LINE = (20, 24, 33), (90, 98, 112), (109, 40, 217), (255, 255, 255), (232, 228, 245)


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(draw, text, fnt, max_w):
    """한글은 글자 단위, 공백 우선으로 줄바꿈."""
    lines, cur = [], ""
    for token in re.findall(r"\S+\s*|\s+", str(text)):
        if draw.textlength(cur + token, font=fnt) <= max_w:
            cur += token
            continue
        if cur.strip():
            lines.append(cur.rstrip())
            cur = ""
        for ch in token:  # 토큰 자체가 길면 글자 단위
            if draw.textlength(cur + ch, font=fnt) > max_w and cur:
                lines.append(cur.rstrip()); cur = ""
            cur += ch
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def render(slide, idx, total, path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 24, H], fill=ACCENT)
    x, maxw = 140, W - 280
    y = 110
    d.text((x, y), f"{idx + 1:02d} / {total:02d}", font=font(FONT_B, 30), fill=ACCENT)
    y += 70
    for ln in wrap(d, slide.get("title", ""), font(FONT_B, 72), maxw):
        d.text((x, y), ln, font=font(FONT_B, 72), fill=INK); y += 96
    y += 20
    d.line([x, y, x + 160, y], fill=ACCENT, width=6)
    y += 50
    big = slide.get("big_number")
    if big:
        for ln in wrap(d, big, font(FONT_B, 120), maxw):
            d.text((x, y), ln, font=font(FONT_B, 120), fill=ACCENT); y += 150
        y += 20
    fb = font(FONT_R, 46)
    for b in slide.get("bullets", []) or []:
        lines = wrap(d, b, fb, maxw - 60)
        if y + 64 * len(lines) > H - 140:
            break
        d.ellipse([x, y + 22, x + 16, y + 38], fill=ACCENT)
        for ln in lines:
            d.text((x + 50, y), ln, font=fb, fill=INK); y += 64
        y += 22
    d.line([x, H - 110, W - 140, H - 110], fill=LINE, width=2)
    d.text((x, H - 90), "자료: 서울 열린데이터광장 상권분석서비스 · 팀 분석", font=font(FONT_R, 26), fill=SUB)
    im.save(path)


def audio_seconds():
    p = subprocess.run([FF, "-i", AUDIO], capture_output=True, text=True, encoding="utf-8", errors="ignore")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def main():
    slides = sorted(json.load(open(SLIDES, encoding="utf-8")), key=lambda s: float(s["start_sec"]))
    dur = audio_seconds()
    tmp = tempfile.mkdtemp(prefix="slides_")
    concat = []
    for i, s in enumerate(slides):
        png = os.path.join(tmp, f"s{i:02d}.png")
        render(s, i, len(slides), png)
        start = 0.0 if i == 0 else float(s["start_sec"])  # 첫 장은 0초부터
        end = float(slides[i + 1]["start_sec"]) if i + 1 < len(slides) else dur
        concat.append((png, max(0.5, end - start)))
    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for png, sec in concat:
            f.write(f"file '{png.replace(os.sep, '/')}'\nduration {sec:.3f}\n")
        f.write(f"file '{concat[-1][0].replace(os.sep, '/')}'\n")  # concat demuxer: 마지막 프레임 유지
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cmd = [FF, "-y", "-f", "concat", "-safe", "0", "-i", lst, "-i", AUDIO,
           "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p", "-tune", "stillimage",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", OUT]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode:
        raise SystemExit(r.stderr[-2000:])
    shutil.copyfile(OUT, SITE_COPY)
    # 미리보기용 첫 장 저장
    shutil.copyfile(concat[0][0], os.path.join(ROOT, "video", "poster.png"))
    shutil.copyfile(concat[0][0], os.path.join(ROOT, "site", "assets", "poster.png"))
    print(f"OK {OUT}  slides={len(slides)}  audio={dur:.1f}s  size={os.path.getsize(OUT)/1e6:.1f}MB")


if __name__ == "__main__":
    main()
