# Google Photos Metadata Fix

A CLI tool to restore metadata from Google Photos Takeout exports to images and videos.

## Features

- **Attach metadata**: Write date, GPS coordinates, and descriptions from JSON files to media files
- **Cleanup mode**: Delete JSON files after verifying metadata was written correctly
- **Recursive processing**: Process entire directory trees
- **Dry-run mode**: Preview changes without modifying files
- **Detailed statistics**: See file counts by extension, directory breakdown, and processing results
- **Verification**: Confirm metadata was written by reading it back

## Prerequisites

**ExifTool** must be installed and available in PATH:

- **Windows**: Download from https://exiftool.org/ and add to PATH
- **macOS**: `brew install exiftool`
- **Linux**: `sudo apt install libimage-exiftool-perl`

## Installation

```bash
# Clone the repository
git clone https://github.com/ivozilkenat/google-photos-metadata-fix.git
cd google-photos-metadata-fix

# Install with uv
uv sync
```

## Usage

### Show statistics

See what files are available for processing:

```bash
gphotos-meta stats /path/to/takeout --recursive
```

### Attach metadata (dry-run)

Preview what will be processed without making changes:

```bash
gphotos-meta attach /path/to/takeout --recursive --dry-run
```

### Attach metadata

Write metadata from JSON files to images:

```bash
gphotos-meta attach /path/to/takeout --recursive
```

Options:
- `-r, --recursive`: Process subdirectories
- `--dry-run`: Preview without making changes
- `--no-verify`: Skip verification after writing
- `-y, --yes`: Skip confirmation prompt

### Cleanup JSON files

Delete JSON files after verifying metadata was written:

```bash
gphotos-meta cleanup /path/to/takeout --recursive
```

Options:
- `-r, --recursive`: Process subdirectories
- `--no-verify`: Delete without verifying (DANGEROUS)
- `-y, --yes`: Skip confirmation prompt

## What metadata is restored?

| JSON Field | EXIF/XMP Tag |
|------------|--------------|
| `photoTakenTime.timestamp` | DateTimeOriginal, CreateDate, ModifyDate |
| `geoData.latitude/longitude` | GPSLatitude, GPSLongitude |
| `geoData.altitude` | GPSAltitude |
| `description` | ImageDescription, XMP:Description, IPTC:Caption-Abstract |

## Google Takeout Structure

The tool handles Google Photos Takeout exports which have:

- Media files (`.jpg`, `.mp4`, `.gif`, etc.)
- Corresponding JSON files (`.supplemental-metadata.json`)
- Some JSON filenames may be truncated (`.supplemental-met.json`, `.su.json`)

## License

MIT

