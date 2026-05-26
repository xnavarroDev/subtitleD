import subprocess
from pathlib import Path


class FFmpegError(RuntimeError):
    """Raised when an FFmpeg command exits unsuccessfully."""

    pass


def _run_ffmpeg(args):
    """Run FFmpeg with consistent safety and error handling."""
    # FFmpeg is invoked without a shell so uploaded filenames cannot become shell
    # syntax. stderr is preserved because FFmpeg diagnostics are the useful part.
    completed = subprocess.run(
        ["ffmpeg", "-y", *[str(arg) for arg in args]],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise FFmpegError(message[-4000:])
    return completed


def extract_audio(video_path, output_audio_path):
    """Extract mono 16 kHz WAV audio suitable for STT providers."""
    output = Path(output_audio_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            output,
        ]
    )
    return output


def _escape_subtitles_filter_path(path):
    """Escape a path for use inside FFmpeg's subtitles filter expression."""
    value = str(Path(path)).replace("\\", "/")
    return value.replace(":", "\\:").replace("'", "\\'")


def burn_subtitles(video_path, srt_path, output_video_path):
    """Burn an SRT subtitle file into a source video and write an MP4 render."""
    output = Path(output_video_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # The subtitles filter reads SRT directly. The path needs FFmpeg filter-level
    # escaping even though subprocess argument handling already avoids shell issues.
    subtitle_filter = f"subtitles='{_escape_subtitles_filter_path(srt_path)}'"
    _run_ffmpeg(
        [
            "-i",
            video_path,
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output,
        ]
    )
    return output
