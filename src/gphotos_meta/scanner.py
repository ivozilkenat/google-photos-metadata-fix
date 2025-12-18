"""Directory scanning and file matching for Google Photos Takeout exports."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


# Patterns for JSON metadata files (Google truncates names in various ways)
JSON_PATTERNS = [
    r"\.supplemental-metadata\.json$",
    r"\.supplemental-metada\.json$",  # Truncated version
    r"\.supplemental-met\.json$",     # More truncated
    r"\.su\.json$",                   # Very truncated
]

# Media file extensions we support
MEDIA_EXTENSIONS = {
    # Images
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tiff", ".tif",
    # Videos
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".3gp", ".m4v",
}

# Files to skip (album metadata, not per-image metadata)
SKIP_FILES = {"Metadaten.json", "metadata.json"}


@dataclass
class MediaFilePair:
    """A media file paired with its JSON metadata file."""
    media_path: Path
    json_path: Path
    
    @property
    def media_name(self) -> str:
        return self.media_path.name
    
    @property
    def relative_dir(self) -> str:
        return str(self.media_path.parent)


@dataclass
class ScanResult:
    """Results from scanning a directory for media/metadata pairs."""
    pairs: list[MediaFilePair] = field(default_factory=list)
    orphan_jsons: list[Path] = field(default_factory=list)  # JSON files without matching media
    orphan_media: list[Path] = field(default_factory=list)  # Media files without matching JSON
    skipped_jsons: list[Path] = field(default_factory=list)  # Album metadata files
    errors: list[tuple[Path, str]] = field(default_factory=list)  # Files that caused errors
    
    @property
    def total_pairs(self) -> int:
        return len(self.pairs)
    
    @property
    def total_orphan_jsons(self) -> int:
        return len(self.orphan_jsons)
    
    @property
    def total_orphan_media(self) -> int:
        return len(self.orphan_media)
    
    def merge(self, other: "ScanResult") -> None:
        """Merge another scan result into this one."""
        self.pairs.extend(other.pairs)
        self.orphan_jsons.extend(other.orphan_jsons)
        self.orphan_media.extend(other.orphan_media)
        self.skipped_jsons.extend(other.skipped_jsons)
        self.errors.extend(other.errors)


def is_metadata_json(filename: str) -> bool:
    """Check if a filename matches the Google Photos metadata JSON pattern."""
    if filename in SKIP_FILES:
        return False
    return any(re.search(pattern, filename, re.IGNORECASE) for pattern in JSON_PATTERNS)


def get_media_filename_from_json(json_filename: str) -> str | None:
    """Extract the media filename from a metadata JSON filename.
    
    Examples:
        - "photo.jpg.supplemental-metadata.json" -> "photo.jpg"
        - "video.mp4.supplemental-met.json" -> "video.mp4"
        - "image.png.su.json" -> "image.png"
    """
    for pattern in JSON_PATTERNS:
        match = re.search(pattern, json_filename, re.IGNORECASE)
        if match:
            return json_filename[:match.start()]
    return None


def is_media_file(filename: str) -> bool:
    """Check if a filename is a supported media file."""
    ext = Path(filename).suffix.lower()
    return ext in MEDIA_EXTENSIONS


def scan_directory(directory: Path, recursive: bool = False) -> ScanResult:
    """Scan a directory for media files and their metadata JSON files.
    
    Args:
        directory: Path to the directory to scan
        recursive: If True, scan subdirectories recursively
        
    Returns:
        ScanResult containing matched pairs and orphaned files
    """
    result = ScanResult()
    
    if not directory.exists():
        result.errors.append((directory, "Directory does not exist"))
        return result
    
    if not directory.is_dir():
        result.errors.append((directory, "Path is not a directory"))
        return result
    
    # Get iterator based on recursive flag
    if recursive:
        entries = list(directory.rglob("*"))
    else:
        entries = list(directory.iterdir())
    
    # Separate files by type
    json_files: dict[Path, Path] = {}  # media_path -> json_path
    media_files: set[Path] = set()
    
    for entry in entries:
        if not entry.is_file():
            continue
            
        filename = entry.name
        
        # Check for album metadata files to skip
        if filename in SKIP_FILES:
            result.skipped_jsons.append(entry)
            continue
        
        # Check if it's a metadata JSON
        if is_metadata_json(filename):
            media_name = get_media_filename_from_json(filename)
            if media_name:
                # The media file should be in the same directory as the JSON
                media_path = entry.parent / media_name
                json_files[media_path] = entry
            continue
        
        # Check if it's a media file
        if is_media_file(filename):
            media_files.add(entry)
    
    # Match media files with their JSON metadata
    matched_media: set[Path] = set()
    
    for media_path, json_path in json_files.items():
        if media_path in media_files:
            result.pairs.append(MediaFilePair(media_path, json_path))
            matched_media.add(media_path)
        else:
            # JSON exists but media file doesn't
            result.orphan_jsons.append(json_path)
    
    # Find media files without JSON
    for media_path in media_files:
        if media_path not in matched_media:
            result.orphan_media.append(media_path)
    
    return result


def get_directory_stats(result: ScanResult) -> dict[str, int]:
    """Get statistics about a scan result."""
    # Count by file extension
    ext_counts: dict[str, int] = {}
    for pair in result.pairs:
        ext = pair.media_path.suffix.lower()
        ext_counts[ext] = ext_counts.get(ext, 0) + 1
    
    # Count by directory
    dir_counts: dict[str, int] = {}
    for pair in result.pairs:
        dir_name = pair.media_path.parent.name
        dir_counts[dir_name] = dir_counts.get(dir_name, 0) + 1
    
    return {
        "total_pairs": result.total_pairs,
        "total_orphan_jsons": result.total_orphan_jsons,
        "total_orphan_media": result.total_orphan_media,
        "total_skipped": len(result.skipped_jsons),
        "extensions": ext_counts,
        "directories": dir_counts,
    }

