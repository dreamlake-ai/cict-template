"""Headless Isaac Sim scene for DreamLake CI/CT.

Drops a grid of rigid cubes onto a ground plane, steps physics (optionally with
RTX camera rendering) for a wall-clock budget, checks the physics settled
plausibly, and writes to --out: summary.json, metrics.json, frame.png (when
rendering) and a replay DreamLake's viewer opens from the run's evidence (the
.dreamrc, with episodes/sim/camera.mp4 and telemetry.csv on one clock).
Replace the scene and the checks with your own.
"""
import argparse
import json
import os
import time

parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True)
parser.add_argument("--sim-seconds", type=float, default=600)
parser.add_argument("--render", default="true")
parser.add_argument("--grid", type=int, default=8, help="cubes per side (grid x grid)")
parser.add_argument("--video-seconds", type=float, default=10,
                    help="simulated seconds of camera video to record (0: none)")
parser.add_argument("--warmup-seconds", type=float, default=900,
                    help="most time to wait for the first rendered frame (shader compilation)")
args = parser.parse_args()
render = str(args.render).lower() in ("1", "true", "yes")
os.makedirs(args.out, exist_ok=True)

t_boot = time.time()
from isaacsim import SimulationApp  # noqa: E402  (must start before other omni imports)

app = SimulationApp({"headless": True, "width": 640, "height": 480})
boot_s = time.time() - t_boot

import numpy as np  # noqa: E402
from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.api.objects import DynamicCuboid  # noqa: E402

cases, metrics, files = [], [], []

# DreamLake's viewer config for this run folder: the camera video, the scene's numbers as charts,
# and a timeline to scrub both. Field names are file names (camera.mp4 -> camera, telemetry.csv ->
# telemetry); a chart series names [file, column].
VIDEO_VIEW = """  - view: videoStack
    cameras: ["*"]
    height: 360
"""
DREAMRC = """version: 1
name: Isaac Sim - falling cubes
dataset:
  format: folder
  episodes: "episodes/*/"
  fps: {fps}
views:
{video}  - view: timeline
  - view: lineChart
    title: Cube height (m)
    series:
      - {{ field: [telemetry, mean_height_m], label: mean }}
      - {{ field: [telemetry, max_height_m], label: highest }}
  - view: lineChart
    title: Mean cube speed (m/s)
    series:
      - {{ field: [telemetry, mean_speed_mps] }}
"""


def case(cid, checks):
    cases.append({"id": cid, "passed": all(c["passed"] for c in checks), "checks": checks})


world = World(stage_units_in_meters=1.0, physics_dt=1 / 120, rendering_dt=1 / 30)
world.scene.add_default_ground_plane()
size, drop = 0.2, 1.5
cubes = []
for i in range(args.grid):
    for j in range(args.grid):
        cubes.append(world.scene.add(DynamicCuboid(
            prim_path=f"/World/cube_{i}_{j}", name=f"cube_{i}_{j}", size=size,
            position=np.array([(i - args.grid / 2) * 0.5, (j - args.grid / 2) * 0.5, drop + 0.05 * ((i + j) % 4)]),
            color=np.array([0.2 + 0.6 * i / args.grid, 0.4, 0.2 + 0.6 * j / args.grid]),
        )))

camera = None
if render:
    try:
        from isaacsim.sensors.camera import Camera
        camera = Camera(prim_path="/World/camera", position=np.array([6.0, 6.0, 4.0]),
                        resolution=(640, 480), orientation=None)
    except Exception as e:  # rendering stack unavailable: report, keep the physics case
        case("render_setup", [{"name": "camera", "passed": False, "observed": repr(e)[:200], "expected": "camera created"}])

world.reset()


def frame_of(cam):
    f = cam.get_rgba()
    return f if f is not None and getattr(f, "size", 0) > 0 else None


warmup_s, warm_frames = 0.0, 0
if camera is not None:
    camera.initialize()
    try:
        from isaacsim.core.utils.viewports import set_camera_view
        set_camera_view(eye=[6.0, 6.0, 4.0], target=[0, 0, 0], camera_prim_path="/World/camera")
    except Exception:
        pass
    # The first RTX frame compiles shaders (minutes on a cold cache). Wait for a real
    # frame before timing, rendering without stepping physics so the cubes stay put.
    print("warming up the renderer (first frame compiles shaders)", flush=True)
    tw = time.time()
    while time.time() - tw < args.warmup_seconds and app.is_running():
        world.render()
        warm_frames += 1
        if frame_of(camera) is not None:
            break
    warmup_s = time.time() - tw
    print(f"first frame after {warmup_s:.0f}s ({warm_frames} render calls)", flush=True)

