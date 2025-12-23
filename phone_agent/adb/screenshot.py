"""Screenshot utilities for capturing Android device screen."""

import base64
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Tuple

from PIL import Image

from phone_agent.config.timing import TIMING_CONFIG


@dataclass
class Screenshot:
    """Represents a captured screenshot."""

    base64_data: str
    width: int
    height: int
    is_sensitive: bool = False


def get_screenshot(
    device_id: str | None = None, timeout: int | None = None
) -> Screenshot:
    """
    Capture a screenshot from the connected Android device.

    Args:
        device_id: Optional ADB device ID for multi-device setups.
        timeout: Timeout in seconds for screenshot operations. If None, uses TIMING_CONFIG.

    Returns:
        Screenshot object containing base64 data and dimensions.

    Note:
        If the screenshot fails (e.g., on sensitive screens like payment pages),
        a black fallback image is returned with is_sensitive=True.

        The function automatically retries on timeout failures up to max_retries times.
    """
    if timeout is None:
        timeout = int(TIMING_CONFIG.screenshot.screencap_timeout)

    max_retries = TIMING_CONFIG.screenshot.max_retries
    pull_timeout = int(TIMING_CONFIG.screenshot.pull_timeout)

    for attempt in range(max_retries + 1):
        try:
            screenshot = _attempt_screenshot(device_id, timeout, pull_timeout)
            if screenshot is not None:
                return screenshot
        except subprocess.TimeoutExpired as e:
            if attempt < max_retries:
                print(
                    f"Screenshot timeout (attempt {attempt + 1}/{max_retries + 1}), retrying..."
                )
                time.sleep(1)  # Wait before retry
                continue
            else:
                print(
                    f"Screenshot error: Command '{' '.join(e.cmd)}' timed out after {timeout} seconds"
                )
                return _create_fallback_screenshot(is_sensitive=False)
        except Exception as e:
            print(f"Screenshot error: {e}")
            return _create_fallback_screenshot(is_sensitive=False)

    return _create_fallback_screenshot(is_sensitive=False)


def _attempt_screenshot(
    device_id: str | None, screencap_timeout: int, pull_timeout: int
) -> Screenshot | None:
    """
    Attempt a single screenshot operation.

    Returns:
        Screenshot object if successful, None if it fails, raises exception on timeout.
    """
    temp_path = os.path.join(tempfile.gettempdir(), f"screenshot_{uuid.uuid4()}.png")
    adb_prefix = _get_adb_prefix(device_id)

    # Execute screenshot command on device
    result = subprocess.run(
        adb_prefix + ["shell", "screencap", "-p", "/sdcard/tmp.png"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=screencap_timeout,
    )

    # Check for screenshot failure (sensitive screen)
    output = result.stdout + result.stderr
    if "Status: -1" in output or "Failed" in output:
        return _create_fallback_screenshot(is_sensitive=True)

    # Pull screenshot to local temp path
    subprocess.run(
        adb_prefix + ["pull", "/sdcard/tmp.png", temp_path],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=pull_timeout,
    )

    if not os.path.exists(temp_path):
        return _create_fallback_screenshot(is_sensitive=False)

    # Read and encode image
    img = Image.open(temp_path)
    width, height = img.size

    buffered = BytesIO()
    img.save(buffered, format="PNG")
    base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

    # Cleanup
    os.remove(temp_path)

    return Screenshot(
        base64_data=base64_data, width=width, height=height, is_sensitive=False
    )


def _get_adb_prefix(device_id: str | None) -> list:
    """Get ADB command prefix with optional device specifier."""
    if device_id:
        return ["adb", "-s", device_id]
    return ["adb"]


def _create_fallback_screenshot(is_sensitive: bool) -> Screenshot:
    """Create a black fallback image when screenshot fails."""
    default_width, default_height = 1080, 2400

    black_img = Image.new("RGB", (default_width, default_height), color="black")
    buffered = BytesIO()
    black_img.save(buffered, format="PNG")
    base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return Screenshot(
        base64_data=base64_data,
        width=default_width,
        height=default_height,
        is_sensitive=is_sensitive,
    )
