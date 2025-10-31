import os
import ctypes
from app.constants import COMMON_LIBC_FLAGS as uflags
from app import configs
import sys
from pathlib import Path
import tempfile

libc = ctypes.CDLL('libc.so.6')
# Start a sub process with the specified command and run it inside an isolated
# Network, Process, Filesystem namespace all the while keeping access to the 
# Stdin, our and err channels connected to the parents corresponding channels
class ProcessMananger:
    def __init__(self, command, image):
        self.image = image
        self.command = command
        print(self.command)
    def run(self):
        child_sig_rd, child_sig_wr = os.pipe()
        parent_sig_rd, parent_sig_wr = os.pipe()
        child_pid = os.fork()

        runtime_dir = Path(configs.CONTAINER_RUNTIME_ROOT_DIR)/"_".join(self.image.split(":"))/"runtime_dir"
        os.makedirs(Path(runtime_dir)/"old_root", exist_ok=True)

        target_host_uid = 1000
        target_host_gid = 1000
        print(f"[Parent] Changing ownership of '{runtime_dir}' to {target_host_uid}:{target_host_gid}")
        os.chown(runtime_dir, target_host_uid, target_host_gid)
        # Also chown the subdirectory for the old_root
        os.chown(Path(runtime_dir)/"old_root", target_host_uid, target_host_gid)

        if child_pid == 0:
            print(f"Hello from the Child: {child_pid}")
            libc.unshare(uflags.CLONE_NEWUSER |
                          uflags.CLONE_NEWIPC | 
                          uflags.CLONE_NEWNS | 
                          uflags.CLONE_NEWNET |
                          uflags.CLONE_NEWPID |
                          uflags.CLONE_NEWCGROUP |
                          uflags.CLONE_NEWUTS)
            
            # Created uid and gid mapping for the container
            os.close(child_sig_rd)
            os.write(child_sig_wr, b"1")
            print("[Child]: Waiting for the parent to create uid mapping")
            os.read(parent_sig_rd, 1)
            print("[Child] Continuing execution")
            os.close(parent_sig_rd)
            os.setuid(0)
            os.setgid(0)

            # Perform pivot root

            libc.mount(None, "/", None, uflags.MS_REC | uflags.MS_PRIVATE, None)
            libc.mount(str(runtime_dir).encode("utf-8"), str(runtime_dir).encode("utf-8"), None, uflags.MS_BIND, None)
            os.chdir(runtime_dir)
            # TODO: Make this retrive the syscall number based on the current architecture
            syscall_num = 155
            ret = libc.syscall(syscall_num, ".", "./old_root") # pivot root sys call
            if ret != 0:
                errno = ctypes.get_errno()
                raise OSError(errno, f"pivot_root failed: {os.strerror(errno)}")
            libc.umount2("old_root".encode(), 2) # 2 is MNT_DETACH
            os.rmdir("./old_root")
            libc.mount("proc".encode(), "proc".encode(), "proc".encode(), 0, None)
            print("Running command")
            os.system(f"{self.command}")
            # os.system("whoami")
            # os.system("/bin/sh")
            os._exit(1)
            
            
        else:
            print(f"I am the parent: {os.getpid()}")
            print(f"Parent says, my child's PID is: {child_pid}")    
            print("Parent is setting up uid and gid mapping")
            os.close(parent_sig_rd)

            os.read(child_sig_rd, 1)
            try:
                with open(f"/proc/{child_pid}/setgroups", "w") as f:
                    f.write("deny")
                with open(f"/proc/{child_pid}/gid_map", "w") as f:
                    f.write("0 1000 1\n") # Map to user 1000 (e.g., your normal user)
                with open(f"/proc/{child_pid}/uid_map", "w") as f:
                    f.write("0 1000 1\n")
                print("[Parent] UID/GID maps written successfully.")
                os.write(parent_sig_wr, b"1")
                os.close(parent_sig_wr)
                _, status = os.waitpid(child_pid, 0)

            except Exception as e:
                print(f"[Parent] FATAL: Could not write maps: {e}", file=sys.stderr)
                os.kill(child_pid, 9) # Kill the child if mapping fails
                sys.exit(1)




if __name__ == "__main__":
    pm = ProcessMananger(" ".join(sys.argv[2:]), sys.argv[1])
    pm.run()