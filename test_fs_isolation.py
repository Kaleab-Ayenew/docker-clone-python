#!/usr/bin/env python3
"""
Python test that mirrors the Go testFSIsolation function.
Tests that the Docker implementation properly isolates the filesystem.
"""

import argparse
import logging
import os
import subprocess
import sys
import tempfile


def setup_logging():
    """Setup logging similar to the Go harness"""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(levelname)s: %(message)s'
    )
    return logging.getLogger(__name__)


def test_fs_isolation(docker_image, logger):
    """
    Test filesystem isolation by creating a temp directory on the host
    and verifying it's not accessible from within the container.
    """
    # Create temporary directory on host (equivalent to ioutil.TempDir)
    with tempfile.TemporaryDirectory() as temp_dir:
        logger.debug(f"Created temp dir on host: {temp_dir}")
        
        # Get the path to your_docker.sh (assuming it's in the same directory as this script)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        docker_script = os.path.join(script_dir, "your_docker.sh")
        
        # Build the command (equivalent to the Go executable.Run call)
        cmd = [
            docker_script,
            "run", docker_image,
            "/usr/local/bin/docker-explorer", "ls", temp_dir
        ]
        
        logger.debug(f"Executing: {' '.join(cmd)}")
        logger.debug("(expecting that the directory won't be accessible)")
        
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
        
        # Assert stdout contains "No such file or directory"
        combined_output = result.stdout + result.stderr
        if "no such file or directory" not in combined_output:
            logger.error(f"Expected 'No such file or directory' in output, got: {combined_output}")
            return False
        
        # Assert exit code is 2
        if result.returncode != 2:
            logger.error(f"Expected exit code 2, got: {result.returncode}")
            return False
        
        logger.info("✓ Filesystem isolation test passed!")
        return True


def main():
    """Main function with argument parsing"""
    parser = argparse.ArgumentParser(description="Test Docker filesystem isolation")
    parser.add_argument(
        "--image", 
        default=os.environ.get("DOCKER_IMAGE_STAGE_1", "busybox:latest"),
        help="Docker image to use for testing (default: busybox:latest or DOCKER_IMAGE_STAGE_1 env var)"
    )
    
    args = parser.parse_args()
    logger = setup_logging()
    
    logger.info(f"Testing filesystem isolation with image: {args.image}")
    
    success = test_fs_isolation(args.image, logger)
    
    if success:
        logger.info("All tests passed!")
        sys.exit(0)
    else:
        logger.error("Test failed!")
        sys.exit(1)


if __name__ == "__main__":
    main() 