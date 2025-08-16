#!/usr/bin/env python3
"""
Python test that mirrors the Go testProcessIsolation function.
Tests that the Docker implementation properly isolates processes (PID namespace).
"""

import argparse
import logging
import os
import subprocess
import sys


def setup_logging():
    """Setup logging similar to the Go harness"""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(levelname)s: %(message)s'
    )
    return logging.getLogger(__name__)


def test_process_isolation(docker_image, logger):
    """
    Test process isolation by running a command that should report PID 1
    when properly isolated in its own PID namespace.
    """
    # Get the path to your_docker.sh (assuming it's in the same directory as this script)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    docker_script = os.path.join(script_dir, "your_docker.sh")
    
    # Build the command (equivalent to the Go executable.Run call)
    cmd = [
        docker_script,
        "run", docker_image,
        "/usr/local/bin/docker-explorer", "mypid"
    ]
    
    logger.debug(f"Executing: {' '.join(cmd)}")
    
    # Run the command and capture output
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        logger.error("Command timed out after 30 seconds")
        return False
    except FileNotFoundError:
        logger.error(f"Could not find {docker_script}")
        return False
    
    # Debug output
    if result.stdout:
        logger.debug(f"STDOUT: {result.stdout}")
    if result.stderr:
        logger.debug(f"STDERR: {result.stderr}")
    logger.debug(f"Exit code: {result.returncode}")
    
    # Assert stdout is exactly "1\n" (process should have PID 1 in isolated namespace)
    expected_output = "1\n"
    if result.stdout != expected_output:
        logger.error(f"Expected stdout to be '{expected_output}', got: '{result.stdout}'")
        return False
    
    # Implicitly check that exit code is 0 (success)
    if result.returncode != 0:
        logger.error(f"Expected exit code 0, got: {result.returncode}")
        return False
    
    logger.info("✓ Process isolation test passed!")
    return True


def main():
    """Main function with argument parsing"""
    parser = argparse.ArgumentParser(description="Test Docker process isolation")
    parser.add_argument(
        "--image", 
        default=os.environ.get("DOCKER_IMAGE_STAGE_1", "busybox:latest"),
        help="Docker image to use for testing (default: busybox:latest or DOCKER_IMAGE_STAGE_1 env var)"
    )
    
    args = parser.parse_args()
    logger = setup_logging()
    
    logger.info(f"Testing process isolation with image: {args.image}")
    
    success = test_process_isolation(args.image, logger)
    
    if success:
        logger.info("All tests passed!")
        sys.exit(0)
    else:
        logger.error("Test failed!")
        sys.exit(1)


if __name__ == "__main__":
    main() 