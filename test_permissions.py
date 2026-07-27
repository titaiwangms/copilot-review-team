import os
import stat
import tempfile
import sys
import _merge_playbook as mp

dir = tempfile.mkdtemp()
target = os.path.join(dir, "target.md")
with open(target, "w") as f:
    f.write("user content\n")
os.chmod(target, 0o600)

source = os.path.join(dir, "source.md")
with open(source, "w") as f:
    f.write("managed content\n")

mp.cmd_install(target, source)
mode = stat.S_IMODE(os.stat(target).st_mode)
print(oct(mode))
