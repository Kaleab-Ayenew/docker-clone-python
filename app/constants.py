from dataclasses import dataclass

@dataclass(frozen=True)
class CommonFlags:
    """Constants for Linux unshare flags used in namespace isolation."""
    CLONE_NEWNS: int = 0x00020000      # Mount namespace (filesystem)
    CLONE_NEWUTS: int = 0x04000000     # UTS namespace (hostname)
    CLONE_NEWIPC: int = 0x08000000     # IPC namespace
    CLONE_NEWUSER: int = 0x10000000    # User namespace
    CLONE_NEWPID: int = 0x20000000     # PID namespace
    CLONE_NEWNET: int = 0x40000000     # Network namespace
    CLONE_NEWCGROUP: int = 0x02000000  # Cgroup namespace
    MS_REC: int = 0x4000 # Recursive mounts
    MS_PRIVATE: int = 0x40000 # Mount private
    MS_BIND: int = 0x1000 # Bind mount


COMMON_LIBC_FLAGS = CommonFlags()