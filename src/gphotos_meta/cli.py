"""CLI entry point for Google Photos Metadata Fix tool."""

import argparse
import sys
from pathlib import Path

from rich.console import Console

from .metadata import MetadataProcessor, check_exiftool_available, parse_google_json
from .reporter import ProcessingStats, Reporter
from .scanner import ScanResult, scan_directory


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="gphotos-meta",
        description="Restore metadata from Google Photos Takeout exports to images and videos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show statistics for a directory
  gphotos-meta stats /path/to/takeout --recursive
  
  # Preview what will be processed (dry-run)
  gphotos-meta attach /path/to/takeout --recursive --dry-run
  
  # Attach metadata to all files recursively (JSON files are preserved)
  gphotos-meta attach /path/to/takeout --recursive
  
  # Re-run attach if needed (safe to run multiple times)
  gphotos-meta attach /path/to/takeout --recursive
  
  # Delete JSON files ONLY after verifying metadata was written
  gphotos-meta cleanup /path/to/takeout --recursive

Note:
  The 'attach' command never deletes JSON files - you can re-run it safely.
  Use 'cleanup' only when you're sure metadata was written correctly.

Prerequisites:
  ExifTool must be installed and available in PATH.
  Download from: https://exiftool.org/
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")
    
    # Stats command
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show statistics about files in a directory"
    )
    stats_parser.add_argument(
        "directory",
        type=Path,
        help="Directory to scan"
    )
    stats_parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Scan subdirectories recursively"
    )
    
    # Attach command
    attach_parser = subparsers.add_parser(
        "attach",
        help="Attach metadata from JSON files to media files (JSON files are preserved)"
    )
    attach_parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing media and JSON files"
    )
    attach_parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Process subdirectories recursively"
    )
    attach_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    attach_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip verification after writing metadata"
    )
    attach_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt"
    )
    
    # Cleanup command
    cleanup_parser = subparsers.add_parser(
        "cleanup",
        help="Delete JSON metadata files after verification"
    )
    cleanup_parser.add_argument(
        "directory",
        type=Path,
        help="Directory containing JSON files to clean up"
    )
    cleanup_parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Process subdirectories recursively"
    )
    cleanup_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Delete JSON files without verifying metadata was written (DANGEROUS)"
    )
    cleanup_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt"
    )
    
    return parser


def cmd_stats(args: argparse.Namespace, reporter: Reporter) -> int:
    """Handle the stats command."""
    directory = args.directory.resolve()
    
    if not directory.exists():
        reporter.print_error(f"Directory not found: {directory}")
        return 1
    
    reporter.print_info(f"Scanning directory: {directory}")
    result = scan_directory(directory, recursive=args.recursive)
    
    reporter.print_scan_stats(result, directory, args.recursive)
    reporter.print_extension_breakdown(result)
    reporter.print_directory_breakdown(result)
    reporter.print_sample_files(result)
    
    return 0


def cmd_attach(args: argparse.Namespace, reporter: Reporter) -> int:
    """Handle the attach command."""
    directory = args.directory.resolve()
    
    if not directory.exists():
        reporter.print_error(f"Directory not found: {directory}")
        return 1
    
    # Check ExifTool availability
    available, message = check_exiftool_available()
    if not available:
        reporter.print_error(message)
        return 1
    reporter.print_info(message)
    
    # Scan directory
    reporter.print_info(f"Scanning directory: {directory}")
    result = scan_directory(directory, recursive=args.recursive)
    
    if not result.pairs:
        reporter.print_warning("No files found to process")
        return 0
    
    # Show statistics
    reporter.print_scan_stats(result, directory, args.recursive)
    reporter.print_extension_breakdown(result)
    
    if args.dry_run:
        reporter.print_info("Dry run mode - no changes will be made")
        reporter.print_sample_files(result, count=20)
        return 0
    
    # Confirm action
    if not args.yes:
        if not reporter.confirm_action(
            f"This will modify {len(result.pairs)} files. Proceed?"
        ):
            reporter.print_info("Operation cancelled")
            return 0
    
    # Process files
    stats = ProcessingStats(total=len(result.pairs))
    
    with reporter.create_progress() as progress:
        task = progress.add_task("Processing files...", total=len(result.pairs))
        
        with MetadataProcessor() as processor:
            for pair in result.pairs:
                success, message, verification = processor.process_file(
                    pair.media_path,
                    pair.json_path,
                    verify=not args.no_verify,
                    video_path=pair.video_path
                )
                
                if success:
                    stats.successful += 1
                    if verification:
                        stats.verified += 1
                else:
                    stats.failed += 1
                    stats.failures.append((pair.media_path, message))
                    if verification and not verification.success:
                        stats.verification_failed += 1
                        stats.verification_failures.append(
                            (pair.media_path, verification.message)
                        )
                
                progress.update(task, advance=1)
    
    reporter.print_processing_results(stats)
    
    # Return non-zero if there were failures
    return 1 if stats.failed > 0 else 0


