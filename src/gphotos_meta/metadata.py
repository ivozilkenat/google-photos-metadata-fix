"""Metadata parsing and ExifTool operations for Google Photos Takeout."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import exiftool


@dataclass
class GoogleMetadata:
    """Parsed metadata from a Google Photos JSON file."""
    title: str | None = None
    description: str | None = None
    photo_taken_time: datetime | None = None
    creation_time: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    favorited: bool = False
    
    @property
    def has_gps(self) -> bool:
        """Check if GPS coordinates are present and valid."""
        return (
            self.latitude is not None 
            and self.longitude is not None
            and (self.latitude != 0.0 or self.longitude != 0.0)
        )
    
    @property
    def has_date(self) -> bool:
        """Check if photo taken time is present."""
        return self.photo_taken_time is not None


@dataclass
class VerificationResult:
    """Result of verifying metadata was written correctly."""
    success: bool
    date_match: bool = False
    gps_match: bool = False
    description_match: bool = False
    message: str = ""


def parse_google_json(json_path: Path) -> GoogleMetadata | None:
    """Parse a Google Photos metadata JSON file.
    
    Args:
        json_path: Path to the JSON file
        
    Returns:
        GoogleMetadata object or None if parsing fails
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return None
    
    metadata = GoogleMetadata()
    
    # Title
    metadata.title = data.get("title")
    
    # Description
    desc = data.get("description", "")
    if desc and desc.strip():
        metadata.description = desc.strip()
    
    # Photo taken time (Unix timestamp)
    photo_time = data.get("photoTakenTime", {})
    if "timestamp" in photo_time:
        try:
            ts = int(photo_time["timestamp"])
            metadata.photo_taken_time = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            pass
    
    # Creation time (fallback)
    creation_time = data.get("creationTime", {})
    if "timestamp" in creation_time:
        try:
            ts = int(creation_time["timestamp"])
            metadata.creation_time = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            pass
    
    # GPS data
    geo_data = data.get("geoData", {})
    lat = geo_data.get("latitude")
    lon = geo_data.get("longitude")
    alt = geo_data.get("altitude")
    
    if lat is not None and lon is not None:
        # Only set if not both zero (Google uses 0,0 for "no location")
        if lat != 0.0 or lon != 0.0:
            metadata.latitude = float(lat)
            metadata.longitude = float(lon)
            if alt is not None and alt != 0.0:
                metadata.altitude = float(alt)
    
    # Favorited
    metadata.favorited = data.get("favorited", False)
    
    return metadata


