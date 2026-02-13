#! /usr/bin/env python3

import xml.etree.ElementTree as ET
import subprocess
from ansitable import ANSITable, Column
import json
import argparse
import sys
import time
from pathlib import Path

# Configuration - Ensure these match the files from LosslessCut

OUTPUT = "camancipated_video.mp4"
SCREEN = "Rec 10-15-21 1-stream-0-video-tscc2.mkv"
CAM = "Rec 10-15-21 1-stream-1-video-h264.mp4"
AUDIO = "Rec 10-15-21 1-stream-2-audio-aac.aac"
XML = "project.xml"

FPS = 30


def find_default_file(extension, folder="."):
    """Find a default file with the given extension in the specified folder.

    Returns the filename if exactly one file with that extension exists.
    Returns None if no files exist.
    Raises an error if multiple files exist.
    """
    folder_path = Path(folder)
    files = [
        f.name for f in folder_path.iterdir() if f.is_file() and f.suffix == extension
    ]

    if len(files) == 0:
        return None
    elif len(files) == 1:
        return str(folder_path / files[0])
    else:
        return None
        # raise ValueError(
        #     f"Found multiple files with extension '{extension}': {', '.join(files)}. "
        #     f"Please specify one explicitly."
        # )


def check_overwrite(filename):
    """Check if file exists and prompt user to overwrite it.

    If file exists, prompts the user for confirmation.
    Returns True if user confirms overwrite, False otherwise.
    """
    if Path(filename).exists():
        response = (
            input(f"File '{filename}' already exists. Overwrite? (y/n): ")
            .strip()
            .lower()
        )
        if response != "y":
            print("Aborted.")
            sys.exit(0)
    return True


def cleanup_slice_files():
    """Find and remove all slice_NNN.ts files and concat_list.txt in the current directory."""
    current_dir = Path(".")
    slice_files = list(current_dir.glob("slice_*.ts"))

    if slice_files:
        print(f"Cleaning up {len(slice_files)} slice files...")
        for file in slice_files:
            try:
                file.unlink()
            except Exception as e:
                print(f"Warning: Could not delete {file}: {e}")

    # Also remove concat_list.txt if it exists
    concat_list = Path("concat_list.txt")
    if concat_list.exists():
        try:
            concat_list.unlink()
        except Exception as e:
            print(f"Warning: Could not delete concat_list.txt: {e}")


def show_segments(segs):
    table = ANSITable("timelineStart", "In point", "Out point", "duration", "type")

    def mmss(f):
        seconds = round(int(f) / 30)
        minutes = seconds // 60
        seconds -= minutes * 60
        return f"{minutes:02d}:{seconds:02d}"

    duration = 0
    for seg in segs:
        table.row(
            mmss(seg["timelineStart"]),
            mmss(seg["mediaStart"]),
            mmss(seg["mediaStart"] + seg["duration"]),
            mmss(seg["duration"]),
            seg["type"],
        )
        duration += seg["duration"]
    table.print()
    print(f"Total duration: {mmss(duration)}")


