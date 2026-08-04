# GaussianReconstruction

## Overview

This tool creates a 3D reconstruction from one or more video files. Supported
input formats include MP4, AVI, MOV, MKV, and WebM.

The reconstruction is not generative: it cannot create viewpoints that are not
visible in any of the frames extracted from the selected videos.

The tool also requires sufficient parallax to produce good results:

- Do not simply stand in one place and turn the camera around. For example, to reconstruct a room, move the camera around the center of the room while keeping it pointed towards the scene.
- When following an out-and-back path, avoid turning around in place at the start of the return leg. Instead, make a wide turn so that the camera continues to move around the scene and captures sufficient parallax.
- Avoid moving only in a straight line. For example, when reconstructing a narrow corridor, move the camera from side to side between the two walls.

If possible, avoid drastic changes in focus or framing while recording. For example, switching between a close-up and a wide shot can make reconstruction more difficult.

## Video selection and matching

The video selection dialog accepts one or more files. Every selected path is
displayed under the **Video** label in the main menu.

All selected videos are processed as one reconstruction:

1. Frames are extracted into the same image dataset, with one numbered
   subdirectory per video (`video_001`, `video_002`, and so on).
2. COLMAP feature extraction runs once on the complete dataset.
3. Matching and mapping also run once on all extracted frames.

COLMAP creates one camera calibration per video directory. This allows videos
recorded with different devices, resolutions, or orientations to be processed
together without forcing them to share the same optical parameters.

The matching strategy is selected automatically:

- With one video, COLMAP uses sequential matching by default. This is faster and
  compares frames that are close to each other in the video.
- With multiple videos, the application first matches neighboring frames only
  within each video. It then compares every cross-video combination among up to
  120 sharp, temporally distributed anchors per video. This bounded exhaustive
  pass uses the existing SIFT descriptors and requires no Vocabulary Tree or
  additional image index. Anchor pairs require at least 100 geometrically
  consistent matches, a 45% inlier ratio, and at most 1.5 pixels of geometric
  error. Every anchor pair passing this geometric verification is retained for
  mapping; no additional group-level filter removes isolated valid pairs.
- After mapping, the application reports registered-image counts per video and
  warns when COLMAP creates disconnected sparse models. Brush trains on the
  largest sparse model; images belonging only to the other models are excluded
  from the exported reconstruction.
- **Force exhaustive matching** bypasses this strategy and compares every image
  pair. It is slower and is mainly useful for diagnostics or small datasets.

## Settings

- **Frame rate** is configured independently for each selected video and is
  **Automatic** by default: frames are selected from useful
  camera motion and relative sharpness. Automatic selection requires a
  displacement proportional to the image width and normally prefers the
  sharpest half of the recent video segment. To preserve feature-tracking
  continuity, it keeps the best available bridge frame before the viewpoint
  displacement becomes too large. Entering a numerical value for one video
  switches only that video to temporal sampling: it is divided into matching
  time windows and the sharpest usefully moved frame is kept in each window.
  Windows containing only stationary near-duplicates are rejected.
- **Start time / End time** define the portion of each selected video to
  process. After selecting the videos, open the settings: a separate row is
  displayed for every video, with its own FPS, start, and end fields. Use the
  `HH:MM:SS` format; leave the start empty to begin at the first frame and the
  end empty to continue until the end of that video.
- **Use GPU** speeds up processing when a compatible GPU and the required drivers are available.
- **Force exhaustive matching** compares every extracted image pair, even when only one video is selected. It can improve connections between non-consecutive viewpoints but increases processing time.
- **Keep temporary files** preserves the intermediate COLMAP and Brush working
  files after reconstruction. Each run uses a separate
  `LastReconstruction/reconstruction-*` directory so concurrent application
  instances cannot overwrite each other's working files.
- **Open the COLMAP model in its GUI** opens the sparse camera reconstruction for inspection before Brush training.

## Building the application

See [Software/build.md](Software/build.md) for the Windows and Linux standalone
build instructions.
