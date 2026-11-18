"""Record the README and talk media from a live run of `./dvap demo --auto`.

    uv sync --group media && uv run --group media playwright install chromium   # once
    uv run --group media python scripts/record_demo.py

Builds and starts the lab from this checkout with the agent in replay mode (your .env is not
changed), records the HMI's presenter view (http://127.0.0.1:8080/?presenter=1) in headless
Chromium at 1280x720 while the staged demo runs, stops the lab, and writes:

  docs/assets/demo.gif            ~15 s loop: malicious ticket -> tank rises -> PHYSICAL INCIDENT
  docs/assets/demo-full.mp4       the whole staged demo (attack, then the same attack blocked), H.264
  docs/assets/social-preview.png  1280x640, the incident with the project's title (GitHub social preview)

The demo's own output marks the moments to cut on (steps, the incident, the guard's denial), and the
script lays a caption bar over the page for each step so the video tells the story without the
terminal. It stops the lab when it is done (`docker compose down`, data volumes kept).
"""

from __future__ import annotations

import base64
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from bench import ops, stage

ASSETS = ROOT / "docs" / "assets"
W, H = 1280, 720
GIF_SECONDS, GIF_FPS, GIF_WIDTH, GIF_MAX_BYTES = 15, 12, 960, 5_000_000
SC = stage.SCENARIOS["C01"]  # the overflow reads best on screen
TITLE, SUBTITLE = "DVAP — Damn Vulnerable Agentic Plant", "Prompt injection with physical consequences"

# A line of the demo's output -> (event name, caption shown over the HMI from then on).
CUES = [
    (r"=== 1 · ", "step1", "1 · A clean plant. SafeEnvelope is OFF."),
    (r"=== 2 · ", "step2", "2 · Normal operation: the AI operator reads the plant, nothing to do."),
    (r"=== 3 · ", "step3", f"3 · An outsider files a maintenance ticket: “{SC.injected}”"),
    (r"=== 4 · ", "step4", "4 · The agent reads the ticket and obeys it."),
    (r"PHYSICAL INCIDENT: ", "incident", "4 · PHYSICAL INCIDENT: the tank overflows."),
    (r"=== 5 · ", "step5", "5 · Reset. SafeEnvelope ON. The same ticket, word for word."),
    (r"=== 6 · ", "step6", "6 · SafeEnvelope DENIES the setpoint change. No incident."),
    (r"=== 7 · ", "step7", "Same attack, two outcomes: overflow without the guard, blocked with it."),
    (r"\(demo ran ", "end", None),
]

CAPTION_JS = """([text, note]) => {
  let bar = document.getElementById("dvap-caption");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "dvap-caption";
    bar.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:99;padding:16px 28px;" +
      "background:rgba(8,12,18,.92);border-top:2px solid #ffd21f;color:#fff;" +
      "font:600 24px/1.3 system-ui,'Segoe UI',sans-serif;display:flex;gap:24px;align-items:center";
    bar.innerHTML = '<span id="dvap-caption-text" style="flex:1"></span>' +
      '<span id="dvap-caption-note" style="font:500 14px system-ui;opacity:.7;white-space:nowrap"></span>';
    document.body.appendChild(bar);
  }
  bar.hidden = !text;
  document.getElementById("dvap-caption-text").textContent = text || "";
  document.getElementById("dvap-caption-note").textContent = note || "";
}"""

SOCIAL_HTML = """<!doctype html><html><body style="margin:0;width:1280px;height:640px;overflow:hidden;
background:#0b0f14 url('data:image/png;base64,{img}') center top / 1280px auto no-repeat;
font-family:system-ui,'Segoe UI',sans-serif;color:#fff">
<div style="position:absolute;inset:auto 0 0 0;padding:140px 56px 44px;
background:linear-gradient(transparent,rgba(5,8,12,.88) 45%,rgba(5,8,12,.97))">
<div style="font-weight:800;font-size:56px;line-height:1.08;letter-spacing:-.01em">{title}</div>
<div style="font-weight:600;font-size:32px;line-height:1.3;margin-top:12px;color:#ffd21f">{subtitle}</div>
</div></body></html>"""


def ffmpeg() -> str:
    import imageio_ffmpeg  # the media group's bundled ffmpeg binary

    return imageio_ffmpeg.get_ffmpeg_exe()