def get_available_encoders():
    """Get list of available video encoders from ffmpeg."""
    try:
        cmd = ["ffmpeg", "-codecs", "-hide_banner"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        encoders = []

        # Look for H.264 encoders
        h264_encoders = {
            "h264_videotoolbox": "Apple Hardware (macOS/iOS)",
            "h264_nvenc": "NVIDIA GPU",
            "h264_amf": "AMD GPU",
            "libx264": "Software (portable)",
        }

        for encoder, description in h264_encoders.items():
            if f" {encoder} " in result.stdout:
                encoders.append((encoder, description))

        return encoders
    except Exception:
        return []


def select_encoder():
    """Auto-detect and select the best available encoder."""
    available = get_available_encoders()

    if not available:
        # Fallback to libx264 if nothing found
        return "libx264"

    # Prefer hardware encoders in this order
    preference_order = ["h264_videotoolbox", "h264_nvenc", "h264_amf", "libx264"]
    for preferred in preference_order:
        for encoder, _ in available:
            if encoder == preferred:
                return encoder

    # Return first available if preference not found
    return available[0][0]


def get_video_size(filename):
    """Detect resolution using ffprobe for dynamic PiP placement."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", filename]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    for stream in data["streams"]:
        if stream["codec_type"] == "video":
            return int(stream["width"]), int(stream["height"])
    return 3840, 2160  # Default to 4K


def get_video_duration(filename):
    """Get video duration in seconds using ffprobe."""
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", filename]
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    if "format" in data and "duration" in data["format"]:
        return float(data["format"]["duration"])
    return 0.0


def parse_fraction(value):
    """Parse values like '1032/1' to integer."""
    if value and "/" in value:
        return int(value.split("/")[0])
    return int(value) if value else 0


def extract_segments(xml_file):
    """
    Parse Camtasia project XML and extract the timeline segments.
    Returns a list of segments, each with mediaStart and duration in frames.

    Key insight: StitchedMedia elements already describe the final segment.
    The nested elements inside show the composition but shouldn't be extracted separately.
    """
    tree = ET.parse(xml_file)
    root = tree.getroot()

    segments = []

    # Find only top-level GenericTrack elements (direct children of Timeline/GenericMixer/Tracks)
    for track in root.findall(".//Timeline/GenericMixer/Tracks/GenericTrack"):
        medias = track.find("Medias")
        if medias is None:
            continue

        # Process only top-level media elements
        for media in medias:
            if media.tag == "StitchedMedia":
                # The StitchedMedia itself describes the segment
                timeline_start = parse_fraction(media.get("start", "0"))
                media_start = parse_fraction(media.get("mediaStart", "0"))
                media_duration = parse_fraction(media.get("mediaDuration", "0"))
                segments.append(
                    {
                        "type": "StitchedMedia",
                        "timelineStart": timeline_start,
                        "mediaStart": media_start,
                        "duration": media_duration,
                    }
                )

            elif media.tag == "ScreenVMFile":
                # Direct clip on timeline
                timeline_start = parse_fraction(media.get("start", "0"))
                media_start = parse_fraction(media.get("mediaStart", "0"))
                media_duration = parse_fraction(media.get("mediaDuration", "0"))
                segments.append(
                    {
                        "type": "ScreenVMFile",
                        "timelineStart": timeline_start,
                        "mediaStart": media_start,
                        "duration": media_duration,
                    }
                )

    # Remove duplicates (ScreenVMFile and AMFile are parallel audio/video tracks)
    unique_segments = []
    seen = set()
    for seg in segments:
        key = (seg["mediaStart"], seg["duration"])
        if key not in seen:
            seen.add(key)
            unique_segments.append(
                {
                    "mediaStart": seg["mediaStart"],
                    "duration": seg["duration"],
                    "type": seg["type"],
                    "timelineStart": seg["timelineStart"],
                }
            )

    return unique_segments


def reconstruct(segments, quiet=False, restart=False, encoder=None):

    if restart is False:
        # cut out the segments
        with open("concat_list.txt", "w") as f_list:
            for i, s in enumerate(segments):
                out = f"slice_{i:03d}.ts"
                print(f"🎬 Extracting segment {i+1}/{len(segments)} --> {out}")

                start_sec = s["mediaStart"] / FPS
                dur_sec = s["duration"] / FPS

                # ffmpeg command to 'window' the media accurately
                filter_complex = (
                    f"[0:v]scale=3840:2160,fps={FPS}[v0]; "
                    f"[1:v]scale=720:-1,fps={FPS}[v1]; "
                    f"[v0][v1]overlay=main_w-overlay_w-50:main_h-overlay_h-50"
                )

                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(start_sec),
                    "-t",
                    str(dur_sec),
                    "-i",
                    SCREEN,
                    "-ss",
                    str(start_sec),
                    "-t",
                    str(dur_sec),
                    "-i",
                    CAM,
                    "-ss",
                    str(start_sec),
                    "-t",
                    str(dur_sec),
                    "-i",
                    AUDIO,
                    "-filter_complex",
                    filter_complex,
                    "-c:v",
                    encoder or "h264_videotoolbox",
                    "-b:v",
                    "15M",
                    "-c:a",
                    "aac",
                    out,
                ]
                if quiet:
                    cmd.extend(["-loglevel", "error", "-hide_banner"])
                subprocess.run(cmd)
                f_list.write(f"file '{out}'\n")

    # Final butt-joint concatenation
    concat_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-i",
        "concat_list.txt",
        "-c",
        "copy",
        OUTPUT,
    ]
    if quiet:
        concat_cmd.extend(["-loglevel", "error", "-hide_banner"])
    print(f"🎬 Final concatenation --> {OUTPUT}")
    subprocess.run(concat_cmd)


def parse_arguments():
    """Parse and validate command-line arguments."""
    # First, parse just the folder argument to determine where to look for defaults
    folder_parser = argparse.ArgumentParser(add_help=False)
    folder_parser.add_argument("-f", "--folder", default=".")
    folder_args, remaining = folder_parser.parse_known_args()

    # Find default files in the specified folder
    default_screen = find_default_file(".mkv", folder_args.folder)
    default_webcam = find_default_file(".mp4", folder_args.folder)
    default_audio = find_default_file(".aac", folder_args.folder)
    default_xml = find_default_file(".xml", folder_args.folder)

    # Create main parser with computed defaults
    parser = argparse.ArgumentParser(
        description="Reconstruct video from Camtasia project with screen and webcam overlay."
    )
    parser.add_argument(
        "-f",
        "--folder",
        help="Folder containing the media files (default: current folder)",
        default=".",
    )
    parser.add_argument(
        "-s",
        "--screen",
        help="Screen recording filename (.mkv)",
        default=default_screen,
    )
    parser.add_argument(
        "-w",
        "--webcam",
        help="Webcam recording filename (.mp4)",
        default=default_webcam,
    )
    parser.add_argument(
        "-a", "--audio", help="Audio filename (.aac)", default=default_audio
    )
    parser.add_argument(
        "-x",
        "--xml",
        help="Camtasia project XML filename (.xml)",
        default=default_xml,
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output video filename (default: camancipated_video.mp4)",
        default="camancipated_video.mp4",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        help="Suppress ffmpeg output (only show errors)",
        action="store_true",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        help="Show what would be done without executing",
        action="store_true",
    )
    parser.add_argument(
        "-r",
        "--restart",
        help="Restart using existing slice files (skip segment generation)",
        action="store_true",
    )
    parser.add_argument(
        "-e",
        "--encoder",
        help="Video encoder (auto-detect if not specified)",
        default=None,
    )

    return parser.parse_args()


if __name__ == "__main__":
    # Parse command-line arguments
    args = parse_arguments()

    # Record start time
    start_time = time.time()

    # Check if output file already exists
    check_overwrite(args.output)

    # Update the global variables with parsed arguments
    SCREEN = args.screen
    CAM = args.webcam
    AUDIO = args.audio
    XML = args.xml
    OUTPUT = args.output

    print("Screen video size:", "x".join(map(str, get_video_size(SCREEN))))
    print("Webcam video size:", "x".join(map(str, get_video_size(CAM))))

    # Get and display screen video duration
    screen_duration = get_video_duration(SCREEN)
    minutes, seconds = divmod(int(screen_duration), 60)
    print(f"Video runtime: {minutes:02d}:{seconds:02d}")

    # Parse the XML and extract segments
    segments = extract_segments("project.xml")

    # ----------- Display results
    print(f"Total segments: {len(segments)}")
    print()

    show_segments(segments)

    # ----------- Determine encoder
    if args.encoder:
        encoder = args.encoder
        print(f"Using encoder: {encoder}")
    else:
        encoder = select_encoder()
        available = get_available_encoders()
        if available:
            print(f"Auto-detected encoder: {encoder}")
        else:
            print(f"No encoders found, using fallback: {encoder}")

    # ----------- build the final video
    if not args.dry_run:
        print()
        reconstruct(segments, quiet=args.quiet, restart=args.restart, encoder=encoder)

        # Clean up all temporary slice files
        cleanup_slice_files()

        # Calculate and display elapsed time
        elapsed = time.time() - start_time
        hours, remainder = divmod(int(elapsed), 3600)
        minutes, seconds = divmod(remainder, 60)
        print(f"\nCompleted in {hours:02d}:{minutes:02d}:{seconds:02d}")
