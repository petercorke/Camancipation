# Camancipation 🔓

<img src="images/camancipation.png" width="400">

**Camancipation** is a minimalist recovery tool for freeing legacy TechSmith Camtasia (`.trec`) recordings. Designed for Mac power users who prefer `vi` over GUIs and `ffmpeg` over bloat.

## The Problem
Old `.trec` files are proprietary black boxes. If your software version doesn't match, or the file index is "incomplete," your footage is effectively held hostage.

## The Solution
Camancipation uses your `project.xml` as a surgical map to carve out segments from raw media streams and restitch them into a modern, open-standard MP4—complete with Picture-in-Picture webcam overlays.

---

## 🛠 Prerequisites

- **macOS Tahoe** (Optimized for Apple Silicon M4)
- **Python 3.x**
- **FFmpeg** (with `h264_videotoolbox` support)
- **LosslessCut** (for initial stream extraction)

`ffmpeg` apparantly uses some funky hardware on the M4 but 
---

## 🚀 Workflow

### 1. Extraction
Open your `.trec` file in **LosslessCut**. Extract the following streams:
- `extracted_screen.mkv` (The primary screen recording)  `stream-0`, might be a `.mkv` file
- `extracted_webcam.mp4` (The webcam inset), `stream-1`, might be a `.mp4` file
- `extracted_audio.wav` (The master audio), `stream-2`, might be a `.aac` file

### 2. The Map
Locate the `project.xml` file within your Camtasia project folder.

### 3. Execution
Run the provided Python script to parse the XML and automate the `ffmpeg` filtergraph:

```bash
python3 camancipation.py