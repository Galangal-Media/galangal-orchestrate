"""
GitHub issue image extraction and download.

Parses markdown content for image URLs and downloads them locally
so Claude Code can view them during workflow execution.
"""

import hashlib
import re
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# Patterns for finding images in markdown
MARKDOWN_IMAGE_PATTERN = re.compile(
    r'!\[([^\]]*)\]\(([^)]+)\)',  # ![alt text](url)
    re.MULTILINE
)
HTML_IMG_PATTERN = re.compile(
    r'<img[^>]+src=["\']([^"\']+)["\']',  # <img src="url">
    re.IGNORECASE
)

# GitHub domains that host user-uploaded images
GITHUB_IMAGE_DOMAINS = {
    "user-images.githubusercontent.com",
    "github.com",
    "raw.githubusercontent.com",
    "camo.githubusercontent.com",
    "private-user-images.githubusercontent.com",
}

# Supported image extensions
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


def extract_image_urls(markdown_text: str) -> list[dict]:
    """
    Extract image URLs from markdown text.

    Finds both markdown-style images (![alt](url)) and HTML img tags.

    Args:
        markdown_text: Raw markdown content (e.g., GitHub issue body)

    Returns:
        List of dicts with keys: 'url', 'alt_text', 'source' ('markdown' or 'html')
    """
    images = []
    seen_urls = set()

    # Find markdown-style images: ![alt](url)
    for match in MARKDOWN_IMAGE_PATTERN.finditer(markdown_text):
        alt_text = match.group(1)
        url = match.group(2).strip()

        if url and url not in seen_urls and _is_image_url(url):
            images.append({
                "url": url,
                "alt_text": alt_text,
                "source": "markdown",
            })
            seen_urls.add(url)

    # Find HTML img tags: <img src="url">
    for match in HTML_IMG_PATTERN.finditer(markdown_text):
        url = match.group(1).strip()

        if url and url not in seen_urls and _is_image_url(url):
            images.append({
                "url": url,
                "alt_text": "",
                "source": "html",
            })
            seen_urls.add(url)

    return images


def _is_image_url(url: str) -> bool:
    """Check if a URL appears to be an image."""
    try:
        parsed = urlparse(url)

        # Check if it's a GitHub user content URL (these are always images)
        if parsed.netloc in GITHUB_IMAGE_DOMAINS:
            return True

        # Check file extension
        path_lower = parsed.path.lower()
        for ext in IMAGE_EXTENSIONS:
            if path_lower.endswith(ext):
                return True

        # GitHub blob URLs often contain images
        if "blob" in parsed.path and any(
            ext in path_lower for ext in IMAGE_EXTENSIONS
        ):
            return True

        return False
    except Exception:
        return False


def _generate_filename(url: str, alt_text: str, index: int) -> str:
    """Generate a filename for a downloaded image."""
    parsed = urlparse(url)
    path = parsed.path

    # Try to get extension from URL
    ext = ".png"  # Default
    for e in IMAGE_EXTENSIONS:
        if path.lower().endswith(e):
            ext = e
            break

    # Create a descriptive name
    if alt_text:
        # Sanitize alt text for filename
        safe_alt = re.sub(r'[^\w\s-]', '', alt_text)[:30].strip()
        safe_alt = re.sub(r'[\s]+', '_', safe_alt).lower()
        if safe_alt:
            return f"screenshot_{index:02d}_{safe_alt}{ext}"

    # Use hash of URL for uniqueness
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"screenshot_{index:02d}_{url_hash}{ext}"


def download_images(
    images: list[dict],
    output_dir: Path,
    use_gh_auth: bool = True,
) -> list[dict]:
    """
    Download images to a local directory.

    Args:
        images: List of image dicts from extract_image_urls()
        output_dir: Directory to save images (e.g., task_dir/screenshots)
        use_gh_auth: If True, use gh CLI for authenticated downloads

    Returns:
        List of dicts with 'local_path', 'url', 'alt_text', 'success', 'error'
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, img in enumerate(images, 1):
        url = img["url"]
        alt_text = img.get("alt_text", "")
        filename = _generate_filename(url, alt_text, i)
        local_path = output_dir / filename

        result = {
            "url": url,
            "alt_text": alt_text,
            "local_path": str(local_path),
            "success": False,
            "error": None,
        }

        try:
            parsed = urlparse(url)
            is_github_url = parsed.netloc in GITHUB_IMAGE_DOMAINS

            # Try gh CLI for GitHub URLs (handles auth)
            if use_gh_auth and is_github_url:
                success = _download_with_gh(url, local_path)
                if success:
                    result["success"] = True
                    results.append(result)
                    continue

            # Fall back to direct download
            _download_direct(url, local_path)
            result["success"] = True

        except Exception as e:
            result["error"] = str(e)

        results.append(result)

    return results


def _download_with_gh(url: str, output_path: Path) -> bool:
    """
    Download a URL using gh CLI (handles GitHub authentication).

    Args:
        url: URL to download
        output_path: Path to save the file

    Returns:
        True if successful, False otherwise
    """
    try:
        # For private-user-images.githubusercontent.com, we need to use gh api
        # with the raw URL to get authenticated access
        parsed = urlparse(url)

        if parsed.netloc == "private-user-images.githubusercontent.com":
            # Private images need authenticated download via gh api
            # Extract the path and use gh api to fetch it
            result = subprocess.run(
                ["gh", "api", "-H", "Accept: application/octet-stream", url],
                capture_output=True,
                timeout=60,
            )
            if result.returncode == 0:
                output_path.write_bytes(result.stdout)
                return True
            return False

        # For other GitHub URLs, use curl with gh auth token
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False

        token = result.stdout.strip()
        if not token:
            return False

        # Download with auth header
        headers = {"Authorization": f"token {token}"}
        request = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(request, timeout=60) as response:
            output_path.write_bytes(response.read())
        return True

    except Exception:
        return False


def _download_direct(url: str, output_path: Path) -> None:
    """
    Download a URL directly without authentication.

    Args:
        url: URL to download
        output_path: Path to save the file

    Raises:
        Exception on download failure
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; galangal-orchestrate/1.0)"
    }
    request = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(request, timeout=60) as response:
        output_path.write_bytes(response.read())


def download_issue_images(
    markdown_body: str,
    task_dir: Path,
    screenshots_subdir: str = "screenshots",
) -> list[str]:
    """
    Extract and download all images from a GitHub issue body.

    This is the main entry point for integrating with task creation.

    Args:
        markdown_body: The raw issue body markdown
        task_dir: Base directory for the task (e.g., galangal-tasks/issue-42-fix-bug)
        screenshots_subdir: Subdirectory name for screenshots (default: "screenshots")

    Returns:
        List of local file paths for successfully downloaded images
    """
    images = extract_image_urls(markdown_body)
    if not images:
        return []

    output_dir = task_dir / screenshots_subdir
    results = download_images(images, output_dir)

    # Return only successful downloads
    return [r["local_path"] for r in results if r["success"]]
