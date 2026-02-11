import xml.etree.ElementTree as ET
import subprocess
from ansitable import ANSITable, Column
import os
import json

# Configuration - Ensure these match the files from LosslessCut

OUTPUT = "camancipated_video.mp4"
SCREEN = "Rec 10-15-21 1-stream-0-video-tscc2.mkv"
CAM = "Rec 10-15-21 1-stream-1-video-h264.mp4"
AUDIO = "Rec 10-15-21 1-stream-2-audio-aac.aac"
XML = "project.xml"

FPS = 30


def get_video_size(filename):
    """Detect resolution using ffprobe for dynamic PiP placement."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", filename]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    for stream in data["streams"]:
        if stream["codec_type"] == "video":
            return int(stream["width"]), int(stream["height"])
    return 3840, 2160  # Default to 4K


def parse_hierarchical_edits(xml_file):
    """Recursive parser for GenericTrack -> StitchedMedia -> Clips."""
    tree = ET.parse(xml_file)
    root = tree.getroot()
    all_edits = []

    # Traverse Tracks
    for track in root.findall(".//GenericTrack"):
        for media in track.findall(".//Medias/*"):

            # Handle Nested 'Stitched' Groups
            if media.tag == "StitchedMedia":
                container_start = int(media.get("start", 0))
                for sub in media.findall(".//Medias/*"):
                    # Calculate Global Timeline Position: Parent + Local Offset
                    global_t_start = int(sub.get("start", 0)) + container_start
                    m_start = int(sub.get("mediaStart", "0/1").split("/")[0])
                    dur = int(sub.get("mediaDuration", "0/1").split("/")[0])
                    all_edits.append(
                        {"t_start": global_t_start, "m_start": m_start, "dur": dur}
                    )

            # Handle Standalone Timeline Clips
            else:
                t_start = int(media.get("start", 0))
                m_start = int(media.get("mediaStart", "0/1").split("/")[0])
                dur = int(media.get("mediaDuration", "0/1").split("/")[0])
                if dur > 0:
                    all_edits.append(
                        {"t_start": t_start, "m_start": m_start, "dur": dur}
                    )

    # Deduplicate: Grouping by (Timeline Start, Duration) removes redundant audio/video entries
    unique_map = {}
    for e in sorted(all_edits, key=lambda x: x["t_start"]):
        key = (e["t_start"], e["dur"])
        if key not in unique_map:
            unique_map[key] = e

    return sorted(unique_map.values(), key=lambda x: x["t_start"])


def run_recovery():
    sw, sh = get_video_size(SCREEN)
    pip_w = 720
    edits = parse_hierarchical_edits(XML)

    print(f"🚀 Starting Camancipation of {len(edits)} segments...")

    with open("list.txt", "w") as f_list:
        for i, e in enumerate(edits):
            start_t = e["m_start"] / FPS
            dur_t = e["dur"] / FPS
            out = f"part_{i:03d}.ts"

            # Filter: 1. Scale 5K -> 4K for M4 encoder. 2. Fix 1fps stutter with fps=30. 3. PiP Overlay
            filter_str = (
                f"[0:v]scale=3840:2160,fps={FPS},setsar=1[main]; "
                f"[1:v]scale={pip_w}:-1,fps={FPS},setsar=1[pip]; "
                f"[main][pip]overlay=main_w-overlay_w-50:main_h-overlay_h-50"
            )

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(start_t),
                "-t",
                str(dur_t),
                "-i",
                SCREEN,
                "-ss",
                str(start_t),
                "-t",
                str(dur_t),
                "-i",
                CAM,
                "-ss",
                str(start_t),
                "-t",
                str(dur_t),
                "-i",
                AUDIO,
                "-filter_complex",
                filter_str,
                "-c:v",
                "h264_videotoolbox",
                "-b:v",
                "15M",
                "-c:a",
                "aac",
                "-ar",
                "44100",
                out,
            ]

            subprocess.run(cmd)
            f_list.write(f"file '{out}'\n")

    # Concatenate final output
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-i", "list.txt", "-c", "copy", OUTPUT]
    )

    # Cleanup temp files
    for f in os.listdir("."):
        if f.endswith(".ts"):
            os.remove(f)
    os.remove("list.txt")
    print(f"✅ Recovery Complete: {OUTPUT}")


if __name__ == "__main__":
    run_recovery()
