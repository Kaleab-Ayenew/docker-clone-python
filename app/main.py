import subprocess
import shutil
import sys
import os
import secrets
from app.pull import docker_pull, docker_run
import tempfile
import uuid
from pathlib import Path
from contextlib import contextmanager
from app.configs import CGROUP_PATH, MEM_UNIT_MAP, LOCAL_IMAGE_REGISTRY


@contextmanager
def manage_cgroup(image_name: str, mem_limit: str, cpu_percent: int):
    """
    A context manager to create, configure, and clean up a cgroup for a container.

    Yields:
        The Path object for the created cgroup directory.
    """
    # 1. SETUP: Create a unique cgroup directory
    cgroup_base = Path(CGROUP_PATH) / "mydocker"
    cgroup_base.mkdir(exist_ok=True)
    
    container_id = f"{image_name.replace(':', '_')}_{uuid.uuid4().hex[:8]}"
    cgroup_path = cgroup_base / container_id
    cgroup_path.mkdir()

    try:
        (cgroup_base / "cgroup.subtree_control").write_text("+cpu +memory")
    except OSError as e:
        print(f"We got an error while creating cgroup.subtree_control: {e}", "We are ignoring it")
        pass


    try:

        if mem_limit:
            amount = "".join(c for c in mem_limit.lower() if c.isdigit())
            unit = "".join(c for c in mem_limit.lower() if not c.isdigit())
            try:
                amount_in_bytes = int(amount) * MEM_UNIT_MAP[unit]
                (cgroup_path / "memory.max").write_text(str(amount_in_bytes))
            except (KeyError, ValueError) as e:
                print(f"Invalid memory limit format: {mem_limit}. Error: {e}", file=sys.stderr)
        
        if cpu_percent:
            max_us = int(cpu_percent * 1000)
            quota_us = 100000
            (cgroup_path / "cpu.max").write_text(f"{max_us} {quota_us}")

        yield cgroup_path

    finally:
        try:
            os.rmdir(cgroup_path)
        except OSError as e:
            print(f"Error cleaning up cgroup {cgroup_path}: {e}", file=sys.stderr)


def main(image):

        command = sys.argv[3]
        args = sys.argv[4:]
        image_dir = docker_pull(image, LOCAL_IMAGE_REGISTRY)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            docker_run(temp_dir, image_dir)
            chrooted_cmd = ["unshare", "-fp", "--mount-proc", "--", "chroot", temp_dir, command.split("/")[-1]]
            try:
                with manage_cgroup(image, "500MB", 20) as cgroup_path:

                    container_process = subprocess.Popen([*chrooted_cmd, *args], stderr=sys.stderr,stdout=sys.stdout, stdin=sys.stdin, text=True)
                    (cgroup_path/"cgroup.procs").write_text(str(container_process.pid))
                    con_stdout, con_stderr = container_process.communicate()
                    if con_stdout:
                        print(con_stdout.strip(), file=sys.stdout)
                    if con_stderr:
                        print(con_stderr.strip(), file=sys.stderr)
                    sys.exit(container_process.returncode)
            except FileNotFoundError:
                print("Error: Command not found.", file=sys.stderr)
                sys.exit()
            except Exception as e:                
                print(f"An unexpected error occurred: {e}", file=sys.stderr)
                raise(e)
            




if __name__ == "__main__":
    print(sys.argv[2])
    main(sys.argv[2])