def check_exiftool_available() -> tuple[bool, str]:
    """Check if ExifTool is available on the system.
    
    Returns:
        Tuple of (available, message)
    """
    # Check if exiftool is in PATH
    exiftool_path = shutil.which("exiftool")
    if exiftool_path:
        try:
            result = subprocess.run(
                ["exiftool", "-ver"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                return True, f"ExifTool version {version} found at {exiftool_path}"
        except Exception:
            pass
    
    return False, (
        "ExifTool not found. Please install it:\n"
        "  Windows: Download from https://exiftool.org/ and add to PATH\n"
        "  macOS: brew install exiftool\n"
        "  Linux: sudo apt install libimage-exiftool-perl"
    )


def write_metadata_to_file(
    media_path: Path,
    metadata: GoogleMetadata,
    et: exiftool.ExifToolHelper
) -> tuple[bool, str]:
    """Write metadata to a media file using ExifTool.
    
    Args:
        media_path: Path to the media file
        metadata: GoogleMetadata to write
        et: ExifTool helper instance
        
    Returns:
        Tuple of (success, message)
    """
    if not media_path.exists():
        return False, f"File not found: {media_path}"
    
    # Build parameters for ExifTool
    params: dict[str, Any] = {}
    
    # Date/time
    if metadata.photo_taken_time:
        # Format: "YYYY:MM:DD HH:MM:SS"
        dt_str = metadata.photo_taken_time.strftime("%Y:%m:%d %H:%M:%S")
        params["DateTimeOriginal"] = dt_str
        params["CreateDate"] = dt_str
        params["ModifyDate"] = dt_str
        # Also set subsec times to match
        params["SubSecTimeOriginal"] = "00"
        params["SubSecCreateDate"] = "00"
        params["SubSecModifyDate"] = "00"
    
    # GPS coordinates
    if metadata.has_gps:
        # ExifTool handles the conversion to proper EXIF format
        params["GPSLatitude"] = metadata.latitude
        params["GPSLongitude"] = metadata.longitude
        params["GPSLatitudeRef"] = "N" if metadata.latitude >= 0 else "S"
        params["GPSLongitudeRef"] = "E" if metadata.longitude >= 0 else "W"
        
        if metadata.altitude is not None:
            params["GPSAltitude"] = abs(metadata.altitude)
            params["GPSAltitudeRef"] = 0 if metadata.altitude >= 0 else 1
    
    # Description
    if metadata.description:
        params["ImageDescription"] = metadata.description
        params["XMP:Description"] = metadata.description
        # Also set IPTC caption
        params["IPTC:Caption-Abstract"] = metadata.description
    
    if not params:
        return True, "No metadata to write"
    
    try:
        # Use set_tags to write metadata
        et.set_tags(str(media_path), params, params=["-overwrite_original"])
        return True, f"Wrote {len(params)} metadata fields"
    except Exception as e:
        return False, f"ExifTool error: {e}"


def read_metadata_from_file(
    media_path: Path,
    et: exiftool.ExifToolHelper
) -> dict[str, Any] | None:
    """Read metadata from a media file using ExifTool.
    
    Args:
        media_path: Path to the media file
        et: ExifTool helper instance
        
    Returns:
        Dictionary of metadata or None if reading fails
    """
    try:
        metadata_list = et.get_metadata(str(media_path))
        if metadata_list:
            return metadata_list[0]
        return None
    except Exception:
        return None


def verify_metadata(
    media_path: Path,
    expected: GoogleMetadata,
    et: exiftool.ExifToolHelper
) -> VerificationResult:
    """Verify that metadata was written correctly to a file.
    
    Args:
        media_path: Path to the media file
        expected: Expected metadata values
        et: ExifTool helper instance
        
    Returns:
        VerificationResult indicating success/failure
    """
    actual = read_metadata_from_file(media_path, et)
    if actual is None:
        return VerificationResult(
            success=False,
            message="Could not read metadata from file"
        )
    
    result = VerificationResult(success=True)
    issues = []
    
    # Verify date
    if expected.photo_taken_time:
        expected_dt = expected.photo_taken_time.strftime("%Y:%m:%d %H:%M:%S")
        actual_dt = actual.get("EXIF:DateTimeOriginal") or actual.get("DateTimeOriginal")
        
        if actual_dt:
            # Compare just the date/time portion (ignore timezone suffix)
            actual_dt_clean = str(actual_dt)[:19]
            result.date_match = actual_dt_clean == expected_dt
            if not result.date_match:
                issues.append(f"Date mismatch: expected {expected_dt}, got {actual_dt_clean}")
        else:
            result.date_match = False
            issues.append("DateTimeOriginal not found in file")
    else:
        result.date_match = True  # No date to verify
    
    # Verify GPS
    if expected.has_gps:
        actual_lat = actual.get("EXIF:GPSLatitude") or actual.get("GPSLatitude")
        actual_lon = actual.get("EXIF:GPSLongitude") or actual.get("GPSLongitude")
        
        if actual_lat is not None and actual_lon is not None:
            try:
                lat_diff = abs(float(actual_lat) - abs(expected.latitude))
                lon_diff = abs(float(actual_lon) - abs(expected.longitude))
                # Allow small tolerance for floating point
                result.gps_match = lat_diff < 0.0001 and lon_diff < 0.0001
                if not result.gps_match:
                    issues.append(f"GPS mismatch: expected ({expected.latitude}, {expected.longitude}), got ({actual_lat}, {actual_lon})")
            except (ValueError, TypeError):
                result.gps_match = False
                issues.append("Could not parse GPS coordinates")
        else:
            result.gps_match = False
            issues.append("GPS coordinates not found in file")
    else:
        result.gps_match = True  # No GPS to verify
    
    # Verify description
    if expected.description:
        actual_desc = (
            actual.get("EXIF:ImageDescription") 
            or actual.get("ImageDescription")
            or actual.get("XMP:Description")
            or actual.get("IPTC:Caption-Abstract")
        )
        result.description_match = actual_desc == expected.description
        if not result.description_match and actual_desc:
            issues.append(f"Description mismatch")
    else:
        result.description_match = True  # No description to verify
    
    # Overall success
    result.success = result.date_match and result.gps_match and result.description_match
    result.message = "; ".join(issues) if issues else "All metadata verified"
    
    return result


class MetadataProcessor:
    """High-level processor for applying metadata to files."""
    
    def __init__(self):
        self._et: exiftool.ExifToolHelper | None = None
    
    def __enter__(self):
        # Use UTF-8 encoding to avoid Windows cp1252 issues
        self._et = exiftool.ExifToolHelper(encoding="utf-8")
        self._et.__enter__()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._et:
            self._et.__exit__(exc_type, exc_val, exc_tb)
            self._et = None
    
    def process_file(
        self,
        media_path: Path,
        json_path: Path,
        verify: bool = True,
        video_path: Path | None = None
    ) -> tuple[bool, str, VerificationResult | None]:
        """Process a single media file with its JSON metadata.
        
        Args:
            media_path: Path to the media file
            json_path: Path to the JSON metadata file
            verify: Whether to verify the metadata after writing
            video_path: Optional path to Live Photo video file (MP4) to also process
            
        Returns:
            Tuple of (success, message, verification_result)
        """
        if self._et is None:
            return False, "MetadataProcessor not initialized (use with statement)", None
        
        # Parse JSON
        metadata = parse_google_json(json_path)
        if metadata is None:
            return False, f"Failed to parse JSON: {json_path}", None
        
        # Write metadata to main media file
        success, message = write_metadata_to_file(media_path, metadata, self._et)
        if not success:
            return False, message, None
        
        # If this is a Live Photo, also write metadata to the video file
        if video_path:
            video_success, video_message = write_metadata_to_file(video_path, metadata, self._et)
            if not video_success:
                return False, f"Image: {message}; Video: {video_message}", None
            message = f"{message}; Video: {video_message}"
        
        # Verify if requested
        verification = None
        if verify:
            # Verify main media file
            verification = verify_metadata(media_path, metadata, self._et)
            
            # If this is a Live Photo, also verify the video file
            if video_path:
                video_verification = verify_metadata(video_path, metadata, self._et)
                # Combine verification results - both must succeed
                img_date_ok = verification.date_match
                img_gps_ok = verification.gps_match
                img_desc_ok = verification.description_match
                
                verification.success = verification.success and video_verification.success
                verification.date_match = verification.date_match and video_verification.date_match
                verification.gps_match = verification.gps_match and video_verification.gps_match
                verification.description_match = verification.description_match and video_verification.description_match
                
                # Combine messages
                if not verification.success:
                    issues = []
                    if not img_date_ok:
                        issues.append("image date")
                    if not img_gps_ok:
                        issues.append("image GPS")
                    if not img_desc_ok:
                        issues.append("image description")
                    if not video_verification.date_match:
                        issues.append("video date")
                    if not video_verification.gps_match:
                        issues.append("video GPS")
                    if not video_verification.description_match:
                        issues.append("video description")
                    verification.message = f"Verification failed on: {', '.join(issues)}"
                else:
                    verification.message = "All metadata verified (image and video)"
            
            if not verification.success:
                return False, f"Verification failed: {verification.message}", verification
        
        return True, message, verification