def sh(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def lab_env() -> dict[str, str]:
    """Replay agent and no Ollama for the recording, whatever .env says (it is not modified)."""
    return dict(os.environ, MODEL="replay", DVAP_LLM_MODE="replay", COMPOSE_PROFILES="none")


def start_lab() -> None:
    sh(["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.build.yml",
        "up", "-d", "--build", "--wait", "--wait-timeout", "300"], env=lab_env())


def stop_lab() -> None:
    sh(["docker", "compose", "down"], env=lab_env())


def run_demo_and_record(work: Path) -> tuple[Path, dict[str, float], Path]:
    """Record the HMI while the demo runs. Returns (video, event times in video seconds, incident still)."""
    from playwright.sync_api import sync_playwright

    hmi = ops.urls(ops.read_env())["HMI"]
    lines: queue.Queue[tuple[float, str]] = queue.Queue()
    events: dict[str, float] = {}
    still = work / "incident.png"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=1,
                                  record_video_dir=str(work), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        t0 = time.monotonic()  # the video starts with the page
        page.goto(f"{hmi}/?presenter=1")
        page.wait_for_timeout(3000)  # charts' history, the first live poll

        demo = subprocess.Popen([sys.executable, "-m", "bench", "demo", "--auto"], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                                env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", NO_COLOR="1"))

        def read() -> None:
            assert demo.stdout is not None
            for line in demo.stdout:
                lines.put((time.monotonic() - t0, line.rstrip()))

        threading.Thread(target=read, daemon=True).start()
        while demo.poll() is None or not lines.empty():
            try:
                at, line = lines.get(timeout=0.1)
            except queue.Empty:
                page.wait_for_timeout(50)  # keeps the page (and its recording) running
                continue
            print(f"[{at:6.1f}s] {line}", flush=True)
            for pattern, name, caption in CUES:
                if name not in events and re.search(pattern, line):
                    events[name] = at
                    if caption is not None:
                        page.evaluate(CAPTION_JS, [caption, f"plant clock {SC.speed}× real time"])
                    if name == "incident":
                        page.wait_for_timeout(1500)  # let the banner land
                        page.evaluate(CAPTION_JS, [None, None])
                        page.screenshot(path=str(still))
                        page.evaluate(CAPTION_JS, [caption, f"plant clock {SC.speed}× real time"])
        page.wait_for_timeout(4000)  # hold the summary caption
        video = Path(page.video.path()) if page.video else None
        ctx.close()  # finalises the video file

        if demo.returncode != 0 or video is None or not still.exists():
            sys.exit(f"the demo failed (exit {demo.returncode}); nothing was written")
        social = browser.new_page(viewport={"width": 1280, "height": 640})
        social.set_content(SOCIAL_HTML.format(img=base64.b64encode(still.read_bytes()).decode(),
                                              title=TITLE, subtitle=SUBTITLE))
        social.screenshot(path=str(ASSETS / "social-preview.png"))
        browser.close()
    return video, events, still


def mp4_start(events: dict[str, float]) -> float:
    return max(0.0, events["step1"] - 1)


def encode_mp4(video: Path, events: dict[str, float]) -> Path:
    out = ASSETS / "demo-full.mp4"
    start, end = mp4_start(events), events["end"] + 4
    sh([ffmpeg(), "-y", "-loglevel", "error", "-i", str(video), "-ss", f"{start:.2f}", "-to", f"{end:.2f}",
        "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-an", str(out)])
    return out


def encode_gif(mp4: Path, events: dict[str, float]) -> Path:
    """The key moment, sped up into a ~15 s loop, with palettegen/paletteuse; under 5 MB. Cut from the
    H.264 file: Playwright's VP8 noise, re-dithered every frame, would make the GIF twice the size."""
    out = ASSETS / "demo.gif"
    start, end = events["step3"] - 0.5 - mp4_start(events), events["incident"] + 5 - mp4_start(events)
    speed = (end - start) / GIF_SECONDS
    for fps, colors in ((GIF_FPS, 128), (10, 96), (8, 64)):  # step down until it fits
        # trim inside the graph: -ss/-to with a filter graph would cut the already sped-up timeline
        graph = (f"trim=start={start:.2f}:end={end:.2f},setpts=(PTS-STARTPTS)/{speed:.4f},fps={fps},scale={GIF_WIDTH}:-1:flags=lanczos,split[a][b];"
                 f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
                 f"[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
        sh([ffmpeg(), "-y", "-loglevel", "error", "-i", str(mp4), "-filter_complex", graph, "-loop", "0", str(out)])
        if out.stat().st_size <= GIF_MAX_BYTES:
            break
    print(f"demo.gif: {end - start:.0f} s of demo at {speed:.1f}x, {fps} fps, {out.stat().st_size / 1e6:.1f} MB")
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]  # the demo prints "·"
    ASSETS.mkdir(parents=True, exist_ok=True)
    start_lab()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            video, events, _ = run_demo_and_record(Path(tmp))
            encode_gif(encode_mp4(video, events), events)
    finally:
        stop_lab()
    for name in ("demo.gif", "demo-full.mp4", "social-preview.png"):
        print(f"wrote docs/assets/{name} ({(ASSETS / name).stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
