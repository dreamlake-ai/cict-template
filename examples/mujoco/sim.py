"""MuJoCo example: a two-link arm tracks a target trajectory (PD control with gravity compensation).

Checks that the simulation stays finite and the arm tracks its target, writes
the headline numbers (metrics.json), a summary (summary.json) and a rendered
video (arm.mp4, headless through EGL on GPU machines) to --out.

Exit codes: 0 every check passed, 1 a check failed, 2 the run could not finish.
Swap in your own model and checks: everything DreamLake needs is the output
directory, which the workflow saves as evidence.
"""
import argparse
import json
import math
import os
import time

import mujoco
import numpy as np

ARM = """
<mujoco model="two-link arm">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <visual><global offwidth="640" offheight="480"/></visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1=".2 .3 .4" rgb2=".1 .15 .2" width="512" height="512"/>
    <material name="grid" texture="grid" texrepeat="8 8" reflectance=".2"/>
  </asset>
  <worldbody>
    <light pos="0 0 3" dir="0 0 -1"/>
    <geom type="plane" size="2 2 .1" material="grid"/>
    <camera name="side" pos="0 -2.2 1.2" xyaxes="1 0 0 0 .5 .87"/>
    <body name="upper" pos="0 0 1">
      <joint name="shoulder" type="hinge" axis="0 1 0" damping=".5"/>
      <geom type="capsule" fromto="0 0 0 .5 0 0" size=".04" rgba=".9 .5 .2 1"/>
      <body name="lower" pos=".5 0 0">
        <joint name="elbow" type="hinge" axis="0 1 0" damping=".5"/>
        <geom type="capsule" fromto="0 0 0 .4 0 0" size=".035" rgba=".2 .6 .9 1"/>
        <site name="tip" pos=".4 0 0" size=".03"/>
      </body>
    </body>
  </worldbody>
  <actuator>
    <motor joint="shoulder" gear="1" ctrlrange="-40 40" ctrllimited="true"/>
    <motor joint="elbow" gear="1" ctrlrange="-40 40" ctrllimited="true"/>
  </actuator>
</mujoco>
"""

parser = argparse.ArgumentParser()
parser.add_argument("--out", default="outputs")
parser.add_argument("--seconds", type=float, default=20.0, help="simulated seconds")
parser.add_argument("--render", default="true", help="render arm.mp4 (true/false)")
args = parser.parse_args()
render = str(args.render).lower() in ("1", "true", "yes")
os.makedirs(args.out, exist_ok=True)

model = mujoco.MjModel.from_xml_string(ARM)
data = mujoco.MjData(model)
kp, kd = np.array([120.0, 60.0]), np.array([12.0, 6.0])


def target(t):
    """Joint angles to track, and their velocities."""
    q = np.array([0.6 * math.sin(1.5 * t), 0.8 * math.sin(2.0 * t + 0.5)])
    qd = np.array([0.9 * math.cos(1.5 * t), 1.6 * math.cos(2.0 * t + 0.5)])
    return q, qd


renderer = None
frames, fps = [], 30
if render:
    try:
        renderer = mujoco.Renderer(model, height=480, width=640)
    except Exception as e:  # no GL on this machine: keep the physics, report the render
        print(f"rendering unavailable: {e}")

errors, per_second, steps = [], [], 0
next_frame, t0 = 0.0, time.time()
while data.time < args.seconds:
    q, qd = data.qpos[:2], data.qvel[:2]
    q_ref, qd_ref = target(data.time)
    # PD on position and velocity, plus gravity and Coriolis compensation (qfrc_bias).
    data.ctrl[:] = kp * (q_ref - q) + kd * (qd_ref - qd) + data.qfrc_bias[:2]
    mujoco.mj_step(model, data)
    steps += 1
    errors.append(float(np.abs(target(data.time)[0] - data.qpos[:2]).mean()))
    if renderer is not None and data.time >= next_frame:
        renderer.update_scene(data, camera="side")
        frames.append(renderer.render())
        next_frame += 1 / fps
    if steps % int(1 / model.opt.timestep) == 0:
        per_second.append({"step": int(round(data.time)), "values": {
            "tracking_error_rad": float(np.mean(errors[-int(1 / model.opt.timestep):]))}})
wall = time.time() - t0

finite = bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())
settled_error = float(np.mean(errors[len(errors) // 4:]))  # after the first quarter: start-up transient
checks = [
    {"name": "simulation stays finite", "passed": finite, "observed": finite, "expected": True},
    {"name": "tracks the target", "passed": settled_error < 0.05, "observed": round(settled_error, 4), "expected": "< 0.05 rad"},
]

files = []
if renderer is not None:
    try:
        import imageio.v2 as imageio

        imageio.mimsave(os.path.join(args.out, "arm.mp4"), frames, fps=fps, macro_block_size=1)
        files.append("arm.mp4")
        checks.append({"name": "rendered a video", "passed": len(frames) > fps, "observed": len(frames), "expected": f"> {fps} frames"})
    except Exception as e:
        checks.append({"name": "rendered a video", "passed": False, "observed": repr(e)[:200], "expected": "arm.mp4"})

passed = all(c["passed"] for c in checks)
summary = {
    "passed": passed, "checks": checks, "files": files,
    "simulated_s": round(data.time, 2), "steps": steps, "wall_s": round(wall, 2),
    "steps_per_s": round(steps / wall) if wall else None, "mujoco": mujoco.__version__,
}
print(json.dumps(summary, indent=2))
with open(os.path.join(args.out, "summary.json"), "w") as f:
    json.dump(summary, f, indent=2)
# metrics.json: [{step, values}] points DreamLake charts on the run page (at most 128 points of 16 numbers).
per_second.append({"step": int(round(data.time)), "values": {
    "settled_tracking_error_rad": settled_error, "steps_per_s": steps / wall if wall else 0}})
with open(os.path.join(args.out, "metrics.json"), "w") as f:
    json.dump(per_second[-128:], f)
raise SystemExit(0 if passed else 1)
