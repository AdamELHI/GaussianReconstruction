# GaussianReconstruction

## Overview

This tool creates a 3D reconstruction from an MP4 video.

The reconstruction is not generative: it cannot create viewpoints that are not visible in any of the frames extracted from the video.

The tool also requires sufficient parallax to produce good results:

- Do not simply stand in one place and turn the camera around. For example, to reconstruct a room, move the camera around the center of the room while keeping it pointed towards the scene.
- When following an out-and-back path, avoid turning around in place at the start of the return leg. Instead, make a wide turn so that the camera continues to move around the scene and captures sufficient parallax.
- Avoid moving only in a straight line. For example, when reconstructing a narrow corridor, move the camera from side to side between the two walls.

If possible, avoid drastic changes in focus or framing while recording. For example, switching between a close-up and a wide shot can make reconstruction more difficult.

## Settings

- **Frame rate** controls the number of frames extracted per second. Increase it when the camera moves quickly so that the reconstruction captures enough intermediate viewpoints.
- **Start time / End time** define the portion of the video to process. Use the `HH:MM:SS` format; for example, `00:00:15` starts at 15 seconds and `00:15:00` starts at 15 minutes.
- **Use GPU** speeds up processing when a compatible GPU and the required drivers are available.
- **Skip alignment** disables the final PCA alignment. Use this option only when PCA alignment distorts the reconstructed scene because of a geometric bias.
- **Keep temporary files** preserves the intermediate COLMAP and Brush working files after reconstruction.

## Building the application

See [Software/build.md](Software/build.md) for the Windows and Linux standalone
build instructions.
