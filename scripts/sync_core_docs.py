import os
import shutil
from pathlib import Path

def sync():
    core_dir = Path("../Karcytics")
    if not core_dir.exists():
        print(f"Warning: Core directory {core_dir.absolute()} not found. Skipping sync.")
        return

    install_src = core_dir / "docs" / "user" / "06_Installation.md"
    install_dest = Path("docs") / "internal" / "06_Installation.md"
    
    # In core, the images are in docs/user/image/06_Installation
    img_src = core_dir / "docs" / "user" / "image" / "06_Installation"
    # But when rendered into flow's docs/index.md, the relative path `image/...` 
    # looks in docs/image/
    img_dest = Path("docs") / "image" / "06_Installation"

    # Copy markdown
    install_dest.parent.mkdir(parents=True, exist_ok=True)
    if install_src.exists():
        shutil.copy2(install_src, install_dest)
        print(f"Copied {install_src} to {install_dest}")
    
    # Copy images
    if img_src.exists():
        if img_dest.exists():
            shutil.rmtree(img_dest)
        img_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(img_src, img_dest)
        print(f"Copied images from {img_src} to {img_dest}")

if __name__ == "__main__":
    sync()
