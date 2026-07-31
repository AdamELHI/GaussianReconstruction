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
- With multiple videos, COLMAP uses exhaustive matching so that frames from
  different videos can be connected.
- **Force exhaustive matching** can be enabled in the settings to use exhaustive
  matching with a single video.

Exhaustive matching is slower because it compares every image pair. To reduce
false connections between videos, it also uses stricter geometric verification:
at least 50 geometrically consistent matches, a minimum inlier ratio of 30%, and
a maximum geometric error of 2 pixels.

## Settings

- **Frame rate** controls the number of frames extracted per second. Increase it when the camera moves quickly so that the reconstruction captures enough intermediate viewpoints.
- **Start time / End time** define the portion of each selected video to
  process. After selecting the videos, open the settings: a separate row is
  displayed for every video, with its own start and end fields. Use the
  `HH:MM:SS` format; leave the start empty to begin at the first frame and the
  end empty to continue until the end of that video.
- **Use GPU** speeds up processing when a compatible GPU and the required drivers are available.
- **Force exhaustive matching** compares every extracted image pair, even when only one video is selected. It can improve connections between non-consecutive viewpoints but increases processing time.
- **Skip alignment** disables the final PCA alignment. Use this option only when PCA alignment distorts the reconstructed scene because of a geometric bias.
- **Keep temporary files** preserves the intermediate COLMAP and Brush working
  files after reconstruction. Each run uses a separate
  `LastReconstruction/reconstruction-*` directory so concurrent application
  instances cannot overwrite each other's working files.
- **Open the COLMAP model in its GUI** opens the sparse camera reconstruction for inspection before Brush training.

## Building the application

See [Software/build.md](Software/build.md) for the Windows and Linux standalone
build instructions.
