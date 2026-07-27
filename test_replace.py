import os
import tempfile

dir = tempfile.mkdtemp()
target = os.path.join(dir, "target.txt")
with open(target, "w") as f: f.write("target")

symlink = os.path.join(dir, "symlink.txt")
os.symlink(target, symlink)

tmp = os.path.join(dir, "tmp.txt")
with open(tmp, "w") as f: f.write("tmp")

os.replace(tmp, symlink)

print("Is symlink?", os.path.islink(symlink))