start_z = np.array([c.get_world_pose()[0][2] for c in cubes])
# A replay for DreamLake's viewer: the camera as a video and the scene's numbers as a table, on
# one clock (simulated seconds), in episodes/sim/. The .dreamrc written at the end lays them out.
episode = os.path.join(args.out, "episodes", "sim")
os.makedirs(episode, exist_ok=True)
FPS, PHYSICS_HZ = 15, 120
every = PHYSICS_HZ // FPS            # physics steps between samples
video, video_frames = None, 0
if camera is not None and args.video_seconds > 0:
    try:
        import imageio.v2 as imageio
        # H.264 in yuv420p plays in every browser; a keyframe each second keeps scrubbing quick.
        video = imageio.get_writer(os.path.join(episode, "camera.mp4"), fps=FPS, codec="libx264",
                                   pixelformat="yuv420p", macro_block_size=16,
                                   ffmpeg_params=["-g", str(FPS), "-movflags", "+faststart"])
    except Exception as e:
        print(f"no video: {e}", flush=True)
telemetry = open(os.path.join(episode, "telemetry.csv"), "w")
telemetry.write("timestamp,mean_height_m,max_height_m,mean_speed_mps,steps_per_s\n")
MAX_ROWS = 20000

steps, t0 = 0, time.time()
while time.time() - t0 < args.sim_seconds and app.is_running():
    world.step(render=render)
    steps += 1
    if steps % every == 0:
        sim_t = steps / PHYSICS_HZ
        if steps // every <= MAX_ROWS:
            z = np.array([c.get_world_pose()[0][2] for c in cubes])
            v = np.array([np.linalg.norm(c.get_linear_velocity()) for c in cubes])
            telemetry.write(f"{sim_t:.4f},{z.mean():.5f},{z.max():.5f},{v.mean():.5f},{steps / (time.time() - t0):.2f}\n")
        if video is not None and sim_t <= args.video_seconds:
            frame = frame_of(camera)
            if frame is not None:
                video.append_data(np.asarray(frame)[..., :3].astype("uint8"))
                video_frames += 1
    if steps % 1200 == 0:
        elapsed = time.time() - t0
        metrics.append({"step": steps, "values": {"steps_per_s": steps / elapsed, "wall_s": elapsed}})
        print(f"step {steps}  {steps / elapsed:.1f} steps/s  {elapsed:.0f}s", flush=True)
wall = time.time() - t0
telemetry.close()
if video is not None:
    video.close()
with open(os.path.join(args.out, ".dreamrc"), "w") as f:
    f.write(DREAMRC.format(fps=FPS, video=VIDEO_VIEW if video_frames else ""))
end_z = np.array([c.get_world_pose()[0][2] for c in cubes])

case("physics_settled", [
    {"name": "all cubes fell", "passed": bool((end_z < start_z - 0.5).all()), "observed": round(float((start_z - end_z).min()), 3), "expected": "> 0.5 m"},
    {"name": "none through ground", "passed": bool((end_z > 0.0).all()), "observed": round(float(end_z.min()), 3), "expected": "> 0"},
    {"name": "resting near ground", "passed": bool((end_z < size * 3).all()), "observed": round(float(end_z.max()), 3), "expected": f"< {size * 3}"},
])
case("throughput", [
    {"name": "stepped", "passed": steps > 0, "observed": steps, "expected": "> 0"},
    {"name": "simulated time", "passed": steps / 120 >= 2.0, "observed": round(steps / 120, 1), "expected": ">= 2 s sim"},
])

if camera is not None:
    frame = frame_of(camera)
    ok = frame is not None
    std = float(np.asarray(frame)[..., :3].std()) if ok else 0.0
    case("render", [
        {"name": "frame captured", "passed": bool(ok), "observed": list(np.asarray(frame).shape) if ok else f"no frame after {warmup_s:.0f}s warm-up", "expected": "[480, 640, 4]"},
        {"name": "frame not blank", "passed": std > 1.0, "observed": round(std, 2), "expected": "pixel std > 1"},
    ])
    if ok:
        try:
            from PIL import Image
            Image.fromarray(np.asarray(frame)[..., :3].astype("uint8")).save(os.path.join(args.out, "frame.png"))
            files.append("frame.png")
        except Exception:
            pass

passed = sum(c["passed"] for c in cases)
result = {
    "passed": passed == len(cases), "cases_passed": passed, "cases": cases,
    "summary": {"boot_s": round(boot_s, 1), "render_warmup_s": round(warmup_s, 1), "steps": steps, "wall_s": round(wall, 1),
                "steps_per_s": round(steps / wall, 1) if wall else 0, "render": render, "cubes": len(cubes)},
}
metrics.append({"step": steps, "values": {"steps_per_s": steps / wall if wall else 0, "wall_s": wall, "pass_rate": passed / len(cases)}})
print(json.dumps(result, indent=1), flush=True)
with open(os.path.join(args.out, "summary.json"), "w") as f:
    json.dump(result, f, indent=2)
# metrics.json: [{step, values}] points DreamLake charts on the run page.
with open(os.path.join(args.out, "metrics.json"), "w") as f:
    json.dump(metrics[-128:], f)
# SimulationApp.close() can end the process with its own status; the outputs are
# already on disk, so exit directly with the verdict.
os._exit(0 if passed == len(cases) else 1)