def cmd_cleanup(args: argparse.Namespace, reporter: Reporter) -> int:
    """Handle the cleanup command."""
    directory = args.directory.resolve()
    
    if not directory.exists():
        reporter.print_error(f"Directory not found: {directory}")
        return 1
    
    # Check ExifTool availability (needed for verification)
    if not args.no_verify:
        available, message = check_exiftool_available()
        if not available:
            reporter.print_error(message)
            return 1
        reporter.print_info(message)
    
    # Scan directory
    reporter.print_info(f"Scanning directory: {directory}")
    result = scan_directory(directory, recursive=args.recursive)
    
    if not result.pairs:
        reporter.print_warning("No JSON files found to clean up")
        return 0
    
    # Show what will be deleted
    reporter.print_scan_stats(result, directory, args.recursive)
    
    # Confirm action
    if not args.yes:
        warning = "This will DELETE JSON files"
        if args.no_verify:
            warning += " WITHOUT verifying metadata was written (DANGEROUS)"
        
        if not reporter.confirm_action(
            f"{warning}. {len(result.pairs)} files will be deleted. Proceed?"
        ):
            reporter.print_info("Operation cancelled")
            return 0
    
    deleted = 0
    failed = 0
    skipped = 0
    
    with reporter.create_progress() as progress:
        task = progress.add_task("Cleaning up...", total=len(result.pairs))
        
        if args.no_verify:
            # Delete without verification
            for pair in result.pairs:
                try:
                    pair.json_path.unlink()
                    deleted += 1
                except OSError as e:
                    failed += 1
                    reporter.print_error(f"Failed to delete {pair.json_path}: {e}")
                
                progress.update(task, advance=1)
        else:
            # Verify before deleting
            with MetadataProcessor() as processor:
                for pair in result.pairs:
                    # Parse expected metadata
                    metadata = parse_google_json(pair.json_path)
                    if metadata is None:
                        skipped += 1
                        progress.update(task, advance=1)
                        continue
                    
                    # Verify metadata is in the file(s)
                    from .metadata import verify_metadata
                    verification = verify_metadata(
                        pair.media_path,
                        metadata,
                        processor._et
                    )
                    
                    # If this is a Live Photo, also verify the video file
                    if pair.video_path:
                        video_verification = verify_metadata(
                            pair.video_path,
                            metadata,
                            processor._et
                        )
                        # Both must succeed
                        verification.success = verification.success and video_verification.success
                        verification.date_match = verification.date_match and video_verification.date_match
                        verification.gps_match = verification.gps_match and video_verification.gps_match
                        verification.description_match = verification.description_match and video_verification.description_match
                        
                        if not verification.success:
                            # Combine messages
                            issues = []
                            if not verification.date_match:
                                issues.append("image or video date")
                            if not verification.gps_match:
                                issues.append("image or video GPS")
                            if not verification.description_match:
                                issues.append("image or video description")
                            verification.message = f"Verification failed on: {', '.join(issues)}"
                    
                    if verification.success:
                        try:
                            pair.json_path.unlink()
                            deleted += 1
                        except OSError as e:
                            failed += 1
                            reporter.print_error(f"Failed to delete {pair.json_path}: {e}")
                    else:
                        skipped += 1
                        reporter.print_warning(
                            f"Skipping {pair.json_path.name}: {verification.message}"
                        )
                    
                    progress.update(task, advance=1)
    
    reporter.print_cleanup_results(deleted, failed, skipped)
    
    # Also clean up orphan JSONs (JSON files without matching media)
    if result.orphan_jsons:
        reporter.print_warning(
            f"Found {len(result.orphan_jsons)} orphan JSON files (no matching media). "
            "These were NOT deleted."
        )
    
    return 1 if failed > 0 else 0


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    console = Console()
    reporter = Reporter(console)
    
    try:
        if args.command == "stats":
            return cmd_stats(args, reporter)
        elif args.command == "attach":
            return cmd_attach(args, reporter)
        elif args.command == "cleanup":
            return cmd_cleanup(args, reporter)
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        reporter.print_warning("\nOperation cancelled by user")
        return 130
    except Exception as e:
        reporter.print_error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

